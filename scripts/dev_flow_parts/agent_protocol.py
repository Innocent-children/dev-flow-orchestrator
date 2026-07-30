# Loaded by scripts/dev_flow.py into its shared namespace.  This fragment owns
# model-visible protocol envelopes only; workflow truth and artifact storage
# are injected controller services.
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable, Iterable, Mapping, Sequence


AGENT_PROTOCOL = "agent-v1"
AGENT_NODE_RESULT_CANDIDATE_SCHEMA = (
    "dev-flow-agent-node-result-candidate/v1"
)
ARTIFACT_REFERENCE_SCHEMA = "dev-flow-artifact-reference/v1"
TASK_NEXT_BUDGET = 1024
HOOK_CHECKPOINT_BUDGET = 600
MUTATION_RECEIPT_BUDGET = 1024
NODE_RESULT_BUDGET = 2048
NODE_RESULT_SUMMARY_BUDGET = 512
_SHA256_VALUE_RE = re.compile(r"^[0-9a-f]{64}$")
_NODE_RESULT_STATES = frozenset(
    {
        "waiting",
        "blocked",
        "succeeded",
        "failed",
        "skipped",
    }
)


class AgentProtocolError(Exception):
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


def _canonical_protocol_value(value: object, path: str = "$") -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise AgentProtocolError(
            "PROTOCOL_FIELD_INVALID",
            "protocol values must not use floating-point numbers",
            details={"path": path},
        )
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise AgentProtocolError(
                    "PROTOCOL_FIELD_INVALID",
                    "protocol object keys must be strings",
                    details={"path": path},
                )
            result[key] = _canonical_protocol_value(
                item, f"{path}/{key}"
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _canonical_protocol_value(item, f"{path}/{index}")
            for index, item in enumerate(value)
        ]
    raise AgentProtocolError(
        "PROTOCOL_FIELD_INVALID",
        "protocol values must be canonical JSON",
        details={"path": path, "type": type(value).__name__},
    )


def canonical_protocol_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _canonical_protocol_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise AgentProtocolError(
            "PROTOCOL_SERIALIZATION_FAILED",
            "protocol payload cannot be canonically serialized",
        ) from exc


def protocol_size(value: object) -> int:
    return len(canonical_protocol_bytes(value))


def _protocol_digest(value: object) -> str:
    return hashlib.sha256(canonical_protocol_bytes(value)).hexdigest()


def _required_string(
    value: object, field: str, *, maximum_bytes: int | None = None
) -> str:
    if not isinstance(value, str) or not value:
        raise AgentProtocolError(
            "PROTOCOL_FIELD_REQUIRED",
            f"{field} must be a non-empty string",
            details={"field": field},
        )
    encoded = value.encode("utf-8")
    if maximum_bytes is not None and len(encoded) > maximum_bytes:
        raise AgentProtocolError(
            "PROTOCOL_FIELD_TOO_LARGE",
            f"{field} exceeds its UTF-8 byte budget",
            details={
                "field": field,
                "size": len(encoded),
                "budget": maximum_bytes,
            },
        )
    return value


def _required_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentProtocolError(
            "PROTOCOL_FIELD_REQUIRED",
            f"{field} must be a non-negative integer",
            details={"field": field},
        )
    return value


