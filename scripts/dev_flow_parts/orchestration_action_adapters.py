# Loaded by scripts/dev_flow.py after the transition/action contracts.
# Responsibility: bind repository-orchestration mutations to one immutable
# catalog action and produce a typed ActionOutcome without persistence or
# dispatch. Keep this standard-library only.
from __future__ import annotations

import threading as _orchestration_action_adapter_threading
from dataclasses import dataclass
from pathlib import Path as _OrchestrationActionAdapterPath
from types import MappingProxyType
from typing import Mapping


_orchestration_action_adapter_delta_fields = frozenset(
    {"operations", "remove", "set"}
)
_orchestration_action_adapter_metadata_fields = frozenset(
    {
        "action_nodes",
        "execution_profile",
        "join",
        "legacy_aliases",
        "map",
        "operation_ids",
        "operation_matrix",
        "schema",
    }
)
_orchestration_action_adapter_matrix_fields = frozenset(
    {
        "action_id",
        "effect_ids",
        "event_id",
        "operation_id",
        "validator_id",
        "write_set_id",
    }
)
_orchestration_action_adapter_alias_fields = frozenset(
    {"alias_id", "operation_ids"}
)
_orchestration_action_adapter_workflow_ref_fields = frozenset(
    {"bundle_sha256", "graph_sha256", "id", "schema", "version"}
)
_orchestration_action_adapter_sha256_length = 64
_orchestration_action_adapter_delta_domain = (
    b"dev-flow-orchestration-action-delta-v1\0"
)
_orchestration_action_adapter_binding_domain = (
    b"dev-flow-orchestration-action-binding-v1\0"
)
_orchestration_action_adapter_candidate_domain = (
    b"dev-flow-orchestration-action-candidate-v1\0"
)
_orchestration_action_adapter_intent_domain = (
    b"dev-flow-orchestration-action-intent-v1\0"
)
_orchestration_action_adapter_validator_receipt_domain = (
    b"dev-flow-orchestration-action-validator-receipt-v1\0"
)
_orchestration_action_adapter_evidence_contract = (
    "dev-flow-orchestration-action-binding/v1"
)
_orchestration_action_adapter_semantic_validation_fields = frozenset(
    {
        "candidate_state_sha256",
        "changed_pointers",
        "evidence",
        "event_id",
        "operation_id",
        "receipt_sha256",
        "validator_id",
    }
)
_orchestration_action_adapter_manager_selection = MappingProxyType(
    {
        "manager.capability.authorize/v1": (
            "manager-authorize",
            "operator",
            "manager_capability_authorized",
        ),
        "manager.capability.revoke/v1": (
            "manager-revoke",
            "operator",
            "manager_capability_revoked",
        ),
    }
)


class OrchestrationActionAdapterError(ValueError):
    """Stable fail-closed error from the pure orchestration adapter."""

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


def _orchestration_action_adapter_error(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> OrchestrationActionAdapterError:
    return OrchestrationActionAdapterError(
        code, message, details=details
    )


def _orchestration_action_adapter_freeze_shape(
    value: object,
    path: str = "$",
) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_JSON_INVALID",
                    "orchestration action object keys must be strings",
                    details={"path": path},
                )
            result[key] = _orchestration_action_adapter_freeze_shape(
                item, f"{path}/{key}"
            )
        return MappingProxyType(result)
    if isinstance(value, (tuple, list)):
        return tuple(
            _orchestration_action_adapter_freeze_shape(
                item, f"{path}/{index}"
            )
            for index, item in enumerate(value)
        )
    raise _orchestration_action_adapter_error(
        "ORCHESTRATION_ACTION_JSON_INVALID",
        "orchestration action values must be canonical JSON",
        details={"path": path, "type": type(value).__name__},
    )


def _orchestration_action_adapter_freeze(
    value: object,
    path: str = "$",
) -> object:
    frozen = _orchestration_action_adapter_freeze_shape(value, path)
    serializer = globals().get("semantic_json_bytes")
    if not callable(serializer):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_CANONICALIZER_UNAVAILABLE",
            "strict semantic JSON canonicalization is unavailable",
        )
    try:
        serializer(_orchestration_action_adapter_thaw(frozen))
    except Exception as exc:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_JSON_INVALID",
            "orchestration action values require strict semantic JSON",
            details={
                "path": path,
                "cause_code": getattr(exc, "code", type(exc).__name__),
                "cause_details": getattr(exc, "details", {}),
            },
        ) from exc
    return frozen


def _orchestration_action_adapter_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _orchestration_action_adapter_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [
            _orchestration_action_adapter_thaw(item) for item in value
        ]
    return value


def _orchestration_action_adapter_digest(
    value: object,
    *,
    domain: bytes,
) -> str:
    digester = globals().get("semantic_sha256")
    if not callable(digester):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_CANONICALIZER_UNAVAILABLE",
            "strict semantic JSON digesting is unavailable",
        )
    try:
        return str(
            digester(
                domain,
                _orchestration_action_adapter_thaw(value),
            )
        )
    except Exception as exc:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_JSON_INVALID",
            "orchestration action value cannot be semantically digested",
            details={
                "cause_code": getattr(exc, "code", type(exc).__name__),
                "cause_details": getattr(exc, "details", {}),
            },
        ) from exc


def _orchestration_action_adapter_string(
    value: object,
    *,
    field: str,
) -> str:
    if not isinstance(value, str) or not value:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_REQUEST_INVALID",
            "orchestration action identity fields require non-empty strings",
            details={"field": field},
        )
    return value


def _orchestration_action_adapter_digest_string(
    value: object,
    *,
    field: str,
) -> str:
    digest = _orchestration_action_adapter_string(value, field=field)
    if (
        len(digest) != _orchestration_action_adapter_sha256_length
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_REQUEST_INVALID",
            "workflow bundle bindings require lowercase SHA-256",
            details={"field": field},
        )
    return digest


