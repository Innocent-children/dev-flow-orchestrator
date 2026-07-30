# Loaded by scripts/dev_flow.py after the workflow projection, manager
# channel, and orchestration services.  This fragment owns only the typed MCP
# to controller-service mapping.  It never writes task state or event logs.
from __future__ import annotations

import base64 as _mcs_base64
import hashlib as _mcs_hashlib
import hmac as _mcs_hmac
import json as _mcs_json
from typing import Callable as _McsCallable
from typing import Mapping as _McsMapping
from typing import Optional as _McsOptional


MCP_CONTROLLER_SERVICE_SCHEMA = "dev-flow-controller-mcp-service/v1"
MCP_CONTROLLER_REQUEST_SCHEMA = "dev-flow-controller-mcp-request/v1"
MCP_TASK_NEXT_UNCHANGED_SCHEMA = (
    "dev-flow-task-next-unchanged/v1"
)
MCP_TASK_NEXT_DELTA_SCHEMA = "dev-flow-task-next-delta/v1"
MCP_NODE_DESCRIPTION_REFERENCE_SCHEMA = (
    "dev-flow-node-description-reference/v1"
)
MCP_EVIDENCE_PROJECTION_SCHEMA = (
    "dev-flow-evidence-projection/v1"
)
MCP_ACTION_PREVIEW_RESULT_SCHEMA = (
    "dev-flow-mcp-action-preview-result/v1"
)
MCP_ACTION_APPLY_RESULT_SCHEMA = (
    "dev-flow-mcp-action-apply-result/v1"
)
MCP_WORKER_RESULT_ACCEPTANCE_SCHEMA = (
    "dev-flow-worker-result-acceptance/v1"
)
MCP_NODE_DESCRIPTION_INLINE_BYTES = 8 * 1024
MCP_EVIDENCE_INLINE_BYTES = 6 * 1024

_mcs_tool_names = frozenset(
    {
        "task-next",
        "node-description",
        "evidence-read",
        "action-preview",
        "action-apply",
        "worker-result",
    }
)
_mcs_sha256_characters = frozenset("0123456789abcdef")