def validate_artifact_reference(
    value: Mapping[str, object],
    *,
    expected_task_id: str | None = None,
) -> dict[str, object]:
    allowed = {
        "schema",
        "artifact_id",
        "task_id",
        "semantic_sha256",
        "sha256",
        "size",
        "media_type",
        "kind",
        "locator",
        "path_identity_sha256",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AgentProtocolError(
            "ARTIFACT_REFERENCE_UNKNOWN_FIELD",
            "artifact reference contains unsupported fields",
            details={"fields": unknown},
        )
    if value.get("schema") != ARTIFACT_REFERENCE_SCHEMA:
        raise AgentProtocolError(
            "ARTIFACT_REFERENCE_UNSUPPORTED",
            "artifact reference schema is unsupported",
            details={"schema": value.get("schema")},
        )
    task_id = _required_string(value.get("task_id"), "task_id")
    if expected_task_id is not None and task_id != expected_task_id:
        raise AgentProtocolError(
            "ARTIFACT_TASK_SCOPE_MISMATCH",
            "artifact reference belongs to another task",
            details={"task_id": expected_task_id},
        )
    result: dict[str, object] = {
        "schema": ARTIFACT_REFERENCE_SCHEMA,
        "artifact_id": _required_string(
            value.get("artifact_id"), "artifact_id"
        ),
        "task_id": task_id,
        "semantic_sha256": _required_string(
            value.get("semantic_sha256"), "semantic_sha256"
        ),
        "sha256": _required_string(value.get("sha256"), "sha256"),
        "size": _required_nonnegative_int(value.get("size"), "size"),
        "media_type": _required_string(
            value.get("media_type"), "media_type"
        ),
        "kind": _required_string(value.get("kind"), "kind"),
        "locator": _required_string(value.get("locator"), "locator"),
    }
    for field in ("semantic_sha256", "sha256"):
        if not _SHA256_VALUE_RE.fullmatch(str(result[field])):
            raise AgentProtocolError(
                "ARTIFACT_DIGEST_INVALID",
                f"{field} must be a lowercase SHA-256 value",
                details={"field": field},
            )
    path_identity = value.get("path_identity_sha256")
    if path_identity is not None:
        path_identity = _required_string(
            path_identity, "path_identity_sha256"
        )
        if not _SHA256_VALUE_RE.fullmatch(path_identity):
            raise AgentProtocolError(
                "ARTIFACT_DIGEST_INVALID",
                "path_identity_sha256 must be a lowercase SHA-256 value",
                details={"field": "path_identity_sha256"},
            )
        result["path_identity_sha256"] = path_identity
    return result


def _write_overflow_artifact(
    payload: Mapping[str, object],
    *,
    task_id: str,
    kind: str,
    artifact_writer: Callable[
        [str, str, bytes], Mapping[str, object]
    ]
    | None,
) -> dict[str, object]:
    if artifact_writer is None:
        raise AgentProtocolError(
            "PROTOCOL_OVERFLOW_STORAGE_REQUIRED",
            "required protocol detail exceeds its inline budget",
            details={"kind": kind, "size": protocol_size(payload)},
        )
    content = canonical_protocol_bytes(payload)
    try:
        reference = artifact_writer(task_id, kind, content)
    except Exception as exc:
        raise AgentProtocolError(
            "PROTOCOL_OVERFLOW_STORAGE_FAILED",
            "oversized required detail could not be stored",
            details={"kind": kind, "error": str(exc)},
        ) from exc
    validated = validate_artifact_reference(
        reference, expected_task_id=task_id
    )
    if validated["sha256"] != hashlib.sha256(content).hexdigest():
        raise AgentProtocolError(
            "PROTOCOL_OVERFLOW_STORAGE_INVALID",
            "stored overflow artifact digest does not match its content",
            details={"artifact_id": validated["artifact_id"]},
        )
    if validated["size"] != len(content):
        raise AgentProtocolError(
            "PROTOCOL_OVERFLOW_STORAGE_INVALID",
            "stored overflow artifact size does not match its content",
            details={"artifact_id": validated["artifact_id"]},
        )
    return validated


def _workflow_identity(
    workflow_ref: Mapping[str, object],
) -> dict[str, object]:
    allowed = {
        "id",
        "version",
        "schema",
        "graph_sha256",
        "bundle_sha256",
        "adapter",
    }
    return {
        key: workflow_ref[key]
        for key in (
            "id",
            "version",
            "schema",
            "graph_sha256",
            "bundle_sha256",
            "adapter",
        )
        if key in workflow_ref and key in allowed
    }


def build_task_next(
    task: Mapping[str, object],
    *,
    workflow_ref: Mapping[str, object],
    frontier: Sequence[Mapping[str, object]],
    actions: Sequence[Mapping[str, object]],
    condition: Mapping[str, object] | None = None,
    locator: Mapping[str, object] | None = None,
    revision_delta: Mapping[str, object] | None = None,
    artifact_writer: Callable[
        [str, str, bytes], Mapping[str, object]
    ]
    | None = None,
) -> dict[str, object]:
    task_id = _required_string(task.get("task_id"), "task_id")
    revision = _required_nonnegative_int(task.get("revision"), "revision")
    stable_frontier = sorted(
        (_canonical_protocol_value(dict(item)) for item in frontier),
        key=lambda item: (
            str(item.get("node_instance_id", "")).encode("utf-8"),
            str(item.get("repository_id", "")).encode("utf-8"),
            str(item.get("node_id", "")).encode("utf-8"),
        ),
    )
    stable_actions = sorted(
        (_canonical_protocol_value(dict(item)) for item in actions),
        key=lambda item: (
            str(item.get("action_id", "")).encode("utf-8"),
            str(item.get("edge_id", "")).encode("utf-8"),
        ),
    )
    for index, item in enumerate(stable_frontier):
        if not isinstance(item, dict) or not item.get("node_id"):
            raise AgentProtocolError(
                "PROTOCOL_FIELD_REQUIRED",
                "frontier entries require a stable node_id",
                details={"field": f"frontier/{index}/node_id"},
            )
    for index, item in enumerate(stable_actions):
        if not isinstance(item, dict) or not item.get("action_id"):
            raise AgentProtocolError(
                "PROTOCOL_FIELD_REQUIRED",
                "actions require a stable action_id",
                details={"field": f"actions/{index}/action_id"},
            )
    frontier_source = {
        "frontier": stable_frontier,
        "actions": stable_actions,
        "condition": condition or {},
    }
    payload: dict[str, object] = {
        "contract": AGENT_PROTOCOL,
        "task_id": task_id,
        "revision": revision,
        "workflow": _workflow_identity(workflow_ref),
        "frontier": stable_frontier,
        "actions": stable_actions,
        "frontier_sha256": _protocol_digest(frontier_source),
    }
    if condition:
        payload["condition"] = _canonical_protocol_value(dict(condition))
    if locator:
        payload["locator"] = _canonical_protocol_value(dict(locator))
    if revision_delta is not None:
        payload["revision_delta"] = _canonical_protocol_value(
            dict(revision_delta)
        )
    if protocol_size(payload) <= TASK_NEXT_BUDGET:
        return payload
    overflow_payload = dict(payload)
    # A revision delta is checkpoint-specific metadata layered over the
    # current projection.  Keep the stored current projection reusable for
    # callers with different checkpoints and carry the delta in the bounded
    # outer envelope.
    overflow_payload.pop("revision_delta", None)
    reference = _write_overflow_artifact(
        overflow_payload,
        task_id=task_id,
        kind="task-next",
        artifact_writer=artifact_writer,
    )
    bounded = {
        "contract": AGENT_PROTOCOL,
        "task_id": task_id,
        "revision": revision,
        "frontier_sha256": payload["frontier_sha256"],
        "condition": {
            "kind": "detail-in-artifact",
            "frontier_count": len(stable_frontier),
            "action_count": len(stable_actions),
        },
        "artifact": reference,
    }
    if revision_delta is not None:
        bounded["revision_delta"] = payload["revision_delta"]
    if protocol_size(bounded) > TASK_NEXT_BUDGET:
        raise AgentProtocolError(
            "PROTOCOL_OVERFLOW_REFERENCE_TOO_LARGE",
            "validated overflow reference cannot fit the task-next budget",
            details={"size": protocol_size(bounded)},
        )
    return bounded


def build_hook_checkpoint(
    task_next: Mapping[str, object],
    *,
    controller_locator: str,
) -> dict[str, object]:
    payload = {
        "contract": "dev-flow-hook-checkpoint/v1",
        "task_id": task_next.get("task_id"),
        "revision": task_next.get("revision"),
        "frontier_sha256": task_next.get("frontier_sha256"),
        "condition": task_next.get("condition"),
        "controller": _required_string(
            controller_locator, "controller_locator"
        ),
    }
    actions = task_next.get("actions")
    if isinstance(actions, list) and len(actions) == 1:
        action = actions[0]
        if isinstance(action, Mapping):
            payload["next"] = {
                key: action[key]
                for key in ("action_id", "edge_id", "playbook")
                if key in action
            }
    size = protocol_size(payload)
    if size > HOOK_CHECKPOINT_BUDGET:
        raise AgentProtocolError(
            "HOOK_CHECKPOINT_BUDGET_EXCEEDED",
            "common hook checkpoint exceeds its UTF-8 byte budget",
            details={"size": size, "budget": HOOK_CHECKPOINT_BUDGET},
        )
    return payload


def build_mutation_receipt(
    *,
    task_id: str,
    revision: int,
    node_id: str,
    changed_sections: Iterable[str],
    action_id: str,
    summary: Mapping[str, object],
    next_locator: Mapping[str, object],
    required_fields: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload = {
        "contract": "dev-flow-mutation-receipt/v1",
        "task_id": _required_string(task_id, "task_id"),
        "revision": _required_nonnegative_int(revision, "revision"),
        "node_id": _required_string(node_id, "node_id"),
        "changed": sorted(set(changed_sections)),
        "action_id": _required_string(action_id, "action_id"),
        "summary": _canonical_protocol_value(dict(summary)),
        "next": _canonical_protocol_value(dict(next_locator)),
    }
    if required_fields:
        payload["required"] = _canonical_protocol_value(
            dict(required_fields)
        )
    common = dict(payload)
    common.pop("required", None)
    common_size = protocol_size(common)
    if common_size > MUTATION_RECEIPT_BUDGET:
        raise AgentProtocolError(
            "MUTATION_RECEIPT_BUDGET_EXCEEDED",
            "common mutation receipt exceeds its UTF-8 byte budget",
            details={
                "size": common_size,
                "budget": MUTATION_RECEIPT_BUDGET,
            },
        )
    return payload


def validate_agent_node_result_candidate(
    value: Mapping[str, object],
    *,
    expected_task_id: str | None = None,
    expected_input_sha256: str | None = None,
) -> dict[str, object]:
    """Validate a bounded, non-authoritative agent projection.

    Only orchestration_results.py owns ``dev-flow-node-result/v1``.  A
    controller must resolve and verify this candidate before promotion.
    """
    allowed = {
        "schema",
        "result_id",
        "task_id",
        "bundle_sha256",
        "node_instance_id",
        "repository_id",
        "attempt",
        "input_sha256",
        "status",
        "summary",
        "artifacts",
        "evidence",
        "changed_files",
        "blockers",
        "plan_drift",
        "runtime_handle",
        "usage",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AgentProtocolError(
            "NODE_RESULT_UNKNOWN_FIELD",
            "node result contains unsupported fields",
            details={"fields": unknown},
        )
    if value.get("schema") != AGENT_NODE_RESULT_CANDIDATE_SCHEMA:
        raise AgentProtocolError(
            "NODE_RESULT_UNSUPPORTED",
            "node result schema is unsupported",
            details={"schema": value.get("schema")},
        )
    task_id = _required_string(value.get("task_id"), "task_id")
    if expected_task_id is not None and task_id != expected_task_id:
        raise AgentProtocolError(
            "NODE_RESULT_TASK_MISMATCH",
            "node result belongs to another task",
        )
    input_sha = _required_string(
        value.get("input_sha256"), "input_sha256"
    )
    for field, digest in (
        ("bundle_sha256", value.get("bundle_sha256")),
        ("input_sha256", input_sha),
    ):
        digest = _required_string(digest, field)
        if not _SHA256_VALUE_RE.fullmatch(digest):
            raise AgentProtocolError(
                "NODE_RESULT_DIGEST_INVALID",
                f"{field} must be a lowercase SHA-256 value",
                details={"field": field},
            )
    if (
        expected_input_sha256 is not None
        and input_sha != expected_input_sha256
    ):
        raise AgentProtocolError(
            "NODE_RESULT_INPUT_MISMATCH",
            "node result input digest is stale or belongs to another attempt",
        )
    status = _required_string(value.get("status"), "status")
    if status not in _NODE_RESULT_STATES:
        raise AgentProtocolError(
            "NODE_RESULT_STATUS_INVALID",
            "node result status is unsupported",
            details={"status": status},
        )
    summary = _required_string(
        value.get("summary"),
        "summary",
        maximum_bytes=NODE_RESULT_SUMMARY_BUDGET,
    )
    result: dict[str, object] = {
        "schema": AGENT_NODE_RESULT_CANDIDATE_SCHEMA,
        "result_id": _required_string(
            value.get("result_id"), "result_id"
        ),
        "task_id": task_id,
        "bundle_sha256": value["bundle_sha256"],
        "node_instance_id": _required_string(
            value.get("node_instance_id"), "node_instance_id"
        ),
        "attempt": _required_nonnegative_int(
            value.get("attempt"), "attempt"
        ),
        "input_sha256": input_sha,
        "status": status,
        "summary": summary,
        "artifacts": [],
        "evidence": [],
        "changed_files": _canonical_protocol_value(
            value.get("changed_files", [])
        ),
        "blockers": _canonical_protocol_value(
            value.get("blockers", [])
        ),
        "plan_drift": _canonical_protocol_value(
            value.get("plan_drift", {"detected": False})
        ),
    }
    repository_id = value.get("repository_id")
    if repository_id is not None:
        result["repository_id"] = _required_string(
            repository_id, "repository_id"
        )
    for field in ("artifacts", "evidence"):
        references = value.get(field, [])
        if not isinstance(references, list):
            raise AgentProtocolError(
                "PROTOCOL_FIELD_INVALID",
                f"{field} must be an array",
                details={"field": field},
            )
        result[field] = [
            validate_artifact_reference(
                item, expected_task_id=task_id
            )
            for item in references
            if isinstance(item, Mapping)
        ]
        if len(result[field]) != len(references):
            raise AgentProtocolError(
                "PROTOCOL_FIELD_INVALID",
                f"{field} entries must be artifact references",
                details={"field": field},
            )
    for optional in ("runtime_handle", "usage"):
        if optional in value:
            result[optional] = _canonical_protocol_value(value[optional])
    size = protocol_size(result)
    if size > NODE_RESULT_BUDGET:
        raise AgentProtocolError(
            "NODE_RESULT_BUDGET_EXCEEDED",
            "manager-visible node result exceeds its UTF-8 byte budget",
            details={"size": size, "budget": NODE_RESULT_BUDGET},
        )
    return result