def _orchestration_action_adapter_pointer(
    value: object,
    *,
    field: str,
) -> str:
    pointer = _orchestration_action_adapter_string(value, field=field)
    if not pointer.startswith("/") or pointer == "/":
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_DELTA_INVALID",
            "orchestration action writes require non-root JSON Pointers",
            details={"field": field, "pointer": pointer},
        )
    index = 0
    while index < len(pointer):
        if pointer[index] != "~":
            index += 1
            continue
        if index + 1 >= len(pointer) or pointer[index + 1] not in "01":
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                "orchestration action JSON Pointer escaping is invalid",
                details={"field": field, "pointer": pointer},
            )
        index += 2
    return pointer


def _orchestration_action_adapter_within(
    pointer: str,
    root: str,
) -> bool:
    return pointer == root or pointer.startswith(root + "/")


def _orchestration_action_adapter_paths_overlap(
    left: str,
    right: str,
) -> bool:
    return (
        _orchestration_action_adapter_within(left, right)
        or _orchestration_action_adapter_within(right, left)
    )


def _orchestration_action_adapter_normalize_delta(
    value: object,
    *,
    allowed_roots: tuple[str, ...],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != (
        _orchestration_action_adapter_delta_fields
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_DELTA_INVALID",
            "orchestration action delta must have exact set/remove/operations fields",
        )
    set_value = value.get("set")
    remove_value = value.get("remove")
    operations_value = value.get("operations")
    if (
        not isinstance(set_value, Mapping)
        or not isinstance(remove_value, (tuple, list))
        or not isinstance(operations_value, (tuple, list))
        or operations_value
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_DELTA_INVALID",
            "orchestration action delta requires a set mapping, canonical remove list, and no implicit operations",
        )
    set_items: dict[str, object] = {}
    for raw_pointer, item in set_value.items():
        pointer = _orchestration_action_adapter_pointer(
            raw_pointer, field="proposed_state_delta.set"
        )
        set_items[pointer] = _orchestration_action_adapter_freeze(
            item, f"$delta/set/{pointer}"
        )
    remove_items = tuple(
        _orchestration_action_adapter_pointer(
            item, field=f"proposed_state_delta.remove/{index}"
        )
        for index, item in enumerate(remove_value)
    )
    if remove_items != tuple(
        sorted(remove_items, key=lambda item: item.encode("utf-8"))
    ) or len(remove_items) != len(set(remove_items)):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_DELTA_INVALID",
            "orchestration action remove paths must be unique UTF-8 order",
        )
    write_paths = tuple(
        sorted(
            (*set_items, *remove_items),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if not write_paths:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_DELTA_INVALID",
            "orchestration action must propose at least one exact write",
        )
    if len(write_paths) != len(set(write_paths)):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_DELTA_INVALID",
            "orchestration action cannot set and remove the same path",
        )
    for index, pointer in enumerate(write_paths):
        if not any(
            _orchestration_action_adapter_within(pointer, root)
            for root in allowed_roots
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_WRITE_OUT_OF_SCOPE",
                "orchestration action delta exceeds its sealed kernel write set",
                details={
                    "pointer": pointer,
                    "allowed_roots": list(allowed_roots),
                },
            )
        for other in write_paths[index + 1 :]:
            if _orchestration_action_adapter_paths_overlap(
                pointer, other
            ):
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_DELTA_INVALID",
                    "orchestration action writes cannot contain ancestor/descendant ambiguity",
                    details={"left": pointer, "right": other},
                )
    canonical_set = {
        pointer: set_items[pointer]
        for pointer in sorted(
            set_items, key=lambda item: item.encode("utf-8")
        )
    }
    return _orchestration_action_adapter_freeze(
        {
            "set": canonical_set,
            "remove": list(remove_items),
            "operations": [],
        },
        "$delta",
    )  # type: ignore[return-value]


@dataclass(frozen=True)
class OrchestrationActionSemanticIntent:
    """Typed, operation-bound input to a package-owned semantic validator."""

    operation_id: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_id",
            _orchestration_action_adapter_string(
                self.operation_id, field="operation_id"
            ),
        )
        if not isinstance(self.payload, Mapping):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_INTENT_INVALID",
                "orchestration semantic intent payload must be an object",
            )
        object.__setattr__(
            self,
            "payload",
            _orchestration_action_adapter_freeze(
                self.payload, "$semantic_intent/payload"
            ),
        )


@dataclass(frozen=True)
class OrchestrationActionSemanticCandidate:
    """Exact candidate and facts returned only by a registered validator."""

    candidate_state: Mapping[str, object]
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_state, Mapping) or not isinstance(
            self.evidence, Mapping
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_SEMANTIC_CANDIDATE_INVALID",
                "semantic validator must return candidate and evidence objects",
            )
        object.__setattr__(
            self,
            "candidate_state",
            _orchestration_action_adapter_freeze(
                self.candidate_state,
                "$semantic_candidate/state",
            ),
        )
        object.__setattr__(
            self,
            "evidence",
            _orchestration_action_adapter_freeze(
                self.evidence,
                "$semantic_candidate/evidence",
            ),
        )