class McpControllerServiceError(RuntimeError):
    """Stable package-owned MCP controller-service failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: _McsOptional[_McsMapping[str, object]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def _mcs_error(
    code: str,
    message: str,
    *,
    details: _McsOptional[_McsMapping[str, object]] = None,
) -> McpControllerServiceError:
    return McpControllerServiceError(
        code, message, details=details
    )


def _mcs_translate(exc: BaseException) -> McpControllerServiceError:
    if isinstance(exc, McpControllerServiceError):
        return exc
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    details = getattr(exc, "details", None)
    if isinstance(code, str) and isinstance(message, str):
        return _mcs_error(
            code,
            message,
            details=details if isinstance(details, _McsMapping) else None,
        )
    return _mcs_error(
        "MCP_CONTROLLER_SERVICE_FAILED",
        "the package controller service rejected the MCP request",
        details={"failure_type": type(exc).__name__},
    )


def _mcs_canonical_bytes(value: object) -> bytes:
    try:
        return _mcs_json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _mcs_error(
            "MCP_CONTROLLER_VALUE_INVALID",
            "controller service value is not canonical JSON",
        ) from exc


def _mcs_sha256(value: object) -> str:
    return _mcs_hashlib.sha256(
        _mcs_canonical_bytes(value)
    ).hexdigest()


def _mcs_is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value).issubset(_mcs_sha256_characters)
    )


def _mcs_require_mapping(
    value: object, field: str
) -> dict[str, object]:
    if not isinstance(value, _McsMapping):
        raise _mcs_error(
            "MCP_CONTROLLER_REQUEST_INVALID",
            "controller MCP request field must be an object",
            details={"field": field},
        )
    if any(not isinstance(key, str) for key in value):
        raise _mcs_error(
            "MCP_CONTROLLER_REQUEST_INVALID",
            "controller MCP request keys must be strings",
            details={"field": field},
        )
    return dict(value)


def _mcs_require_exact_fields(
    value: _McsMapping[str, object],
    fields: frozenset[str],
    *,
    required: frozenset[str],
    field: str,
) -> None:
    unknown = sorted(set(value) - set(fields))
    missing = sorted(set(required) - set(value))
    if unknown or missing:
        raise _mcs_error(
            "MCP_CONTROLLER_REQUEST_INVALID",
            "controller MCP request has an invalid field set",
            details={
                "field": field,
                "unknown": unknown,
                "missing": missing,
            },
        )


def _mcs_require_task_state(
    task_id: str, data_dir: object
) -> dict[str, object]:
    try:
        state = load_state(task_id, data_dir)
    except Exception as exc:
        raise _mcs_translate(exc) from exc
    if (
        not isinstance(state, dict)
        or state.get("task_id") != task_id
        or isinstance(state.get("revision"), bool)
        or not isinstance(state.get("revision"), int)
        or int(state["revision"]) < 0
    ):
        raise _mcs_error(
            "MCP_TASK_STATE_INVALID",
            "loaded task state does not match the requested identity",
            details={"task_id": task_id},
        )
    return state


def _mcs_event_revision_delta(
    task_id: str,
    data_dir: object,
    known_revision: int,
    current_revision: int,
    *,
    task_directory: _McsCallable[..., object],
    event_reader: _McsCallable[..., object],
) -> dict[str, object]:
    """Return a bounded integrity summary of committed revisions after a read."""

    if not callable(task_directory) or not callable(event_reader):
        raise _mcs_error(
            "MCP_REVISION_DELTA_UNAVAILABLE",
            "the explicit package event-store capability is unavailable",
        )
    try:
        events = event_reader(task_directory(task_id, data_dir))
    except Exception as exc:
        raise _mcs_translate(exc) from exc
    selected: list[dict[str, object]] = []
    revisions: set[int] = set()
    for event in events:
        if not isinstance(event, _McsMapping):
            raise _mcs_error(
                "MCP_REVISION_DELTA_INVALID",
                "the task event store returned a non-object record",
            )
        revision = event.get("revision")
        previous_revision = event.get("previous_revision")
        event_type = event.get("type")
        event_id = event.get("event_id")
        if (
            event.get("task_id") != task_id
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or isinstance(previous_revision, bool)
            or not isinstance(previous_revision, int)
            or previous_revision != revision - 1
            or not isinstance(event_type, str)
            or not event_type
            or len(event_type.encode("utf-8")) > 128
            or not isinstance(event_id, str)
            or not event_id
            or len(event_id.encode("utf-8")) > 256
        ):
            raise _mcs_error(
                "MCP_REVISION_DELTA_INVALID",
                "the task event store contains an unbound revision record",
            )
        if known_revision < revision <= current_revision:
            revisions.add(revision)
            selected.append(dict(event))
    selected.sort(
        key=lambda item: (
            int(item["revision"]),
            str(item["type"]).encode("utf-8"),
            str(item["event_id"]).encode("utf-8"),
        )
    )
    ordered_revisions = sorted(revisions)
    expected_count = current_revision - known_revision
    complete = (
        expected_count > 0
        and len(ordered_revisions) == expected_count
        and ordered_revisions[0] == known_revision + 1
        and ordered_revisions[-1] == current_revision
        and all(
            right == left + 1
            for left, right in zip(
                ordered_revisions, ordered_revisions[1:]
            )
        )
    )
    return {
        "contract": MCP_TASK_NEXT_DELTA_SCHEMA,
        "from_revision": known_revision,
        "to_revision": current_revision,
        "revision_count": len(ordered_revisions),
        "delta_sha256": _mcs_sha256(selected),
        "reset_required": not complete,
    }


def _mcs_unavailable_revision_delta(
    _task_id: str,
    _data_dir: object,
    _known_revision: int,
    _current_revision: int,
) -> dict[str, object]:
    raise _mcs_error(
        "MCP_REVISION_DELTA_UNAVAILABLE",
        "the package event-store service was not composed",
    )


def _mcs_runtime_revision_delta_reader(
) -> _McsOptional[_McsCallable[..., object]]:
    runtime_factory = globals().get("workflow_runtime_services")
    if not callable(runtime_factory):
        return None
    try:
        runtime = runtime_factory()
    except Exception as exc:
        raise _mcs_translate(exc) from exc
    store = getattr(runtime, "store", None)
    task_directory = getattr(store, "task_directory", None)
    event_reader = getattr(store, "read_bounded_events", None)
    if not callable(task_directory) or not callable(event_reader):
        raise _mcs_error(
            "MCP_REVISION_DELTA_UNAVAILABLE",
            "runtime services lack the required event-store capabilities",
        )

    def read_delta(
        task_id: str,
        data_dir: object,
        known_revision: int,
        current_revision: int,
    ) -> dict[str, object]:
        return _mcs_event_revision_delta(
            task_id,
            data_dir,
            known_revision,
            current_revision,
            task_directory=task_directory,
            event_reader=event_reader,
        )

    return read_delta


def _mcs_artifact_reference(
    *,
    task_id: str,
    artifact_id: str,
    source: _McsMapping[str, object],
    media_type: str,
) -> dict[str, object]:
    semantic_sha256 = source.get("semantic_sha256")
    sha256 = source.get("sha256")
    size = source.get("size")
    kind = source.get("kind")
    locator = source.get("locator")
    if (
        not _mcs_is_sha256(semantic_sha256)
        or not _mcs_is_sha256(sha256)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or not isinstance(kind, str)
        or not kind
        or not isinstance(locator, str)
        or not locator
    ):
        raise _mcs_error(
            "MCP_EVIDENCE_REFERENCE_INVALID",
            "task evidence has invalid persisted integrity facts",
            details={"evidence_id": artifact_id},
        )
    return {
        "schema": ARTIFACT_REFERENCE_SCHEMA,
        "artifact_id": artifact_id,
        "task_id": task_id,
        "semantic_sha256": semantic_sha256,
        "sha256": sha256,
        "size": size,
        "media_type": media_type,
        "kind": kind,
        "locator": locator,
    }


def _mcs_read_orchestration_artifact(
    state: _McsMapping[str, object],
    *,
    task_id: str,
    evidence_id: str,
    data_dir: object,
) -> tuple[bytes, dict[str, object]]:
    try:
        orchestration = _osc_state_copy(state)
    except Exception as exc:
        raise _mcs_translate(exc) from exc
    artifacts = orchestration.get("artifacts")
    reference = (
        artifacts.get(evidence_id)
        if isinstance(artifacts, _McsMapping)
        else None
    )
    if not isinstance(reference, _McsMapping):
        raise _mcs_error(
            "MCP_EVIDENCE_UNKNOWN",
            "task-scoped evidence is absent",
            details={"evidence_id": evidence_id},
        )
    sha256 = reference.get("sha256")
    locator = reference.get("locator")
    try:
        expected_locator = _osc_artifact_locator(str(sha256))
    except Exception as exc:
        raise _mcs_translate(exc) from exc
    if locator != expected_locator:
        raise _mcs_error(
            "MCP_EVIDENCE_REFERENCE_INVALID",
            "task evidence locator is not controller-owned",
            details={"evidence_id": evidence_id},
        )
    task_dir = _task_dir(task_id, data_dir).resolve()
    path = (task_dir / expected_locator).resolve()
    try:
        path.relative_to(task_dir)
    except ValueError as exc:
        raise _mcs_error(
            "MCP_EVIDENCE_PATH_ESCAPE",
            "task evidence resolves outside its owning task",
            details={"evidence_id": evidence_id},
        ) from exc
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise _mcs_error(
            "MCP_EVIDENCE_UNAVAILABLE",
            "task evidence cannot be read",
            details={"evidence_id": evidence_id},
        ) from exc
    observed_sha256 = _mcs_hashlib.sha256(content).hexdigest()
    if (
        not _mcs_hmac.compare_digest(
            observed_sha256, str(reference.get("sha256"))
        )
        or len(content) != reference.get("size")
    ):
        raise _mcs_error(
            "MCP_EVIDENCE_INTEGRITY_MISMATCH",
            "task evidence differs from persisted integrity facts",
            details={"evidence_id": evidence_id},
        )
    return content, _mcs_artifact_reference(
        task_id=task_id,
        artifact_id=evidence_id,
        source=reference,
        media_type="application/json",
    )


def _mcs_read_protocol_artifact(
    *,
    task_id: str,
    evidence_id: str,
    data_dir: object,
) -> tuple[bytes, dict[str, object]]:
    prefix = "protocol-"
    digest = (
        evidence_id[len(prefix) :]
        if evidence_id.startswith(prefix)
        else ""
    )
    if not _mcs_is_sha256(digest):
        raise _mcs_error(
            "MCP_EVIDENCE_UNKNOWN",
            "task-scoped evidence is absent",
            details={"evidence_id": evidence_id},
        )
    locator = f"artifacts/protocol/{digest}.json"
    try:
        content, reference = resolve_workflow_protocol_artifact(
            task_id, locator, data_dir=data_dir
        )
    except Exception as exc:
        raise _mcs_translate(exc) from exc
    if reference.get("artifact_id") != evidence_id:
        raise _mcs_error(
            "MCP_EVIDENCE_REFERENCE_INVALID",
            "protocol evidence identity does not match its locator",
            details={"evidence_id": evidence_id},
        )
    return content, dict(reference)


def _mcs_read_evidence(
    state: _McsMapping[str, object],
    *,
    task_id: str,
    evidence_id: str,
    expected_sha256: _McsOptional[str],
    data_dir: object,
) -> dict[str, object]:
    if evidence_id.startswith("protocol-"):
        content, reference = _mcs_read_protocol_artifact(
            task_id=task_id,
            evidence_id=evidence_id,
            data_dir=data_dir,
        )
    else:
        content, reference = _mcs_read_orchestration_artifact(
            state,
            task_id=task_id,
            evidence_id=evidence_id,
            data_dir=data_dir,
        )
    observed = _mcs_hashlib.sha256(content).hexdigest()
    if (
        expected_sha256 is not None
        and not _mcs_hmac.compare_digest(expected_sha256, observed)
    ):
        raise _mcs_error(
            "MCP_EVIDENCE_EXPECTED_DIGEST_MISMATCH",
            "task evidence does not match the caller's expected digest",
            details={
                "evidence_id": evidence_id,
                "expected_sha256": expected_sha256,
                "actual_sha256": observed,
            },
        )
    inline = len(content) <= MCP_EVIDENCE_INLINE_BYTES
    return {
        "contract": MCP_EVIDENCE_PROJECTION_SCHEMA,
        "task_id": task_id,
        "revision": int(state["revision"]),
        "evidence_id": evidence_id,
        "reference": reference,
        "inline": inline,
        "content_encoding": "base64" if inline else "artifact-reference",
        "content_base64": (
            _mcs_base64.b64encode(content).decode("ascii")
            if inline
            else None
        ),
    }


def _mcs_manager_secret_resolver(
    channel: object,
) -> _McsCallable[[str], bytearray]:
    def resolve(capability_id: str) -> bytearray:
        if channel is None:
            raise _mcs_error(
                "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
                "the local manager secret channel is unavailable",
            )
        resolver = getattr(channel, "resolve_secret", None)
        if not callable(resolver):
            raise _mcs_error(
                "MANAGER_SECRET_CHANNEL_INVALID",
                "the local manager secret channel has no resolver",
            )
        secret = resolver(capability_id)
        if not isinstance(secret, bytearray):
            raise _mcs_error(
                "MANAGER_CAPABILITY_PROOF_INVALID",
                "the manager secret channel must return mutable proof bytes",
            )
        # The controller becomes the sole consumer and must clear this exact
        # mutable buffer in a finally block after authorization.
        return secret

    return resolve


def _mcs_principal_mapping(
    value: object,
    *,
    request: _McsMapping[str, object],
) -> dict[str, object]:
    source = value
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        source = as_dict()
    if not isinstance(source, _McsMapping):
        raise _mcs_error(
            "MANAGER_PRINCIPAL_UNAVAILABLE",
            "manager channel returned no authenticated principal",
        )
    principal = dict(source)
    expected = {
        "schema",
        "role",
        "session_id",
        "os_user_identity_sha256",
        "host_identity_sha256",
    }
    if (
        set(principal) != expected
        or principal.get("schema") != "dev-flow-agent-principal/v1"
        or principal.get("role") != "manager"
        or principal.get("session_id")
        != request.get("manager_session_id")
        or not _mcs_is_sha256(
            principal.get("os_user_identity_sha256")
        )
        or not _mcs_is_sha256(
            principal.get("host_identity_sha256")
        )
    ):
        raise _mcs_error(
            "MANAGER_PRINCIPAL_INVALID",
            "manager channel principal is outside the request scope",
        )
    return principal


def _mcs_manager_principal_resolver(
    channel: object,
) -> _McsCallable[[_McsMapping[str, object]], object]:
    def resolve(request: _McsMapping[str, object]) -> object:
        if channel is None:
            raise _mcs_error(
                "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
                "the local manager secret channel is unavailable",
            )
        principal_for = getattr(channel, "principal_for", None)
        if not callable(principal_for):
            raise _mcs_error(
                "MANAGER_SECRET_CHANNEL_INVALID",
                "the local manager channel has no principal resolver",
            )
        return _mcs_principal_mapping(
            principal_for(request), request=request
        )

    return resolve


def _mcs_receipt_mapping(value: object) -> dict[str, object]:
    if isinstance(value, _McsMapping):
        return dict(value)
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        result = as_dict()
        if isinstance(result, _McsMapping):
            return dict(result)
    raise _mcs_error(
        "MCP_CONTROLLER_RECEIPT_INVALID",
        "controller action returned an invalid receipt",
    )


class McpControllerService:
    """Package-owned dispatcher shared by MCP and controller services."""

    __slots__ = (
        "_data_dir",
        "_action_preview",
        "_action_apply",
        "_revision_delta_reader",
        "_principal_resolver",
        "_manager_channel",
        "_orchestration_service",
    )

    def __init__(
        self,
        *,
        data_dir: object = None,
        action_preview: _McsOptional[_McsCallable[..., object]] = None,
        action_apply: _McsOptional[_McsCallable[..., object]] = None,
        revision_delta_reader: _McsOptional[
            _McsCallable[..., object]
        ] = None,
        principal_resolver: _McsOptional[
            _McsCallable[[_McsMapping[str, object]], object]
        ] = None,
        manager_channel: object = None,
        orchestration_service: object = None,
    ) -> None:
        self._data_dir = data_dir
        self._action_preview = action_preview
        self._action_apply = action_apply
        self._revision_delta_reader = (
            revision_delta_reader or _mcs_unavailable_revision_delta
        )
        self._principal_resolver = (
            principal_resolver
            or _mcs_manager_principal_resolver(None)
        )
        self._manager_channel = manager_channel
        self._orchestration_service = orchestration_service

    def _task_next(
        self, arguments: _McsMapping[str, object]
    ) -> dict[str, object]:
        task_id = str(arguments["task_id"])
        state = _mcs_require_task_state(task_id, self._data_dir)
        revision = int(state["revision"])
        known_revision = arguments.get("known_revision")
        if (
            isinstance(known_revision, int)
            and not isinstance(known_revision, bool)
        ):
            if known_revision > revision:
                raise _mcs_error(
                    "MCP_KNOWN_REVISION_AHEAD",
                    "known revision is newer than controller state",
                    details={
                        "known_revision": known_revision,
                        "revision": revision,
                    },
                )
            if known_revision == revision:
                return {
                    "contract": MCP_TASK_NEXT_UNCHANGED_SCHEMA,
                    "task_id": task_id,
                    "revision": revision,
                    "known_revision": known_revision,
                    "unchanged": True,
                }
        delta: _McsOptional[dict[str, object]] = None
        if (
            isinstance(known_revision, int)
            and not isinstance(known_revision, bool)
            and known_revision < revision
        ):
            try:
                delta = self._revision_delta_reader(
                    task_id,
                    self._data_dir,
                    known_revision,
                    revision,
                )
            except Exception as exc:
                raise _mcs_translate(exc) from exc
            if not isinstance(delta, _McsMapping):
                raise _mcs_error(
                    "MCP_REVISION_DELTA_INVALID",
                    "the package revision-delta reader returned an invalid value",
                )
            delta = dict(delta)
        try:
            projection = build_workflow_task_next(
                state,
                data_dir=self._data_dir,
                revision_delta=delta,
            )
        except Exception as exc:
            raise _mcs_translate(exc) from exc
        return projection

    def _node_description(
        self, arguments: _McsMapping[str, object]
    ) -> dict[str, object]:
        task_id = str(arguments["task_id"])
        node_id = str(arguments["node_id"])
        state = _mcs_require_task_state(task_id, self._data_dir)
        node_instance_id = arguments.get("node_instance_id")
        if node_instance_id is not None:
            instances = state.get("node_instances")
            match = next(
                (
                    item
                    for item in instances
                    if isinstance(item, _McsMapping)
                    and item.get("node_instance_id")
                    == node_instance_id
                ),
                None,
            ) if isinstance(instances, (list, tuple)) else None
            if not isinstance(match, _McsMapping):
                raise _mcs_error(
                    "MCP_NODE_INSTANCE_UNKNOWN",
                    "node instance is absent from the requested task",
                    details={"node_instance_id": node_instance_id},
                )
            if match.get("node_id") != node_id:
                raise _mcs_error(
                    "MCP_NODE_INSTANCE_MISMATCH",
                    "node instance belongs to another workflow node",
                    details={
                        "node_instance_id": node_instance_id,
                        "expected_node_id": match.get("node_id"),
                        "actual_node_id": node_id,
                    },
                )
        try:
            description = workflow_node_description(state, node_id)
        except Exception as exc:
            raise _mcs_translate(exc) from exc
        content = _mcs_canonical_bytes(description)
        if len(content) <= MCP_NODE_DESCRIPTION_INLINE_BYTES:
            return description
        try:
            reference = _workflow_projection_artifact_writer(
                self._data_dir
            )(task_id, "node-description", content)
        except Exception as exc:
            raise _mcs_translate(exc) from exc
        return {
            "contract": MCP_NODE_DESCRIPTION_REFERENCE_SCHEMA,
            "task_id": task_id,
            "revision": int(state["revision"]),
            "node_id": node_id,
            "artifact": dict(reference),
        }

    def _evidence_read(
        self, arguments: _McsMapping[str, object]
    ) -> dict[str, object]:
        task_id = str(arguments["task_id"])
        state = _mcs_require_task_state(task_id, self._data_dir)
        expected = arguments.get("expected_sha256")
        return _mcs_read_evidence(
            state,
            task_id=task_id,
            evidence_id=str(arguments["evidence_id"]),
            expected_sha256=(
                str(expected) if isinstance(expected, str) else None
            ),
            data_dir=self._data_dir,
        )

    def _preview_action(
        self, arguments: _McsMapping[str, object]
    ) -> dict[str, object]:
        if not callable(self._action_preview):
            raise _mcs_error(
                "MCP_ACTION_SERVICE_UNAVAILABLE",
                "the package action preview service is unavailable",
            )
        input_value = arguments.get("input")
        if not isinstance(input_value, _McsMapping):
            input_value = {}
        try:
            value = self._action_preview(
                str(arguments["task_id"]),
                expected_revision=int(arguments["expected_revision"]),
                action_id=str(arguments["action_id"]),
                input_value=dict(input_value),
                data_dir=self._data_dir,
            )
        except Exception as exc:
            raise _mcs_translate(exc) from exc
        preview = _mcs_receipt_mapping(value)
        required = {
            "contract",
            "task_id",
            "revision",
            "action_id",
            "input_sha256",
            "preview_intent",
            "applicable",
            "blockers",
        }
        allowed = required | {"fallback"}
        if set(preview) - allowed or required - set(preview):
            raise _mcs_error(
                "MCP_ACTION_PREVIEW_INVALID",
                "package action preview returned an invalid field set",
            )
        expected_input_sha256 = _mcs_sha256(dict(input_value))
        if (
            preview.get("contract")
            != MCP_ACTION_PREVIEW_RESULT_SCHEMA
            or preview.get("task_id") != arguments["task_id"]
            or preview.get("revision")
            != arguments["expected_revision"]
            or preview.get("action_id") != arguments["action_id"]
            or preview.get("input_sha256") != expected_input_sha256
            or not isinstance(preview.get("preview_intent"), str)
            or not isinstance(preview.get("applicable"), bool)
            or not isinstance(preview.get("blockers"), list)
            or any(
                not isinstance(item, str)
                for item in preview.get("blockers", [])
            )
        ):
            raise _mcs_error(
                "MCP_ACTION_PREVIEW_INVALID",
                "package action preview is not bound to the MCP request",
            )
        fallback = preview.get("fallback")
        if fallback is not None:
            if (
                not isinstance(fallback, _McsMapping)
                or set(fallback)
                != {"schema", "controller", "data_dir", "arguments"}
                or fallback.get("schema")
                != "dev-flow-cli-fallback/v1"
                or not isinstance(fallback.get("controller"), str)
                or (
                    fallback.get("data_dir") is not None
                    and not isinstance(
                        fallback.get("data_dir"), str
                    )
                )
                or not isinstance(fallback.get("arguments"), list)
                or not fallback.get("arguments")
                or any(
                    not isinstance(item, str)
                    for item in fallback.get("arguments", [])
                )
                or preview.get("applicable") is not False
            ):
                raise _mcs_error(
                    "MCP_ACTION_PREVIEW_INVALID",
                    "package action preview returned an invalid CLI fallback",
                )
        return preview

    def _apply_action(
        self, arguments: _McsMapping[str, object]
    ) -> dict[str, object]:
        if not callable(self._action_apply):
            raise _mcs_error(
                "MCP_ACTION_SERVICE_UNAVAILABLE",
                "the package action apply service is unavailable",
            )
        request = _mcs_require_mapping(
            arguments["request_identity"], "request_identity"
        )
        principal = _mcs_principal_mapping(
            self._principal_resolver(request), request=request
        )
        input_value = arguments.get("input")
        if not isinstance(input_value, _McsMapping):
            input_value = {}
        try:
            value = self._action_apply(
                str(arguments["task_id"]),
                expected_revision=int(arguments["expected_revision"]),
                action_id=str(arguments["action_id"]),
                input_value=dict(input_value),
                preview_intent=str(arguments["preview_intent"]),
                request=request,
                principal=principal,
                manager_channel=self._manager_channel,
                data_dir=self._data_dir,
            )
        except Exception as exc:
            raise _mcs_translate(exc) from exc
        receipt = _mcs_receipt_mapping(value)
        result = {
            "contract": MCP_ACTION_APPLY_RESULT_SCHEMA,
            "task_id": str(arguments["task_id"]),
            "action_id": str(arguments["action_id"]),
            "preview_intent": str(arguments["preview_intent"]),
            "revision": receipt.get("revision"),
            "event_id": receipt.get("event_id"),
            "event_type": receipt.get("event_type"),
            "authorization_id": receipt.get("authorization_id"),
        }
        if (
            isinstance(result["revision"], bool)
            or not isinstance(result["revision"], int)
            or int(result["revision"])
            != int(arguments["expected_revision"]) + 1
            or not isinstance(result["event_id"], str)
            or not result["event_id"]
            or not isinstance(result["event_type"], str)
            or not result["event_type"]
            or not isinstance(result["authorization_id"], str)
            or not result["authorization_id"]
        ):
            raise _mcs_error(
                "MCP_CONTROLLER_RECEIPT_INVALID",
                "package action apply returned an invalid commit receipt",
            )
        return result

    def _worker_result(
        self, arguments: _McsMapping[str, object]
    ) -> dict[str, object]:
        service = self._orchestration_service
        accept_result = getattr(service, "accept_result", None)
        if not callable(accept_result):
            raise _mcs_error(
                "MCP_WORKER_RESULT_SERVICE_UNAVAILABLE",
                "the orchestration result service is unavailable",
            )
        request = _mcs_require_mapping(
            arguments["request_identity"], "request_identity"
        )
        principal = _mcs_principal_mapping(
            self._principal_resolver(request), request=request
        )
        try:
            receipt_value = accept_result(
                str(arguments["task_id"]),
                arguments["result"],
                request=request,
                principal=principal,
                data_dir=self._data_dir,
            )
        except Exception as exc:
            raise _mcs_translate(exc) from exc
        receipt = _mcs_receipt_mapping(receipt_value)
        result_id = arguments["result"].get("result_id")
        result = {
            "contract": MCP_WORKER_RESULT_ACCEPTANCE_SCHEMA,
            "task_id": str(arguments["task_id"]),
            "result_id": result_id,
            "revision": receipt.get("revision"),
            "event_id": receipt.get("event_id"),
            "event_type": receipt.get("event_type"),
            "authorization_id": receipt.get("authorization_id"),
        }
        if (
            not isinstance(result_id, str)
            or isinstance(result["revision"], bool)
            or not isinstance(result["revision"], int)
            or int(result["revision"])
            != int(arguments["expected_revision"]) + 1
            or not isinstance(result["event_id"], str)
            or not result["event_id"]
            or not isinstance(result["event_type"], str)
            or not result["event_type"]
            or not isinstance(result["authorization_id"], str)
            or not result["authorization_id"]
        ):
            raise _mcs_error(
                "MCP_CONTROLLER_RECEIPT_INVALID",
                "orchestration service returned an invalid result receipt",
            )
        return result

    def dispatch_mcp_tool(
        self, request_value: _McsMapping[str, object]
    ) -> dict[str, object]:
        try:
            request = _mcs_require_mapping(request_value, "request")
            _mcs_require_exact_fields(
                request,
                frozenset(
                    {
                        "schema",
                        "tool",
                        "arguments",
                        "request_identity",
                    }
                ),
                required=frozenset(
                    {
                        "schema",
                        "tool",
                        "arguments",
                        "request_identity",
                    }
                ),
                field="request",
            )
            if request["schema"] != MCP_CONTROLLER_REQUEST_SCHEMA:
                raise _mcs_error(
                    "MCP_CONTROLLER_REQUEST_UNSUPPORTED",
                    "controller MCP request schema is unsupported",
                )
            tool = request["tool"]
            if not isinstance(tool, str) or tool not in _mcs_tool_names:
                raise _mcs_error(
                    "MCP_CONTROLLER_TOOL_UNSUPPORTED",
                    "controller MCP tool is unsupported",
                )
            arguments = _mcs_require_mapping(
                request["arguments"], "arguments"
            )
            if (
                tool in {"action-apply", "worker-result"}
                and request["request_identity"]
                != arguments.get("request_identity")
            ):
                raise _mcs_error(
                    "MCP_REQUEST_IDENTITY_MISMATCH",
                    "controller request identity is not the tool identity",
                )
            if (
                tool not in {"action-apply", "worker-result"}
                and request["request_identity"] is not None
            ):
                raise _mcs_error(
                    "MCP_REQUEST_IDENTITY_FORBIDDEN",
                    "read-only MCP calls cannot carry mutation identity",
                )
            dispatch = {
                "task-next": self._task_next,
                "node-description": self._node_description,
                "evidence-read": self._evidence_read,
                "action-preview": self._preview_action,
                "action-apply": self._apply_action,
                "worker-result": self._worker_result,
            }
            return dispatch[tool](arguments)
        except McpControllerServiceError:
            raise
        except Exception as exc:
            raise _mcs_translate(exc) from exc


def create_mcp_controller_service(
    data_dir: object = None,
    *,
    action_preview: _McsOptional[_McsCallable[..., object]] = None,
    action_apply: _McsOptional[_McsCallable[..., object]] = None,
    revision_delta_reader: _McsOptional[
        _McsCallable[..., object]
    ] = None,
    manager_channel_factory: _McsOptional[
        _McsCallable[..., object]
    ] = None,
    principal_resolver: _McsOptional[
        _McsCallable[[_McsMapping[str, object]], object]
    ] = None,
    orchestration_service: object = None,
) -> McpControllerService:
    """Compose only package-owned controller services.

    Optional parameters are explicit test/integration seams.  The production
    path resolves only functions already loaded from this signed package
    namespace; target repositories cannot inject executable handlers.
    """

    preview = action_preview
    if preview is None:
        candidate = globals().get("controller_action_preview")
        preview = candidate if callable(candidate) else None
    apply = action_apply
    if apply is None:
        candidate = globals().get("controller_action_apply")
        apply = candidate if callable(candidate) else None
    delta_reader = revision_delta_reader
    if delta_reader is None:
        delta_reader = _mcs_runtime_revision_delta_reader()
    channel_factory = manager_channel_factory
    if channel_factory is None:
        candidate = globals().get(
            "manager_secret_channel_from_environment"
        )
        channel_factory = candidate if callable(candidate) else None
    channel = None
    if channel_factory is not None:
        try:
            channel = channel_factory()
        except Exception:
            # Reads remain available. Every mutation fails closed at the
            # package-owned authority boundary.
            channel = None
    secret_resolver = _mcs_manager_secret_resolver(channel)
    resolved_principal = principal_resolver
    if resolved_principal is None:
        resolved_principal = _mcs_manager_principal_resolver(channel)
    service = orchestration_service
    if service is None:
        factory = globals().get("orchestration_controller_service")
        if callable(factory):
            try:
                service = factory(
                    secret_resolver=secret_resolver,
                    clock_id=str(
                        globals().get(
                            "MANAGER_CAPABILITY_CLOCK_ID",
                            "process-monotonic",
                        )
                    ),
                )
            except Exception as exc:
                raise _mcs_translate(exc) from exc
    return McpControllerService(
        data_dir=data_dir,
        action_preview=preview,
        action_apply=apply,
        revision_delta_reader=delta_reader,
        principal_resolver=resolved_principal,
        manager_channel=channel,
        orchestration_service=service,
    )