def _build_orchestration_action_semantic_authority(
) -> tuple[object, object, object]:
    """Own exact validator registration and candidate derivation."""
    expected_operations = globals().get(
        "_workflow_catalog_repository_required_operation_ids"
    )
    identity_provider = globals().get(
        "_workflow_catalog_repository_semantic_identities"
    )
    if not isinstance(expected_operations, frozenset) or not callable(
        identity_provider
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_VALIDATOR_REGISTRY_INVALID",
            "catalog semantic identities are unavailable",
        )
    expected_pairs = {
        operation_id: str(
            identity_provider(operation_id)["validator_id"]
        )
        for operation_id in expected_operations
    }
    runtime_path = _OrchestrationActionAdapterPath(
        __file__
    ).resolve()
    scripts_root = (
        runtime_path.parent
        if runtime_path.parent.name == "scripts"
        else runtime_path.parent.parent
    )
    allowed_implementation_paths = frozenset(
        {
            (
                scripts_root
                / "dev_flow_parts"
                / "orchestration_service.py"
            ).resolve()
        }
    )
    registrations: dict[str, tuple[str, object]] = {}
    registered_validator_ids: set[str] = set()
    registry_lock = _orchestration_action_adapter_threading.Lock()
    registry_frozen = False

    def register(
        operation_id: str,
        validator_id: str,
        validator: object,
    ) -> None:
        nonlocal registry_frozen
        operation_id = _orchestration_action_adapter_string(
            operation_id, field="operation_id"
        )
        validator_id = _orchestration_action_adapter_string(
            validator_id, field="validator_id"
        )
        with registry_lock:
            if registry_frozen:
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_VALIDATOR_REGISTRY_FROZEN",
                    "semantic validator registration is closed",
                )
        expected_validator_id = expected_pairs.get(operation_id)
        if (
            expected_validator_id is None
            or expected_validator_id != validator_id
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_VALIDATOR_REGISTRATION_UNKNOWN",
                "semantic validator registration is absent from the exact catalog surface",
                details={
                    "operation_id": operation_id,
                    "validator_id": validator_id,
                },
            )
        code = getattr(validator, "__code__", None)
        implementation_path = (
            _OrchestrationActionAdapterPath(code.co_filename).resolve()
            if code is not None
            and isinstance(getattr(code, "co_filename", None), str)
            else None
        )
        if (
            not callable(validator)
            or implementation_path
            not in allowed_implementation_paths
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_VALIDATOR_IMPLEMENTATION_FORBIDDEN",
                "semantic validators must be static package implementations",
                details={
                    "operation_id": operation_id,
                    "implementation_path": (
                        str(implementation_path)
                        if implementation_path is not None
                        else None
                    ),
                },
            )
        with registry_lock:
            if registry_frozen:
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_VALIDATOR_REGISTRY_FROZEN",
                    "semantic validator registration is closed",
                )
            if (
                operation_id in registrations
                or validator_id in registered_validator_ids
            ):
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_VALIDATOR_REGISTRATION_DUPLICATE",
                    "semantic validator identities are one-to-one",
                    details={
                        "operation_id": operation_id,
                        "validator_id": validator_id,
                    },
                )
            registrations[operation_id] = (
                validator_id,
                validator,
            )
            registered_validator_ids.add(validator_id)

    def freeze() -> None:
        nonlocal registry_frozen
        with registry_lock:
            if registry_frozen:
                return
            if registrations and set(registrations) != set(
                expected_pairs
            ):
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_VALIDATOR_REGISTRY_INCOMPLETE",
                    "semantic validator registry must cover all 29 operations atomically",
                    details={
                        "missing": sorted(
                            set(expected_pairs) - set(registrations)
                        ),
                    },
                )
            registry_frozen = True

    def validate_and_derive(
        state: Mapping[str, object],
        intent: OrchestrationActionSemanticIntent,
        selection: object,
    ) -> object:
        with registry_lock:
            frozen = registry_frozen
            registration = registrations.get(
                getattr(selection, "operation_id", "")
            )
        if not frozen or registration is None:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_SEMANTIC_VALIDATOR_UNAVAILABLE",
                "no frozen package-owned semantic validator is available",
                details={
                    "operation_id": getattr(
                        selection, "operation_id", None
                    )
                },
            )
        validator_id, validator = registration
        if (
            type(intent) is not OrchestrationActionSemanticIntent
            or intent.operation_id
            != getattr(selection, "operation_id", None)
            or validator_id
            != getattr(selection, "validator_id", None)
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_INTENT_CROSS_BINDING",
                "semantic intent or validator belongs to another operation",
            )
        state_snapshot = _orchestration_action_adapter_thaw(
            _orchestration_action_adapter_freeze(
                state, "$semantic_validator/state"
            )
        )
        assert isinstance(state_snapshot, dict)
        try:
            candidate = validator(
                state_snapshot,
                intent,
                selection,
            )
        except Exception as exc:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_SEMANTIC_VALIDATOR_REJECTED",
                "package-owned semantic validator rejected the intent",
                details={
                    "validator_id": validator_id,
                    "cause_code": getattr(
                        exc, "code", type(exc).__name__
                    ),
                    "cause_details": getattr(exc, "details", {}),
                },
            ) from exc
        if type(candidate) is not OrchestrationActionSemanticCandidate:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_SEMANTIC_CANDIDATE_INVALID",
                "semantic validator returned no typed candidate",
                details={"validator_id": validator_id},
            )
        delta_builder = globals().get(
            "_workflow_transition_exact_state_delta"
        )
        if not callable(delta_builder):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_DELTA_DERIVER_UNAVAILABLE",
                "exact state delta derivation is unavailable",
            )
        candidate_state = _orchestration_action_adapter_thaw(
            candidate.candidate_state
        )
        assert isinstance(candidate_state, dict)
        derived_delta = delta_builder(
            state_snapshot, candidate_state
        )
        delta = _orchestration_action_adapter_normalize_delta(
            derived_delta,
            allowed_roots=tuple(
                getattr(selection, "allowed_write_roots", ())
            ),
        )
        changed_pointers = tuple(
            sorted(
                (
                    *tuple(str(pointer) for pointer in delta["set"]),
                    *tuple(str(pointer) for pointer in delta["remove"]),
                ),
                key=lambda item: item.encode("utf-8"),
            )
        )
        candidate_sha256 = _orchestration_action_adapter_digest(
            candidate_state,
            domain=_orchestration_action_adapter_candidate_domain,
        )
        intent_sha256 = _orchestration_action_adapter_digest(
            {
                "operation_id": intent.operation_id,
                "payload": (
                    _orchestration_action_adapter_thaw(
                        intent.payload
                    )
                ),
            },
            domain=_orchestration_action_adapter_intent_domain,
        )
        delta_sha256 = _orchestration_action_adapter_digest(
            delta, domain=_orchestration_action_adapter_delta_domain
        )
        receipt_sha256 = _orchestration_action_adapter_digest(
            {
                "operation_id": getattr(
                    selection, "operation_id"
                ),
                "validator_id": validator_id,
                "event_id": getattr(selection, "event_id"),
                "intent_sha256": intent_sha256,
                "candidate_state_sha256": candidate_sha256,
                "proposed_state_delta_sha256": delta_sha256,
                "changed_pointers": list(changed_pointers),
                "evidence": (
                    _orchestration_action_adapter_thaw(
                        candidate.evidence
                    )
                ),
            },
            domain=(
                _orchestration_action_adapter_validator_receipt_domain
            ),
        )
        validation = (
            _orchestration_action_adapter_semantic_validation(
                {
                    "operation_id": getattr(
                        selection, "operation_id"
                    ),
                    "validator_id": validator_id,
                    "event_id": getattr(selection, "event_id"),
                    "candidate_state_sha256": candidate_sha256,
                    "changed_pointers": list(changed_pointers),
                    "evidence": (
                        _orchestration_action_adapter_thaw(
                            candidate.evidence
                        )
                    ),
                    "receipt_sha256": receipt_sha256,
                },
                selection=selection,
                changed_pointers=changed_pointers,
            )
        )
        return delta, validation

    return (
        register,
        freeze,
        validate_and_derive,
    )


(
    _register_orchestration_action_semantic_validator,
    freeze_orchestration_action_semantic_validators,
    _orchestration_action_adapter_validate_and_derive,
) = _build_orchestration_action_semantic_authority()


@dataclass(frozen=True)
class OrchestrationActionSelection:
    task_id: str
    expected_revision: int
    workflow_bundle_sha256: str
    node_id: str
    operation_id: str
    action_id: str
    validator_id: str
    event_id: str
    canonical_event: str
    public_command_id: str
    public_selector: str
    public_selector_value: str
    write_set_id: str
    effect_ids: tuple[str, ...]
    edge_id: str
    allowed_write_roots: tuple[str, ...]


@dataclass(frozen=True)
class OrchestrationActionAdapterResult:
    selection: OrchestrationActionSelection
    delta_sha256: str
    binding_sha256: str
    action_outcome: ActionOutcome

    def __post_init__(self) -> None:
        if not isinstance(
            self.selection, OrchestrationActionSelection
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_RESULT_INVALID",
                "orchestration adapter result requires a typed selection",
            )
        _orchestration_action_adapter_digest_string(
            self.delta_sha256, field="delta_sha256"
        )
        _orchestration_action_adapter_digest_string(
            self.binding_sha256, field="binding_sha256"
        )
        if (
            type(self.action_outcome) is not ActionOutcome
            or self.action_outcome.action_id
            != self.selection.action_id
            or self.action_outcome.proposed_edge_id
            != self.selection.edge_id
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_RESULT_INVALID",
                "orchestration adapter result does not bind its typed ActionOutcome",
            )


def _orchestration_action_adapter_catalog(catalog: object | None) -> object:
    if catalog is None:
        services_factory = globals().get(
            "workflow_runtime_services"
        )
        if not callable(services_factory):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_CATALOG_UNAVAILABLE",
                "workflow runtime catalog is unavailable",
            )
        services = services_factory()
        catalog = getattr(services, "catalog", None)
        if catalog is None:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_CATALOG_UNAVAILABLE",
                "workflow runtime services expose no catalog",
            )
    if getattr(catalog, "sealed", None) is not True:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_CATALOG_UNSEALED",
            "orchestration actions require a sealed workflow catalog",
        )
    return catalog


def _orchestration_action_adapter_pinned_bundle(
    state: Mapping[str, object],
    *,
    catalog: object,
    operation_id: str,
) -> object:
    if not isinstance(state, Mapping):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_STATE_INVALID",
            "orchestration action state must be an object",
        )
    if state.get("schema_version") != 3:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_V3_REQUIRED",
            "orchestration action adapter accepts only schema-v3 tasks",
        )
    execution_profile = state.get("execution_profile")
    manager_registry_operation = (
        operation_id
        in _orchestration_action_adapter_manager_selection
    )
    if (
        execution_profile != "multi-repository"
        and not (
            manager_registry_operation
            and execution_profile == "single-repository"
        )
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MULTI_PROFILE_REQUIRED",
            "orchestration actions require the pinned multi-repository profile except for manager registry operations",
        )
    workflow_ref = state.get("workflow_ref")
    if not isinstance(workflow_ref, Mapping) or set(workflow_ref) != (
        _orchestration_action_adapter_workflow_ref_fields
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_WORKFLOW_REF_INVALID",
            "orchestration action task lacks an exact pinned workflow reference",
        )
    bundle_sha256 = _orchestration_action_adapter_digest_string(
        workflow_ref.get("bundle_sha256"),
        field="workflow_ref.bundle_sha256",
    )
    workflow_id = workflow_ref.get("id")
    accepted_workflow_ids = (
        {"full", "lite"} if manager_registry_operation else {"full"}
    )
    if (
        workflow_id not in accepted_workflow_ids
        or workflow_ref.get("version") != 4
        or workflow_ref.get("schema") != "dev-flow-workflow/v1"
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_FULL_V4_REQUIRED",
            (
                "repository orchestration requires full-v4; manager "
                "registry operations accept exact full-v4 or lite-v4"
            ),
        )
    resolver = getattr(catalog, "resolve_identity", None)
    if not callable(resolver):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_CATALOG_UNAVAILABLE",
            "catalog cannot resolve immutable bundle identities",
        )
    try:
        bundle = resolver(bundle_sha256)
    except Exception as exc:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_BUNDLE_UNPINNED",
            "orchestration action bundle identity is not installed",
            details={"bundle_sha256": bundle_sha256},
        ) from exc
    graph = getattr(bundle, "graph", None)
    if (
        getattr(bundle, "workflow_id", None) != workflow_id
        or getattr(bundle, "workflow_version", None) != 4
        or getattr(bundle, "bundle_sha256", None) != bundle_sha256
        or getattr(bundle, "graph_sha256", None)
        != workflow_ref.get("graph_sha256")
        or not isinstance(graph, Mapping)
        or graph.get("legacy_adapter") is not False
        or tuple(graph.get("task_schema_versions", ())) != (3,)
        or graph.get("flow") != workflow_id
        or execution_profile
        not in tuple(
            getattr(bundle, "execution_profiles", ())
        )
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_BUNDLE_BINDING_INVALID",
            "resolved workflow does not match the exact V4 task pin",
        )
    return bundle


def _orchestration_action_adapter_matrix(
    bundle: object,
) -> tuple[
    Mapping[str, Mapping[str, object]],
    frozenset[str],
]:
    metadata = getattr(bundle, "repository_orchestration", None)
    if not isinstance(metadata, Mapping) or set(metadata) != (
        _orchestration_action_adapter_metadata_fields
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            "pinned bundle has no exact repository orchestration metadata",
        )
    if (
        metadata.get("schema")
        != "dev-flow-repository-orchestration/v1"
        or metadata.get("execution_profile") != "multi-repository"
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            "repository orchestration metadata has the wrong schema or profile",
        )
    operation_ids = metadata.get("operation_ids")
    matrix_values = metadata.get("operation_matrix")
    alias_values = metadata.get("legacy_aliases")
    action_nodes = metadata.get("action_nodes")
    required_operation_ids = globals().get(
        "_workflow_catalog_repository_required_operation_ids"
    )
    identity_provider = globals().get(
        "_workflow_catalog_repository_semantic_identities"
    )
    expected_alias_targets = globals().get(
        "_workflow_catalog_repository_legacy_alias_targets"
    )
    if (
        not isinstance(required_operation_ids, frozenset)
        or not callable(identity_provider)
        or not isinstance(expected_alias_targets, Mapping)
        or not isinstance(operation_ids, tuple)
        or not isinstance(matrix_values, tuple)
        or not isinstance(alias_values, tuple)
        or not isinstance(action_nodes, tuple)
        or not action_nodes
        or any(
            not isinstance(item, str) or not item
            for item in operation_ids
        )
        or any(
            not isinstance(item, str) or not item
            for item in action_nodes
        )
        or len(operation_ids) != len(matrix_values)
        or tuple(
            sorted(operation_ids, key=lambda item: item.encode("utf-8"))
        )
        != operation_ids
        or len(operation_ids) != len(set(operation_ids))
        or len(action_nodes) != len(set(action_nodes))
        or set(operation_ids) != required_operation_ids
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            "repository orchestration operation inventory is incomplete or non-canonical",
        )
    aliases: set[str] = set()
    ordered_aliases: list[str] = []
    alias_targets: dict[str, tuple[str, ...]] = {}
    for alias in alias_values:
        if (
            not isinstance(alias, Mapping)
            or set(alias) != _orchestration_action_adapter_alias_fields
            or not isinstance(alias.get("operation_ids"), tuple)
            or not alias.get("operation_ids")
            or any(
                not isinstance(target, str) or not target
                for target in alias.get("operation_ids", ())
            )
            or len(alias.get("operation_ids", ()))
            != len(set(alias.get("operation_ids", ())))
            or tuple(
                sorted(
                    alias.get("operation_ids", ()),
                    key=lambda item: item.encode("utf-8"),
                )
            )
            != alias.get("operation_ids")
            or any(
                target not in operation_ids
                for target in alias.get("operation_ids", ())
            )
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_MATRIX_INVALID",
                "repository orchestration legacy alias is malformed",
            )
        alias_id = _orchestration_action_adapter_string(
            alias.get("alias_id"), field="legacy_aliases.alias_id"
        )
        if alias_id in aliases or alias_id in operation_ids:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_SEMANTIC_OVERLOAD",
                "legacy aliases cannot be authoritative operation identities",
                details={"alias_id": alias_id},
            )
        aliases.add(alias_id)
        ordered_aliases.append(alias_id)
        alias_targets[alias_id] = tuple(alias["operation_ids"])
    if tuple(ordered_aliases) != tuple(
        sorted(ordered_aliases, key=lambda item: item.encode("utf-8"))
    ) or alias_targets != {
        str(alias_id): tuple(targets)
        for alias_id, targets in expected_alias_targets.items()
    }:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            "repository orchestration aliases must use canonical order",
        )
    by_operation: dict[str, Mapping[str, object]] = {}
    semantic_owners: dict[str, tuple[str, str]] = {
        operation_id: (operation_id, "operation_id")
        for operation_id in operation_ids
    }
    semantic_owners.update(
        {
            alias_id: (alias_id, "legacy_alias")
            for alias_id in aliases
        }
    )
    for index, item in enumerate(matrix_values):
        if (
            not isinstance(item, Mapping)
            or set(item) != _orchestration_action_adapter_matrix_fields
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_MATRIX_INVALID",
                "repository operation matrix entry has unknown or missing fields",
                details={"index": index},
            )
        operation_id = _orchestration_action_adapter_string(
            item.get("operation_id"), field="operation_id"
        )
        if operation_id != operation_ids[index] or operation_id in aliases:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_MATRIX_INVALID",
                "operation matrix order differs from its authoritative inventory",
                details={"operation_id": operation_id, "index": index},
            )
        normalized: dict[str, object] = {
            "operation_id": operation_id
        }
        for field in (
            "action_id",
            "validator_id",
            "event_id",
            "write_set_id",
        ):
            semantic_id = _orchestration_action_adapter_string(
                item.get(field), field=field
            )
            previous = semantic_owners.get(semantic_id)
            if previous is not None:
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_SEMANTIC_OVERLOAD",
                    "one semantic identity cannot name two operation roles",
                    details={
                        "semantic_id": semantic_id,
                        "first": list(previous),
                        "second": [operation_id, field],
                    },
                )
            semantic_owners[semantic_id] = (operation_id, field)
            normalized[field] = semantic_id
        raw_effect_ids = item.get("effect_ids")
        if (
            not isinstance(raw_effect_ids, tuple)
            or not raw_effect_ids
            or len(raw_effect_ids) != len(set(raw_effect_ids))
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_MATRIX_INVALID",
                "operation matrix requires unique immutable effect identities",
                details={"operation_id": operation_id},
            )
        effect_ids: list[str] = []
        for effect_id_value in raw_effect_ids:
            effect_id = _orchestration_action_adapter_string(
                effect_id_value, field="effect_ids"
            )
            previous = semantic_owners.get(effect_id)
            if previous is not None:
                raise _orchestration_action_adapter_error(
                    "ORCHESTRATION_ACTION_SEMANTIC_OVERLOAD",
                    "one effect identity cannot be shared across operations",
                    details={
                        "effect_id": effect_id,
                        "first": list(previous),
                        "second": [operation_id, "effect_ids"],
                    },
                )
            semantic_owners[effect_id] = (
                operation_id,
                "effect_ids",
            )
            effect_ids.append(effect_id)
        normalized["effect_ids"] = tuple(effect_ids)
        expected_identities = identity_provider(operation_id)
        if (
            not isinstance(expected_identities, Mapping)
            or {
                "action_id": normalized["action_id"],
                "validator_id": normalized["validator_id"],
                "event_id": normalized["event_id"],
                "write_set_id": normalized["write_set_id"],
                "effect_ids": normalized["effect_ids"],
            }
            != {
                "action_id": expected_identities.get("action_id"),
                "validator_id": expected_identities.get("validator_id"),
                "event_id": expected_identities.get("event_id"),
                "write_set_id": expected_identities.get("write_set_id"),
                "effect_ids": tuple(
                    expected_identities.get("effect_ids", ())
                ),
            }
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_MATRIX_INVALID",
                "operation matrix differs from its package-owned exact semantic identities",
                details={"operation_id": operation_id},
            )
        frozen = _orchestration_action_adapter_freeze(
            normalized, f"$matrix/{index}"
        )
        assert isinstance(frozen, Mapping)
        by_operation[operation_id] = frozen
    if tuple(by_operation) != operation_ids:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            "operation matrix does not exactly cover its operation inventory",
        )
    return MappingProxyType(by_operation), frozenset(aliases)


def _orchestration_action_adapter_select(
    state: Mapping[str, object],
    operation_id: str,
    *,
    catalog: object | None = None,
) -> OrchestrationActionSelection:
    resolved_catalog = _orchestration_action_adapter_catalog(catalog)
    operation_id = _orchestration_action_adapter_string(
        operation_id, field="operation_id"
    )
    bundle = _orchestration_action_adapter_pinned_bundle(
        state,
        catalog=resolved_catalog,
        operation_id=operation_id,
    )
    manager_selection = (
        _orchestration_action_adapter_manager_selection.get(operation_id)
    )
    contract_bundle = bundle
    if (
        manager_selection is not None
        and getattr(bundle, "workflow_id", None) == "lite"
    ):
        try:
            contract_bundle = resolved_catalog.resolve("full", 4)
        except Exception as exc:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_MATRIX_INVALID",
                "manager registry contract source is unavailable",
            ) from exc
    matrix, aliases = _orchestration_action_adapter_matrix(
        contract_bundle
    )
    if operation_id in aliases:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_LEGACY_ALIAS_FORBIDDEN",
            "frozen legacy orchestration aliases cannot authorize schema-v3 actions",
            details={"operation_id": operation_id},
        )
    contract = matrix.get(operation_id)
    if contract is None:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_UNDECLARED",
            "orchestration operation is absent from the pinned matrix",
            details={"operation_id": operation_id},
        )
    task_id = _orchestration_action_adapter_string(
        state.get("task_id"), field="task_id"
    )
    revision = state.get("revision")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_STATE_INVALID",
            "orchestration action state requires a non-negative revision",
        )
    node_id = _orchestration_action_adapter_string(
        state.get("status"), field="status"
    )
    metadata = getattr(bundle, "repository_orchestration", None)
    if manager_selection is None and (
        not isinstance(metadata, Mapping)
        or node_id not in tuple(metadata["action_nodes"])
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_NODE_INVALID",
            "orchestration operation is not placed at the current node",
            details={"node_id": node_id, "operation_id": operation_id},
        )
    if manager_selection is None:
        command = "orchestration"
        selector = operation_id
        expected_public = {
            "id": "orchestration",
            "selector": "operation",
            "values": (operation_id,),
        }
        expected_canonical_event = contract["event_id"]
    else:
        command, selector, expected_canonical_event = manager_selection
        expected_public = {
            "id": command,
            "selector": "authority",
            "values": ("operator",),
        }
    legal_action_edges = getattr(bundle, "legal_action_edges", None)
    if not callable(legal_action_edges):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_EDGE_INVALID",
            "pinned bundle cannot enumerate public actions",
        )
    try:
        local_edges = tuple(legal_action_edges(node_id))
    except Exception as exc:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_EDGE_INVALID",
            "pinned bundle could not enumerate actions at the current node",
            details={
                "node_id": node_id,
                "operation_id": operation_id,
                "command": command,
            },
        ) from exc
    matches = tuple(
        edge
        for edge in local_edges
        if isinstance(edge, Mapping)
        and isinstance(edge.get("public_command"), Mapping)
        and {
            "id": edge["public_command"].get("id"),
            "selector": edge["public_command"].get("selector"),
            "values": tuple(
                edge["public_command"].get("values", ())
            ),
        }
        == expected_public
        and selector in tuple(
            edge["public_command"].get("values", ())
        )
    )
    if len(matches) != 1:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_EDGE_INVALID",
            "public orchestration selector did not resolve one pinned edge",
            details={
                "node_id": node_id,
                "operation_id": operation_id,
                "command": command,
                "match_count": len(matches),
            },
        )
    edge = matches[0]
    if not isinstance(edge, Mapping):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_EDGE_INVALID",
            "public orchestration selector returned a non-edge value",
        )
    if (
        manager_selection is not None
        and getattr(bundle, "workflow_id", None) == "lite"
    ):
        declared_effects = edge.get("effects")
        if not isinstance(declared_effects, tuple) or any(
            not isinstance(effect, Mapping)
            or not isinstance(effect.get("id"), str)
            or not effect.get("id")
            for effect in declared_effects
        ):
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_EDGE_BINDING_INVALID",
                "lite-v4 manager edge has no exact pinned effect set",
            )
        contract = MappingProxyType(
            {
                **dict(contract),
                "effect_ids": tuple(
                    str(effect["id"])
                    for effect in declared_effects
                ),
            }
        )
    trigger = edge.get("trigger")
    public = edge.get("public_command")
    effects = edge.get("effects")
    allowed_roots = edge.get("kernel_state_writes")
    write_sets = globals().get(
        "_workflow_catalog_repository_operation_write_sets"
    )
    expected_allowed_roots = (
        tuple(write_sets.get(operation_id, ()))
        if isinstance(write_sets, Mapping)
        else ()
    )
    if (
        edge.get("class") != "action"
        or edge.get("policy") != "node-action"
        or edge.get("source") != node_id
        or edge.get("target") != node_id
        or not isinstance(edge.get("id"), str)
        or not edge.get("id")
        or not isinstance(trigger, Mapping)
        or set(trigger) != {"id", "kind"}
        or trigger.get("kind") != "action"
        or trigger.get("id") != contract["action_id"]
        or not isinstance(public, Mapping)
        or set(public) != {"id", "selector", "values"}
        or {
            "id": public.get("id"),
            "selector": public.get("selector"),
            "values": tuple(public.get("values", ())),
        }
        != expected_public
        or edge.get("canonical_event") != expected_canonical_event
        or not isinstance(effects, tuple)
        or any(
            not isinstance(effect, Mapping) for effect in effects
        )
        or tuple(
            effect.get("id")
            for effect in effects
            if isinstance(effect, Mapping)
        )
        != tuple(contract["effect_ids"])
        or not isinstance(allowed_roots, tuple)
        or not allowed_roots
        or len(allowed_roots) != len(set(allowed_roots))
        or tuple(allowed_roots) != expected_allowed_roots
        or not all(
            isinstance(root, str) and root.startswith("/")
            for root in allowed_roots
        )
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_EDGE_BINDING_INVALID",
            "selected edge differs from its operation/action/event/write/effect contract",
            details={
                "edge_id": edge.get("id"),
                "operation_id": operation_id,
            },
        )
    workflow_ref = state["workflow_ref"]
    assert isinstance(workflow_ref, Mapping)
    selection = OrchestrationActionSelection(
        task_id=task_id,
        expected_revision=revision,
        workflow_bundle_sha256=str(
            workflow_ref["bundle_sha256"]
        ),
        node_id=node_id,
        operation_id=operation_id,
        action_id=str(contract["action_id"]),
        validator_id=str(contract["validator_id"]),
        event_id=str(contract["event_id"]),
        canonical_event=str(expected_canonical_event),
        public_command_id=command,
        public_selector=str(expected_public["selector"]),
        public_selector_value=selector,
        write_set_id=str(contract["write_set_id"]),
        effect_ids=tuple(
            str(item) for item in contract["effect_ids"]
        ),
        edge_id=str(edge["id"]),
        allowed_write_roots=tuple(str(item) for item in allowed_roots),
    )
    return selection


def _orchestration_action_adapter_selection_binding(
    selection: OrchestrationActionSelection,
) -> dict[str, object]:
    return {
        "task_id": selection.task_id,
        "expected_revision": selection.expected_revision,
        "workflow_bundle_sha256": (
            selection.workflow_bundle_sha256
        ),
        "node_id": selection.node_id,
        "operation_id": selection.operation_id,
        "action_id": selection.action_id,
        "validator_id": selection.validator_id,
        "event_id": selection.event_id,
        "canonical_event": selection.canonical_event,
        "public_command_id": selection.public_command_id,
        "public_selector": selection.public_selector,
        "public_selector_value": selection.public_selector_value,
        "write_set_id": selection.write_set_id,
        "effect_ids": list(selection.effect_ids),
        "edge_id": selection.edge_id,
        "allowed_write_roots": list(
            selection.allowed_write_roots
        ),
    }


def _orchestration_action_adapter_semantic_validation(
    value: object,
    *,
    selection: OrchestrationActionSelection,
    changed_pointers: tuple[str, ...],
) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != _orchestration_action_adapter_semantic_validation_fields
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_SEMANTIC_VALIDATION_INVALID",
            "semantic validator output has missing or unknown fields",
        )
    supplied_pointers = value.get("changed_pointers")
    if not isinstance(supplied_pointers, (tuple, list)):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_SEMANTIC_VALIDATION_INVALID",
            "semantic validator changed pointers must be an array",
        )
    normalized_pointers = tuple(
        _orchestration_action_adapter_pointer(
            pointer,
            field=f"semantic_validation.changed_pointers/{index}",
        )
        for index, pointer in enumerate(supplied_pointers)
    )
    if (
        normalized_pointers != changed_pointers
        or normalized_pointers
        != tuple(
            sorted(
                normalized_pointers,
                key=lambda item: item.encode("utf-8"),
            )
        )
        or len(normalized_pointers) != len(set(normalized_pointers))
    ):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_SEMANTIC_VALIDATION_INVALID",
            "semantic validator output does not bind the exact delta paths",
            details={
                "expected": list(changed_pointers),
                "actual": list(normalized_pointers),
            },
        )
    identity_mismatches = {
        field: {
            "expected": getattr(selection, field),
            "actual": value.get(field),
        }
        for field in ("operation_id", "validator_id", "event_id")
        if value.get(field) != getattr(selection, field)
    }
    if identity_mismatches:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_SEMANTIC_VALIDATION_CROSS_BINDING",
            "semantic validator output belongs to a different catalog action",
            details={"mismatches": identity_mismatches},
        )
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping):
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_SEMANTIC_VALIDATION_INVALID",
            "semantic validator output requires an evidence object",
        )
    normalized = {
        "operation_id": selection.operation_id,
        "validator_id": selection.validator_id,
        "event_id": selection.event_id,
        "candidate_state_sha256": (
            _orchestration_action_adapter_digest_string(
                value.get("candidate_state_sha256"),
                field="semantic_validation.candidate_state_sha256",
            )
        ),
        "changed_pointers": list(normalized_pointers),
        "evidence": _orchestration_action_adapter_thaw(
            _orchestration_action_adapter_freeze(
                evidence, "$semantic_validation/evidence"
            )
        ),
        "receipt_sha256": (
            _orchestration_action_adapter_digest_string(
                value.get("receipt_sha256"),
                field="semantic_validation.receipt_sha256",
            )
        ),
    }
    frozen = _orchestration_action_adapter_freeze(
        normalized, "$semantic_validation"
    )
    assert isinstance(frozen, Mapping)
    return frozen


def _orchestration_action_adapter_manager_nonce_declared(
    delta: Mapping[str, object],
    selection: OrchestrationActionSelection,
) -> bool:
    manager_root = "/orchestration/manager_capabilities"
    paths = tuple(
        str(pointer)
        for pointer in (
            *tuple(delta["set"]),
            *tuple(delta["remove"]),
        )
        if _orchestration_action_adapter_within(
            str(pointer), manager_root
        )
    )
    operator_registry_operation = (
        selection.operation_id
        in _orchestration_action_adapter_manager_selection
    )
    if not paths:
        if operator_registry_operation:
            return False
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MANAGER_NONCE_REQUIRED",
            "manager-authorized orchestration actions must consume one exact request nonce path",
            details={
                "operation_id": selection.operation_id,
                "paths": [],
                "nonce_paths": [],
            },
        )
    declared = all(
        any(
            _orchestration_action_adapter_within(pointer, root)
            for root in selection.allowed_write_roots
        )
        for pointer in paths
    )
    if not declared:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MANAGER_NONCE_UNDECLARED",
            "manager nonce paths require an explicit sealed kernel write root",
            details={"paths": list(paths)},
        )
    nonce_paths = tuple(
        pointer
        for pointer in paths
        if (
            len(pointer[len(manager_root) + 1 :].split("/")) >= 2
            and pointer[len(manager_root) + 1 :].split("/")[0]
            and pointer[len(manager_root) + 1 :].split("/")[1]
            == "used_request_nonce_sha256s"
        )
    )
    if operator_registry_operation:
        if nonce_paths:
            raise _orchestration_action_adapter_error(
                "ORCHESTRATION_ACTION_MANAGER_NONCE_FORBIDDEN",
                "operator registry actions cannot consume a manager request nonce",
                details={
                    "operation_id": selection.operation_id,
                    "paths": list(paths),
                    "nonce_paths": list(nonce_paths),
                },
            )
        return False
    if len(nonce_paths) != 1:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_MANAGER_NONCE_REQUIRED",
            "manager-authorized orchestration actions must consume one exact request nonce path",
            details={
                "operation_id": selection.operation_id,
                "paths": list(paths),
                "nonce_paths": list(nonce_paths),
            },
        )
    return True


def resolve_catalog_orchestration_action(
    state: Mapping[str, object],
    operation_id: str,
    *,
    catalog: object | None = None,
) -> OrchestrationActionSelection:
    """Resolve one immutable operation/validator/edge contract."""

    return _orchestration_action_adapter_select(
        state, operation_id, catalog=catalog
    )


def build_catalog_orchestration_action_outcome(
    state: Mapping[str, object],
    operation_id: str,
    intent: OrchestrationActionSemanticIntent,
    *,
    catalog: object | None = None,
) -> OrchestrationActionAdapterResult:
    """Validate intent and build one outcome; never persist or dispatch."""

    selection = _orchestration_action_adapter_select(
        state, operation_id, catalog=catalog
    )
    if type(intent) is not OrchestrationActionSemanticIntent:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_INTENT_INVALID",
            "orchestration actions require a typed semantic intent",
        )
    if intent.operation_id != selection.operation_id:
        raise _orchestration_action_adapter_error(
            "ORCHESTRATION_ACTION_INTENT_CROSS_BINDING",
            "semantic intent belongs to another catalog operation",
            details={
                "selected_operation_id": selection.operation_id,
                "intent_operation_id": intent.operation_id,
            },
        )
    authority_candidate_delta, semantic_validation = (
        _orchestration_action_adapter_validate_and_derive(
            state, intent, selection
        )
    )
    assert isinstance(authority_candidate_delta, Mapping)
    assert isinstance(semantic_validation, Mapping)
    manager_nonce_write_declared = (
        _orchestration_action_adapter_manager_nonce_declared(
            authority_candidate_delta, selection
        )
    )
    delta = authority_candidate_delta
    if manager_nonce_write_declared:
        manager_root = "/orchestration/manager_capabilities"
        delta = {
            "set": {
                str(pointer): value
                for pointer, value in authority_candidate_delta[
                    "set"
                ].items()
                if not _orchestration_action_adapter_within(
                    str(pointer), manager_root
                )
            },
            "remove": [
                str(pointer)
                for pointer in authority_candidate_delta["remove"]
                if not _orchestration_action_adapter_within(
                    str(pointer), manager_root
                )
            ],
            "operations": list(
                authority_candidate_delta["operations"]
            ),
        }
    delta_sha256 = _orchestration_action_adapter_digest(
        delta, domain=_orchestration_action_adapter_delta_domain
    )
    authority_candidate_delta_sha256 = (
        _orchestration_action_adapter_digest(
            authority_candidate_delta,
            domain=_orchestration_action_adapter_delta_domain,
        )
    )
    binding = {
        "contract": _orchestration_action_adapter_evidence_contract,
        **_orchestration_action_adapter_selection_binding(selection),
        "manager_nonce_write_declared": manager_nonce_write_declared,
        "authority_candidate_delta_sha256": (
            authority_candidate_delta_sha256
        ),
        "proposed_state_delta_sha256": delta_sha256,
        "semantic_validation": (
            _orchestration_action_adapter_thaw(semantic_validation)
        ),
    }
    binding_sha256 = _orchestration_action_adapter_digest(
        binding, domain=_orchestration_action_adapter_binding_domain
    )
    evidence = {
        **binding,
        "binding_sha256": binding_sha256,
    }
    outcome = ActionOutcome(
        selection.action_id,
        selection.edge_id,
        evidence_records=(evidence,),
        proposed_state_delta=delta,
        audit_facts=(
            AuditFact(
                "orchestration-action-catalog-bound",
                evidence,
            ),
        ),
    )
    return OrchestrationActionAdapterResult(
        selection=selection,
        delta_sha256=delta_sha256,
        binding_sha256=binding_sha256,
        action_outcome=outcome,
    )


__all__ = [
    "OrchestrationActionAdapterError",
    "OrchestrationActionAdapterResult",
    "OrchestrationActionSemanticCandidate",
    "OrchestrationActionSemanticIntent",
    "OrchestrationActionSelection",
    "build_catalog_orchestration_action_outcome",
    "resolve_catalog_orchestration_action",
]
