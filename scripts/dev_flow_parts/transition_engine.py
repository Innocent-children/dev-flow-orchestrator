# Loaded by scripts/dev_flow.py into its shared module namespace after the
# workflow catalog and sealed registries.  The engine is deliberately pure:
# lock acquisition, state reload, durable commit, and external effects remain
# controller services supplied by the caller.
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
import threading
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence


_TERMINAL_NODE_IDS = frozenset({"DONE", "CANCELLED"})
_PROTECTED_STATE_PATHS = (
    "/task_id",
    "/schema_version",
    "/workflow_ref",
    "/revision",
    "/pending_event",
    "/pending_events",
    "/approvals",
    "/quarantine",
    "/mutation_intent",
    "/workspace/ownership",
)
_transition_engine_kernel_context_contract = (
    "dev-flow-transition-kernel-context/v1"
)
_transition_engine_supported_workflow_schemas = frozenset(
    {"dev-flow-workflow/v1"}
)
_transition_engine_path_effect_markers = (
    "filesystem",
    "git",
    "repository",
    "review-snapshot",
    "workspace",
)
_transition_engine_missing_contract_codes = frozenset(
    {
        "REGISTRY_UNKNOWN_REFERENCE",
        "REGISTRY_SYMBOL_UNAVAILABLE",
        "WORKFLOW_CONTRACT_UNKNOWN",
    }
)
_transition_engine_effect_write_paths = MappingProxyType(
    {
        "invalidate-approval": ("/approvals",),
        "invalidate-evidence": ("/evidence", "/evidence_records"),
        "record-approval": ("/approvals",),
        "record-artifact": ("/artifacts",),
        "record-cancellation": ("/cancelled",),
        "record-repository-state": ("/repositories",),
        "record-review-snapshot": ("/review_snapshots",),
        "record-workspace-ownership": ("/repositories", "/workspace"),
        "release-repository-claim": ("/repositories",),
        "retire-workspace-ownership": ("/repositories", "/workspace"),
        "set-task-status": ("/status",),
    }
)


class TransitionEngineError(Exception):
    """Stable structured blocker emitted before any state commit."""

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


def _freeze_contract_value(value: object, path: str = "$") -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise TransitionEngineError(
            "TRANSITION_CONTRACT_INVALID",
            "workflow contracts must not contain floating-point values",
            details={"path": path},
        )
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TransitionEngineError(
                    "TRANSITION_CONTRACT_INVALID",
                    "workflow contract object keys must be strings",
                    details={"path": path},
                )
            frozen[key] = _freeze_contract_value(item, f"{path}/{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_contract_value(item, f"{path}/{index}")
            for index, item in enumerate(value)
        )
    raise TransitionEngineError(
        "TRANSITION_CONTRACT_INVALID",
        "workflow contracts must contain only canonical JSON values",
        details={"path": path, "type": type(value).__name__},
    )


def _thaw_contract_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _thaw_contract_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_contract_value(item) for item in value]
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _thaw_contract_value(_freeze_contract_value(value)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        if isinstance(exc, TransitionEngineError):
            raise
        raise TransitionEngineError(
            "TRANSITION_CONTRACT_INVALID",
            "workflow contract cannot be canonically encoded",
        ) from exc


def _sha256_contract(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class AuditFact:
    fact_type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.fact_type, str) or not self.fact_type:
            raise TransitionEngineError(
                "AUDIT_FACT_INVALID", "audit fact type is required"
            )
        object.__setattr__(
            self,
            "payload",
            _freeze_contract_value(dict(self.payload), "$audit_fact"),
        )


@dataclass(frozen=True)
class GuardResult:
    passed: bool
    evidence: Mapping[str, object]
    blockers: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TransitionEngineError(
                "GUARD_RESULT_INVALID", "guard result must declare passed"
            )
        object.__setattr__(
            self,
            "evidence",
            _freeze_contract_value(dict(self.evidence), "$guard/evidence"),
        )
        object.__setattr__(
            self,
            "blockers",
            tuple(
                _freeze_contract_value(
                    dict(item), f"$guard/blockers/{index}"
                )
                for index, item in enumerate(self.blockers)
            ),
        )


@dataclass(frozen=True)
class ReducerResult:
    candidate_state: Mapping[str, object]
    audit_facts: tuple[AuditFact, ...] = ()
    kernel_state_delta: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_state",
            _freeze_contract_value(
                dict(self.candidate_state), "$reducer/candidate_state"
            ),
        )
        if not all(
            isinstance(item, AuditFact) for item in self.audit_facts
        ):
            raise TransitionEngineError(
                "REDUCER_RESULT_INVALID",
                "reducer audit facts must use AuditFact",
            )
        object.__setattr__(self, "audit_facts", tuple(self.audit_facts))
        object.__setattr__(
            self,
            "kernel_state_delta",
            _freeze_contract_value(
                dict(self.kernel_state_delta), "$reducer/kernel_state_delta"
            ),
        )


@dataclass(frozen=True)
class KernelEffectResult:
    """Candidate changes owned by the non-extensible controller kernel."""

    candidate_state: Mapping[str, object]
    audit_facts: tuple[AuditFact, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_state",
            _freeze_contract_value(
                dict(self.candidate_state), "$kernel/candidate_state"
            ),
        )
        if not all(
            isinstance(item, AuditFact) for item in self.audit_facts
        ):
            raise TransitionEngineError(
                "KERNEL_EFFECT_RESULT_INVALID",
                "kernel effect audit facts must use AuditFact",
            )
        object.__setattr__(self, "audit_facts", tuple(self.audit_facts))


@dataclass(frozen=True)
class ActionOutcome:
    action_id: str
    proposed_edge_id: str
    evidence_records: tuple[Mapping[str, object], ...] = ()
    proposed_state_delta: Mapping[str, object] = MappingProxyType({})
    audit_facts: tuple[AuditFact, ...] = ()
    external_postconditions: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id or not self.proposed_edge_id:
            raise TransitionEngineError(
                "ACTION_OUTCOME_INVALID",
                "action and proposed edge identities are required",
            )
        object.__setattr__(
            self,
            "evidence_records",
            tuple(
                _freeze_contract_value(
                    dict(item), f"$action/evidence/{index}"
                )
                for index, item in enumerate(self.evidence_records)
            ),
        )
        object.__setattr__(
            self,
            "proposed_state_delta",
            _freeze_contract_value(
                dict(self.proposed_state_delta), "$action/state_delta"
            ),
        )
        if not all(
            isinstance(item, AuditFact) for item in self.audit_facts
        ):
            raise TransitionEngineError(
                "ACTION_OUTCOME_INVALID",
                "action audit facts must use AuditFact",
            )
        object.__setattr__(self, "audit_facts", tuple(self.audit_facts))
        object.__setattr__(
            self,
            "external_postconditions",
            tuple(
                _freeze_contract_value(
                    dict(item), f"$action/postconditions/{index}"
                )
                for index, item in enumerate(
                    self.external_postconditions
                )
            ),
        )


@dataclass(frozen=True)
class ApprovalOutcome:
    gate_id: str
    proposed_edge_id: str
    approval: Mapping[str, object]
    evidence_records: tuple[Mapping[str, object], ...] = ()
    audit_facts: tuple[AuditFact, ...] = ()

    def __post_init__(self) -> None:
        if not self.gate_id or not self.proposed_edge_id:
            raise TransitionEngineError(
                "APPROVAL_OUTCOME_INVALID",
                "gate and proposed edge identities are required",
            )
        object.__setattr__(
            self,
            "approval",
            _freeze_contract_value(
                dict(self.approval), "$approval/record"
            ),
        )
        object.__setattr__(
            self,
            "evidence_records",
            tuple(
                _freeze_contract_value(
                    dict(item), f"$approval/evidence/{index}"
                )
                for index, item in enumerate(self.evidence_records)
            ),
        )
        if not all(
            isinstance(item, AuditFact) for item in self.audit_facts
        ):
            raise TransitionEngineError(
                "APPROVAL_OUTCOME_INVALID",
                "approval audit facts must use AuditFact",
            )
        object.__setattr__(self, "audit_facts", tuple(self.audit_facts))


@dataclass(frozen=True)
class KernelTransitionContext:
    """Immutable controller proof required for schema-v4 evaluation."""

    task_id: str
    workflow_ref: Mapping[str, object]
    task_lock_held: bool
    workspace_lock_held: bool
    ownership_lock_held: bool
    evidence_sha256: str
    evidence_authentic: bool
    evidence_current: bool
    approval_current: bool = False
    approval_intent_id: str | None = None
    supported_node_contracts: Mapping[str, Sequence[str]] = (
        MappingProxyType({})
    )
    supported_contract_versions: Mapping[str, Sequence[str]] = (
        MappingProxyType({})
    )
    authorized_effects: tuple[str, ...] = ()
    requested_effect_paths: tuple[str, ...] = ()
    authorized_paths: tuple[str, ...] = ()
    contract: str = _transition_engine_kernel_context_contract

    def __post_init__(self) -> None:
        if self.contract != _transition_engine_kernel_context_contract:
            raise TransitionEngineError(
                "KERNEL_CONTEXT_UNSUPPORTED",
                "kernel transition context contract is unsupported",
                details={
                    "contract": self.contract,
                    "supported": [
                        _transition_engine_kernel_context_contract
                    ],
                },
            )
        if not isinstance(self.task_id, str) or not self.task_id:
            raise TransitionEngineError(
                "KERNEL_CONTEXT_INVALID",
                "kernel transition context must identify one task",
            )
        for field in (
            "task_lock_held",
            "workspace_lock_held",
            "ownership_lock_held",
            "evidence_authentic",
            "evidence_current",
            "approval_current",
        ):
            if not isinstance(getattr(self, field), bool):
                raise TransitionEngineError(
                    "KERNEL_CONTEXT_INVALID",
                    "kernel proof flags must be booleans",
                    details={"field": field},
                )
        object.__setattr__(
            self,
            "workflow_ref",
            _freeze_contract_value(
                copy.deepcopy(dict(self.workflow_ref)),
                "$kernel_context/workflow_ref",
            ),
        )
        object.__setattr__(
            self,
            "supported_node_contracts",
            _freeze_contract_value(
                copy.deepcopy(dict(self.supported_node_contracts)),
                "$kernel_context/supported_node_contracts",
            ),
        )
        object.__setattr__(
            self,
            "supported_contract_versions",
            _freeze_contract_value(
                copy.deepcopy(dict(self.supported_contract_versions)),
                "$kernel_context/supported_contract_versions",
            ),
        )
        for field in (
            "authorized_effects",
            "requested_effect_paths",
            "authorized_paths",
        ):
            values = tuple(getattr(self, field))
            if any(not isinstance(item, str) or not item for item in values):
                raise TransitionEngineError(
                    "KERNEL_CONTEXT_INVALID",
                    "kernel authority lists must contain non-empty strings",
                    details={"field": field},
                )
            object.__setattr__(self, field, tuple(sorted(set(values))))


@dataclass(frozen=True)
class TransitionEvaluation:
    edge_id: str
    source: str
    target: str
    intent: Mapping[str, object]
    candidate_state: Mapping[str, object]
    changed_paths: tuple[str, ...]
    guard_results: tuple[tuple[str, GuardResult], ...]
    audit_facts: tuple[AuditFact, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "intent",
            _freeze_contract_value(dict(self.intent), "$evaluation/intent"),
        )
        object.__setattr__(
            self,
            "candidate_state",
            _freeze_contract_value(
                dict(self.candidate_state), "$evaluation/candidate_state"
            ),
        )
        object.__setattr__(self, "changed_paths", tuple(self.changed_paths))
        object.__setattr__(
            self, "guard_results", tuple(self.guard_results)
        )
        object.__setattr__(self, "audit_facts", tuple(self.audit_facts))


def _transition_engine_audit_fact_binding(
    facts: Sequence[AuditFact],
) -> list[dict[str, object]]:
    return [
        {
            "fact_type": fact.fact_type,
            "payload": _thaw_contract_value(fact.payload),
        }
        for fact in facts
    ]


def _transition_engine_action_outcome_binding(
    outcome: ActionOutcome | None,
) -> dict[str, object] | None:
    if outcome is None:
        return None
    return {
        "action_id": outcome.action_id,
        "proposed_edge_id": outcome.proposed_edge_id,
        "evidence_records": _thaw_contract_value(
            outcome.evidence_records
        ),
        "proposed_state_delta": _thaw_contract_value(
            outcome.proposed_state_delta
        ),
        "audit_facts": _transition_engine_audit_fact_binding(
            outcome.audit_facts
        ),
        "external_postconditions": _thaw_contract_value(
            outcome.external_postconditions
        ),
    }


def _transition_engine_approval_outcome_binding(
    outcome: ApprovalOutcome | None,
) -> dict[str, object] | None:
    if outcome is None:
        return None
    return {
        "gate_id": outcome.gate_id,
        "proposed_edge_id": outcome.proposed_edge_id,
        "approval": _thaw_contract_value(outcome.approval),
        "evidence_records": _thaw_contract_value(
            outcome.evidence_records
        ),
        "audit_facts": _transition_engine_audit_fact_binding(
            outcome.audit_facts
        ),
    }


def _transition_engine_evaluation_binding(
    evaluation: TransitionEvaluation,
) -> dict[str, object]:
    return {
        "edge_id": evaluation.edge_id,
        "source": evaluation.source,
        "target": evaluation.target,
        "intent": _thaw_contract_value(evaluation.intent),
        "candidate_state_sha256": _sha256_contract(
            evaluation.candidate_state
        ),
        "changed_paths": list(evaluation.changed_paths),
        "guard_results": [
            {
                "guard_id": guard_id,
                "passed": result.passed,
                "evidence": _thaw_contract_value(result.evidence),
                "blockers": _thaw_contract_value(result.blockers),
            }
            for guard_id, result in evaluation.guard_results
        ],
        "audit_facts": _transition_engine_audit_fact_binding(
            evaluation.audit_facts
        ),
    }


_transition_engine_evaluation_lock_observer: (
    Callable[[Mapping[str, object]], Mapping[str, object]] | None
) = None


def install_transition_engine_evaluation_lock_observer(
    observer: Callable[
        [Mapping[str, object]], Mapping[str, object]
    ],
) -> None:
    """Install the trusted controller's exact live-lock observer once.

    The pure engine can still be loaded in isolation for preview and contract
    tests.  In the composed controller, however, every non-preview schema-v4
    issuance records the opaque lock capabilities that were live at the
    instant the evaluation completed.  A later commit must observe the same
    capabilities; copied ContextVar path metadata is therefore insufficient.
    """

    global _transition_engine_evaluation_lock_observer
    if not callable(observer):
        raise TransitionEngineError(
            "V4_ENGINE_LOCK_OBSERVER_INVALID",
            "engine evaluation lock observer must be callable",
        )
    if _transition_engine_evaluation_lock_observer is not None:
        if _transition_engine_evaluation_lock_observer is observer:
            return
        raise TransitionEngineError(
            "V4_ENGINE_LOCK_OBSERVER_ALREADY_INSTALLED",
            "engine evaluation lock observer is immutable for this process",
        )
    _transition_engine_evaluation_lock_observer = observer


def _transition_engine_observe_evaluation_locks(
    state: Mapping[str, object],
) -> dict[str, object] | None:
    observer = _transition_engine_evaluation_lock_observer
    if observer is None:
        # Standalone pure-engine consumers cannot mint a durable controller
        # proof because the proof-minting service rejects this absent binding.
        return None
    observed = observer(state)
    if not isinstance(observed, Mapping):
        raise TransitionEngineError(
            "V4_ENGINE_LOCK_OBSERVER_INVALID",
            "engine evaluation lock observer returned a non-object binding",
        )
    public = _thaw_contract_value(
        _freeze_contract_value(
            copy.deepcopy(dict(observed)),
            "$engine_evaluation_lock_capabilities",
        )
    )
    if not isinstance(public, dict):
        raise TransitionEngineError(
            "V4_ENGINE_LOCK_OBSERVER_INVALID",
            "engine evaluation lock binding must be an object",
        )
    return public


def _build_transition_evaluation_issuance_registry(
) -> tuple[
    Callable[..., None],
    Callable[[object], dict[str, object]],
]:
    """Keep commit authority separate from the public evaluation value.

    ``TransitionEvaluation`` intentionally remains a public, inspectable
    projection.  Only the exact object returned by a successful non-preview
    schema-v4 kernel evaluation is entered in this process-private one-shot
    registry.  Reconstructing, copying, or replacing that dataclass therefore
    cannot create commit authority.
    """

    registry: dict[
        int, tuple[TransitionEvaluation, bytes, dict[str, object]]
    ] = {}
    registry_lock = threading.Lock()

    def register(
        evaluation: TransitionEvaluation,
        *,
        state: Mapping[str, object],
        action_id: str,
        action_parameters: Mapping[str, object],
        evidence: Mapping[str, object],
        action_outcome: ActionOutcome | None,
        approval_outcome: ApprovalOutcome | None,
        kernel_context: Mapping[str, object],
    ) -> None:
        record = {
            "contract": "dev-flow-engine-evaluation-issuance/v1",
            "task_id": state.get("task_id"),
            "expected_revision": state.get("revision"),
            "workflow_ref": _thaw_contract_value(
                state.get("workflow_ref", {})
            ),
            "old_state_sha256": _sha256_contract(state),
            "evaluation_lock_capabilities": (
                _transition_engine_observe_evaluation_locks(state)
            ),
            "action": {
                "action_id": action_id,
                "parameters": _thaw_contract_value(action_parameters),
                "outcome": _transition_engine_action_outcome_binding(
                    action_outcome
                ),
                "approval_outcome": (
                    _transition_engine_approval_outcome_binding(
                        approval_outcome
                    )
                ),
                "evidence_sha256": _sha256_contract(evidence),
            },
            "kernel_context": _thaw_contract_value(kernel_context),
            "evaluation": _transition_engine_evaluation_binding(
                evaluation
            ),
        }
        canonical = _canonical_json_bytes(record)
        with registry_lock:
            registry[id(evaluation)] = (
                evaluation,
                canonical,
                record,
            )

    def consume(value: object) -> dict[str, object]:
        if type(value) is not TransitionEvaluation:
            raise TransitionEngineError(
                "V4_ENGINE_EVALUATION_UNREGISTERED",
                "commit proof requires an exact kernel-issued evaluation",
            )
        evaluation = value
        with registry_lock:
            registered = registry.get(id(evaluation))
            if (
                registered is None
                or registered[0] is not evaluation
            ):
                raise TransitionEngineError(
                    "V4_ENGINE_EVALUATION_UNREGISTERED",
                    "public or replayed evaluation has no live kernel issuance",
                )
            # Pop before validating the public projection.  Mutation, failed
            # minting, or any later exception cannot make this issuance live
            # again.
            del registry[id(evaluation)]
        _registered_value, canonical, record = registered
        observed = dict(record)
        observed["evaluation"] = (
            _transition_engine_evaluation_binding(evaluation)
        )
        if not hmac.compare_digest(
            canonical, _canonical_json_bytes(observed)
        ):
            raise TransitionEngineError(
                "V4_ENGINE_EVALUATION_CHANGED",
                "kernel evaluation changed after issuance",
            )
        return copy.deepcopy(record)

    return register, consume


(
    _transition_engine_register_evaluation_issuance,
    _transition_engine_consume_evaluation_issuance,
) = _build_transition_evaluation_issuance_registry()


def _build_engine_commit_proof_broker(
) -> tuple[
    type,
    Callable[[Mapping[str, object]], object],
    Callable[
        [
            object,
            Callable[[], Mapping[str, object]]
            | Mapping[str, object],
        ],
        dict[str, object],
    ],
]:
    """Create the controller-start-private proof type, key, and registry."""

    construction_capability = object()
    signing_key = secrets.token_bytes(32)
    registry_lock = threading.Lock()
    registry: dict[
        str, tuple[object, bytes, str, dict[str, object]]
    ] = {}
    domain = b"dev-flow-v4-engine-commit-proof-v1\0"
    durable_observed_bindings = frozenset(
        {
            "task_directory",
            "held_lock_capabilities",
            "task",
            "workflow",
            "old_state_sha256",
            "candidate_state_sha256",
            "event_batch",
            "verified_receipt",
        }
    )

    class EngineCommitProof:
        """Opaque one-shot authority for one exact durable v4 transaction."""

        __slots__ = ("__issuance_id", "__mac")

        def __new__(
            cls,
            capability: object = None,
            issuance_id: str | None = None,
            mac: str | None = None,
        ) -> "EngineCommitProof":
            if capability is not construction_capability:
                raise TypeError(
                    "EngineCommitProof values are issued by the kernel"
                )
            instance = super().__new__(cls)
            object.__setattr__(
                instance,
                "_EngineCommitProof__issuance_id",
                issuance_id,
            )
            object.__setattr__(
                instance,
                "_EngineCommitProof__mac",
                mac,
            )
            return instance

        def __repr__(self) -> str:
            return "<EngineCommitProof opaque>"

        __str__ = __repr__

        def __copy__(self) -> object:
            raise TypeError("EngineCommitProof cannot be copied")

        def __deepcopy__(self, _memo: object) -> object:
            raise TypeError("EngineCommitProof cannot be deep-copied")

        def __reduce__(self) -> object:
            raise TypeError("EngineCommitProof cannot be serialized")

        def __reduce_ex__(self, _protocol: int) -> object:
            raise TypeError("EngineCommitProof cannot be serialized")

        def __getstate__(self) -> object:
            raise TypeError("EngineCommitProof cannot be serialized")

    EngineCommitProof.__name__ = "EngineCommitProof"
    EngineCommitProof.__qualname__ = "EngineCommitProof"

    def framed(core: bytes) -> bytes:
        return domain + len(core).to_bytes(8, "big") + core

    def semantic_json_bytes(value: object, path: str = "$") -> bytes:
        def validate(item: object, pointer: str) -> object:
            if item is None or isinstance(item, bool):
                return item
            if isinstance(item, int):
                if not -(2**63) <= item <= 2**63 - 1:
                    raise TransitionEngineError(
                        "V4_ENGINE_COMMIT_CANONICALIZATION_INVALID",
                        "engine proof integers must fit signed 64-bit",
                        details={"path": pointer},
                    )
                return item
            if isinstance(item, str):
                if unicodedata.normalize("NFC", item) != item:
                    raise TransitionEngineError(
                        "V4_ENGINE_COMMIT_CANONICALIZATION_INVALID",
                        "engine proof strings must use NFC",
                        details={"path": pointer},
                    )
                try:
                    item.encode("utf-8", "strict")
                except UnicodeEncodeError as exc:
                    raise TransitionEngineError(
                        "V4_ENGINE_COMMIT_CANONICALIZATION_INVALID",
                        "engine proof strings must use exact UTF-8",
                        details={"path": pointer},
                    ) from exc
                return item
            if isinstance(item, Mapping):
                result: dict[str, object] = {}
                for key, child in item.items():
                    if (
                        not isinstance(key, str)
                        or unicodedata.normalize("NFC", key) != key
                    ):
                        raise TransitionEngineError(
                            "V4_ENGINE_COMMIT_CANONICALIZATION_INVALID",
                            "engine proof object keys must be NFC strings",
                            details={"path": pointer},
                        )
                    result[key] = validate(
                        child, f"{pointer}/{_pointer_segment(key)}"
                    )
                return result
            if isinstance(item, (list, tuple)):
                return [
                    validate(child, f"{pointer}/{index}")
                    for index, child in enumerate(item)
                ]
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_CANONICALIZATION_INVALID",
                "engine proof contains a non-semantic JSON value",
                details={
                    "path": pointer,
                    "type": type(item).__name__,
                },
            )

        normalized = validate(value, path)
        try:
            return json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_CANONICALIZATION_INVALID",
                "engine proof cannot be canonically encoded",
                details={"path": path},
            ) from exc

    def issue(core: Mapping[str, object]) -> object:
        normalized = _thaw_contract_value(
            _freeze_contract_value(
                copy.deepcopy(dict(core)), "$engine_commit_proof"
            )
        )
        if not isinstance(normalized, dict):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_INVALID",
                "engine commit proof core must be an object",
            )
        core_bytes = semantic_json_bytes(normalized)
        issuance_id = secrets.token_hex(32)
        mac = hmac.new(
            signing_key, framed(core_bytes), hashlib.sha256
        ).hexdigest()
        proof = EngineCommitProof(
            construction_capability, issuance_id, mac
        )
        with registry_lock:
            registry[issuance_id] = (
                proof,
                core_bytes,
                mac,
                normalized,
            )
        return proof

    def consume(
        value: object,
        observed_value: (
            Callable[[], Mapping[str, object]]
            | Mapping[str, object]
        ),
    ) -> dict[str, object]:
        if type(value) is not EngineCommitProof:
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_INVALID",
                "schema-v4 persistence requires a live opaque proof",
            )
        try:
            issuance_id = object.__getattribute__(
                value, "_EngineCommitProof__issuance_id"
            )
            supplied_mac = object.__getattribute__(
                value, "_EngineCommitProof__mac"
            )
        except AttributeError as exc:
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_INVALID",
                "schema-v4 engine commit proof is incomplete",
            ) from exc
        if not isinstance(issuance_id, str):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_INVALID",
                "schema-v4 engine commit proof identity is invalid",
            )
        with registry_lock:
            registered = registry.get(issuance_id)
            if registered is None:
                raise TransitionEngineError(
                    "V4_ENGINE_COMMIT_PROOF_REPLAYED",
                    "schema-v4 engine commit proof is absent or consumed",
                )
            if registered[0] is not value:
                raise TransitionEngineError(
                    "V4_ENGINE_COMMIT_PROOF_INVALID",
                    "schema-v4 engine commit proof object is not registered",
                )
            # Atomic pop is the first operation for a real proof.  Every
            # binding failure and every exception after this point burns it.
            del registry[issuance_id]
        _proof, core_bytes, registered_mac, core = registered
        expected_mac = hmac.new(
            signing_key, framed(core_bytes), hashlib.sha256
        ).hexdigest()
        if (
            not isinstance(supplied_mac, str)
            or not hmac.compare_digest(registered_mac, expected_mac)
            or not hmac.compare_digest(supplied_mac, expected_mac)
        ):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_INVALID",
                "schema-v4 engine commit proof authentication failed",
            )
        observed = (
            observed_value()
            if callable(observed_value)
            else observed_value
        )
        if not isinstance(observed, Mapping):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_MISMATCH",
                "durable transaction binding must be an object",
            )
        if (
            core.get("contract")
            == "dev-flow-v4-engine-commit-proof/v1"
            and set(observed) != durable_observed_bindings
        ):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_MISMATCH",
                "durable transaction supplied an incomplete proof binding",
                details={
                    "missing": sorted(
                        durable_observed_bindings - set(observed)
                    ),
                    "unexpected": sorted(
                        set(observed) - durable_observed_bindings
                    ),
                },
            )
        for key, item in observed.items():
            if key not in core or not hmac.compare_digest(
                semantic_json_bytes(core[key]),
                semantic_json_bytes(item),
            ):
                raise TransitionEngineError(
                    "V4_ENGINE_COMMIT_PROOF_MISMATCH",
                    "durable transaction differs from its engine proof",
                    details={"binding": str(key)},
                )
        return copy.deepcopy(core)

    return EngineCommitProof, issue, consume


(
    EngineCommitProof,
    _engine_commit_proof_issue,
    _engine_commit_proof_consume,
) = _build_engine_commit_proof_broker()


def _pointer_segment(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def json_pointer_diff(
    before: object, after: object, pointer: str = ""
) -> tuple[str, ...]:
    """Return deterministic leaf/list JSON Pointer changes."""

    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changed: list[str] = []
        keys = sorted(
            set(before) | set(after),
            key=lambda item: str(item).encode("utf-8"),
        )
        for key in keys:
            child = f"{pointer}/{_pointer_segment(key)}"
            if key not in before or key not in after:
                changed.append(child)
                continue
            changed.extend(
                json_pointer_diff(before[key], after[key], child)
            )
        return tuple(changed)
    if isinstance(before, (list, tuple)) and isinstance(
        after, (list, tuple)
    ):
        if list(before) == list(after):
            return ()
        return (pointer or "/",)
    if before != after or type(before) is not type(after):
        return (pointer or "/",)
    return ()


def _path_is_within(path: str, allowed: str) -> bool:
    return path == allowed or path.startswith(allowed.rstrip("/") + "/")


def enforce_allowed_state_writes(
    changed_paths: Iterable[str],
    allowed_state_writes: Iterable[str],
) -> tuple[str, ...]:
    allowed = tuple(sorted(set(allowed_state_writes)))
    if any(
        not isinstance(path, str)
        or not path.startswith("/")
        or path == "/"
        for path in allowed
    ):
        raise TransitionEngineError(
            "EDGE_ALLOWED_WRITES_INVALID",
            "allowed state writes must be non-root JSON Pointers",
            details={"allowed_state_writes": list(allowed)},
        )
    for grant in allowed:
        for protected in _PROTECTED_STATE_PATHS:
            if _path_is_within(grant, protected) or _path_is_within(
                protected, grant
            ):
                raise TransitionEngineError(
                    "EDGE_PROTECTED_WRITE_GRANT",
                    "workflow data cannot grant writes to kernel fields",
                    details={
                        "allowed_path": grant,
                        "protected_path": protected,
                    },
                )
    changed = tuple(sorted(set(changed_paths)))
    unexpected = [
        path
        for path in changed
        if not any(_path_is_within(path, grant) for grant in allowed)
    ]
    if unexpected:
        raise TransitionEngineError(
            "REDUCER_WRITE_OUT_OF_SCOPE",
            "candidate state changed outside declared write paths",
            details={
                "unexpected_paths": unexpected,
                "allowed_state_writes": list(allowed),
            },
        )
    return changed


def _edge_trigger_action(edge: Mapping[str, object]) -> str | None:
    trigger = edge.get("trigger")
    if not isinstance(trigger, Mapping):
        return None
    action_id = trigger.get("id", trigger.get("action_id"))
    return action_id if isinstance(action_id, str) else None


def _transition_engine_edge_source(
    edge: Mapping[str, object],
) -> object:
    return edge.get("source", edge.get("from"))


def _transition_engine_edge_target(
    edge: Mapping[str, object],
) -> object:
    return edge.get("target", edge.get("to"))


def _transition_engine_edge_trigger(
    edge: Mapping[str, object],
) -> dict[str, object]:
    trigger = edge.get("trigger")
    if not isinstance(trigger, Mapping):
        return {}
    identifier = trigger.get("id", trigger.get("action_id"))
    kind = trigger.get("kind")
    if not isinstance(kind, str):
        kind = "action"
    return {"kind": kind, "id": identifier}


def _edge_contract_ids(edge: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in ("guards", "reducers"):
        values = edge.get(field, ())
        if isinstance(values, (list, tuple)):
            result[field] = list(values)
    for field in ("gate", "handler", "executor"):
        value = edge.get(field)
        if value is not None:
            result[field] = value
    return result


def _transition_engine_kernel_write_paths(
    edge: Mapping[str, object],
) -> tuple[str, ...]:
    result = {"/status"}
    invalidates = edge.get("kernel_invalidates", ())
    if isinstance(invalidates, (list, tuple)):
        result.update(
            item for item in invalidates if isinstance(item, str)
        )
    effects = edge.get("kernel_effects", ())
    if isinstance(effects, (list, tuple)):
        for effect in effects:
            if isinstance(effect, str):
                result.update(
                    _transition_engine_effect_write_paths.get(effect, ())
                )
    return tuple(sorted(result))


def _transition_engine_enforce_kernel_writes(
    changed_paths: Iterable[str],
    kernel_write_paths: Iterable[str],
) -> tuple[str, ...]:
    allowed = tuple(sorted(set(kernel_write_paths)))
    if any(
        not isinstance(path, str)
        or not path.startswith("/")
        or path == "/"
        for path in allowed
    ):
        raise TransitionEngineError(
            "KERNEL_WRITE_POLICY_INVALID",
            "kernel state write paths must be non-root JSON Pointers",
        )
    changed = tuple(sorted(set(changed_paths)))
    unexpected = [
        path
        for path in changed
        if not any(_path_is_within(path, grant) for grant in allowed)
    ]
    if unexpected:
        raise TransitionEngineError(
            "KERNEL_WRITE_OUT_OF_SCOPE",
            "kernel effect changed state outside its fixed authority",
            details={
                "unexpected_paths": unexpected,
                "kernel_write_paths": list(allowed),
            },
        )
    return changed


def _transition_engine_enforce_combined_writes(
    changed_paths: Iterable[str],
    reducer_write_paths: Iterable[str],
    kernel_write_paths: Iterable[str],
) -> tuple[str, ...]:
    reducer_allowed = tuple(sorted(set(reducer_write_paths)))
    # Validate graph grants even when only kernel-owned fields changed.
    enforce_allowed_state_writes((), reducer_allowed)
    kernel_allowed = tuple(sorted(set(kernel_write_paths)))
    changed = tuple(sorted(set(changed_paths)))
    unexpected = [
        path
        for path in changed
        if not any(
            _path_is_within(path, grant)
            for grant in (*reducer_allowed, *kernel_allowed)
        )
    ]
    if unexpected:
        raise TransitionEngineError(
            "TRANSITION_WRITE_OUT_OF_SCOPE",
            "transition changed state outside reducer and kernel authority",
            details={
                "unexpected_paths": unexpected,
                "allowed_state_writes": list(reducer_allowed),
                "kernel_write_paths": list(kernel_allowed),
            },
        )
    return changed


_transition_engine_kernel_operation_paths = MappingProxyType(
    {
        "increment-impact-generation": ("/impact_generation",),
        "increment-planning-generation": ("/planning_generation",),
        "increment-workspace-generation": ("/workspace",),
        "retire-current-workspaces": ("/repositories",),
    }
)


def _transition_engine_decode_pointer(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise TransitionEngineError(
            "KERNEL_STATE_DELTA_INVALID",
            "kernel state deltas require non-root JSON Pointers",
            details={"pointer": pointer},
        )
    return tuple(
        segment.replace("~1", "/").replace("~0", "~")
        for segment in pointer[1:].split("/")
    )


def _transition_engine_pointer_get(
    value: object, pointer: str
) -> tuple[bool, object]:
    current = value
    for segment in _transition_engine_decode_pointer(pointer):
        if isinstance(current, Mapping):
            if segment not in current:
                return False, None
            current = current[segment]
            continue
        if isinstance(current, (list, tuple)):
            if not segment.isdigit():
                return False, None
            index = int(segment)
            if index >= len(current):
                return False, None
            current = current[index]
            continue
        return False, None
    return True, current


def _transition_engine_pointer_parent(
    value: object,
    pointer: str,
    *,
    create: bool,
) -> tuple[object, str]:
    segments = _transition_engine_decode_pointer(pointer)
    current = value
    for segment in segments[:-1]:
        if isinstance(current, dict):
            child = current.get(segment)
            if child is None and create:
                child = {}
                current[segment] = child
            if not isinstance(child, (dict, list)):
                raise TransitionEngineError(
                    "KERNEL_STATE_DELTA_INVALID",
                    "kernel state delta traverses a non-container value",
                    details={"pointer": pointer, "segment": segment},
                )
            current = child
            continue
        if isinstance(current, list):
            if not segment.isdigit():
                raise TransitionEngineError(
                    "KERNEL_STATE_DELTA_INVALID",
                    "kernel state delta uses a non-numeric array segment",
                    details={"pointer": pointer, "segment": segment},
                )
            index = int(segment)
            if index >= len(current):
                raise TransitionEngineError(
                    "KERNEL_STATE_DELTA_INVALID",
                    "kernel state delta array index is out of range",
                    details={"pointer": pointer, "segment": segment},
                )
            child = current[index]
            if not isinstance(child, (dict, list)):
                raise TransitionEngineError(
                    "KERNEL_STATE_DELTA_INVALID",
                    "kernel state delta traverses a non-container value",
                    details={"pointer": pointer, "segment": segment},
                )
            current = child
            continue
        raise TransitionEngineError(
            "KERNEL_STATE_DELTA_INVALID",
            "kernel state delta traverses a non-container value",
            details={"pointer": pointer, "segment": segment},
        )
    return current, segments[-1]


def _transition_engine_pointer_set(
    value: dict[str, object], pointer: str, item: object
) -> None:
    parent, segment = _transition_engine_pointer_parent(
        value, pointer, create=True
    )
    copied = copy.deepcopy(_thaw_contract_value(item))
    if isinstance(parent, dict):
        parent[segment] = copied
        return
    if isinstance(parent, list) and segment.isdigit():
        index = int(segment)
        if index < len(parent):
            parent[index] = copied
            return
    raise TransitionEngineError(
        "KERNEL_STATE_DELTA_INVALID",
        "kernel state delta cannot set the requested JSON Pointer",
        details={"pointer": pointer},
    )


def _transition_engine_pointer_remove(
    value: dict[str, object], pointer: str
) -> None:
    parent, segment = _transition_engine_pointer_parent(
        value, pointer, create=False
    )
    if isinstance(parent, dict):
        parent.pop(segment, None)
        return
    if isinstance(parent, list) and segment.isdigit():
        index = int(segment)
        if index < len(parent):
            parent.pop(index)
        return
    raise TransitionEngineError(
        "KERNEL_STATE_DELTA_INVALID",
        "kernel state delta cannot remove the requested JSON Pointer",
        details={"pointer": pointer},
    )


def _transition_engine_normalize_kernel_delta(
    value: Mapping[str, object],
) -> dict[str, object]:
    unknown = sorted(set(value) - {"set", "remove", "operations"})
    if unknown:
        raise TransitionEngineError(
            "KERNEL_STATE_DELTA_INVALID",
            "kernel state delta contains unsupported fields",
            details={"fields": unknown},
        )
    set_values = value.get("set", {})
    remove_values = value.get("remove", ())
    operations = value.get("operations", ())
    if not isinstance(set_values, Mapping) or not isinstance(
        remove_values, (list, tuple)
    ) or not isinstance(operations, (list, tuple)):
        raise TransitionEngineError(
            "KERNEL_STATE_DELTA_INVALID",
            "kernel state delta set, remove, and operations have invalid types",
        )
    normalized_set: dict[str, object] = {}
    for pointer, item in set_values.items():
        _transition_engine_decode_pointer(pointer)
        normalized_set[pointer] = copy.deepcopy(_thaw_contract_value(item))
    normalized_remove: list[str] = []
    for pointer in remove_values:
        _transition_engine_decode_pointer(pointer)
        if pointer not in normalized_remove:
            normalized_remove.append(pointer)
    overlap = sorted(set(normalized_set) & set(normalized_remove))
    if overlap:
        raise TransitionEngineError(
            "KERNEL_STATE_DELTA_INVALID",
            "kernel state delta cannot set and remove the same path",
            details={"paths": overlap},
        )
    normalized_operations: list[str] = []
    for operation in operations:
        if (
            not isinstance(operation, str)
            or operation not in _transition_engine_kernel_operation_paths
        ):
            raise TransitionEngineError(
                "KERNEL_OPERATION_UNSUPPORTED",
                "reducer requested an unsupported kernel operation",
                details={"operation": operation},
            )
        if operation not in normalized_operations:
            normalized_operations.append(operation)
    return {
        "set": normalized_set,
        "remove": normalized_remove,
        "operations": normalized_operations,
    }


def _transition_engine_merge_kernel_delta(
    current: Mapping[str, object],
    proposed: Mapping[str, object],
) -> dict[str, object]:
    left = _transition_engine_normalize_kernel_delta(current)
    right = _transition_engine_normalize_kernel_delta(proposed)
    set_values = dict(left["set"])
    remove_values = list(left["remove"])
    for pointer, item in right["set"].items():
        if pointer in remove_values:
            raise TransitionEngineError(
                "KERNEL_STATE_DELTA_CONFLICT",
                "reducers requested conflicting kernel changes",
                details={"pointer": pointer},
            )
        if pointer in set_values and set_values[pointer] != item:
            raise TransitionEngineError(
                "KERNEL_STATE_DELTA_CONFLICT",
                "reducers requested different values for one kernel path",
                details={"pointer": pointer},
            )
        set_values[pointer] = item
    for pointer in right["remove"]:
        if pointer in set_values:
            raise TransitionEngineError(
                "KERNEL_STATE_DELTA_CONFLICT",
                "reducers requested conflicting kernel changes",
                details={"pointer": pointer},
            )
        if pointer not in remove_values:
            remove_values.append(pointer)
    operations = list(left["operations"])
    for operation in right["operations"]:
        if operation not in operations:
            operations.append(operation)
    return {
        "set": set_values,
        "remove": remove_values,
        "operations": operations,
    }


def _transition_engine_validate_kernel_delta_scope(
    delta: Mapping[str, object],
    edge: Mapping[str, object],
) -> dict[str, object]:
    normalized = _transition_engine_normalize_kernel_delta(delta)
    allowed = _transition_engine_kernel_write_paths(edge)
    target = _transition_engine_edge_target(edge)
    status_value = normalized["set"].pop("/status", None)
    if status_value is not None and status_value != target:
        raise TransitionEngineError(
            "KERNEL_STATUS_WRITE_FORBIDDEN",
            "a reducer cannot propose a status other than the selected edge target",
            details={"proposed": status_value, "target": target},
        )
    if "/status" in normalized["remove"]:
        raise TransitionEngineError(
            "KERNEL_STATUS_WRITE_FORBIDDEN",
            "a reducer cannot remove task status",
        )
    changed_paths = tuple(
        sorted({*normalized["set"], *normalized["remove"]})
    )
    _transition_engine_enforce_kernel_writes(changed_paths, allowed)
    for operation in normalized["operations"]:
        required = _transition_engine_kernel_operation_paths[operation]
        _transition_engine_enforce_kernel_writes(required, allowed)
    return normalized


def _transition_engine_apply_kernel_operations(
    candidate: dict[str, object],
    operations: Sequence[str],
    action_parameters: Mapping[str, object],
) -> None:
    for operation in operations:
        if operation == "increment-impact-generation":
            candidate["impact_generation"] = int(
                candidate.get("impact_generation", 0)
            ) + 1
            continue
        if operation == "increment-planning-generation":
            candidate["planning_generation"] = int(
                candidate.get("planning_generation", 0)
            ) + 1
            continue
        if operation == "retire-current-workspaces":
            reassessed_at = action_parameters.get("reassessed_at")
            reason = action_parameters.get("note")
            repositories = candidate.get("repositories")
            if not isinstance(repositories, list):
                raise TransitionEngineError(
                    "KERNEL_OPERATION_INVALID",
                    "workspace retirement requires repository state",
                )
            for repository in repositories:
                if not isinstance(repository, dict):
                    raise TransitionEngineError(
                        "KERNEL_OPERATION_INVALID",
                        "workspace retirement found invalid repository state",
                    )
                previous_workspace = repository.get("workspace")
                if previous_workspace:
                    history = repository.setdefault("workspace_history", [])
                    if not isinstance(history, list):
                        raise TransitionEngineError(
                            "KERNEL_OPERATION_INVALID",
                            "workspace history must be an array",
                        )
                    history.append(
                        {
                            **copy.deepcopy(previous_workspace),
                            "workspace_index": copy.deepcopy(
                                repository.get("workspace_index")
                            ),
                            "retired_at": reassessed_at,
                            "retired_reason": reason,
                        }
                    )
                repository["workspace"] = None
                repository["workspace_index"] = None
            continue
        if operation == "increment-workspace-generation":
            previous = candidate.get("workspace")
            previous_generation = (
                int(previous.get("generation", 0))
                if isinstance(previous, Mapping)
                else 0
            )
            candidate["workspace"] = {
                "strategy": "worktree",
                "ready": False,
                "generation": previous_generation + 1,
                "plan": None,
                "reassessed_at": action_parameters.get("reassessed_at"),
            }
            continue
        raise TransitionEngineError(
            "KERNEL_OPERATION_UNSUPPORTED",
            "reducer requested an unsupported kernel operation",
            details={"operation": operation},
        )


def _transition_engine_apply_kernel_delta(
    candidate: Mapping[str, object],
    delta: Mapping[str, object],
    edge: Mapping[str, object],
    action_parameters: Mapping[str, object],
) -> dict[str, object]:
    normalized = _transition_engine_validate_kernel_delta_scope(delta, edge)
    result = copy.deepcopy(_thaw_contract_value(candidate))
    if not isinstance(result, dict):
        raise TransitionEngineError(
            "KERNEL_STATE_DELTA_INVALID",
            "kernel state delta requires an object candidate",
        )
    for pointer, item in normalized["set"].items():
        _transition_engine_pointer_set(result, pointer, item)
    for pointer in sorted(
        normalized["remove"],
        key=lambda item: (item.count("/"), item),
        reverse=True,
    ):
        _transition_engine_pointer_remove(result, pointer)
    _transition_engine_apply_kernel_operations(
        result, normalized["operations"], action_parameters
    )
    return result


def _contract_reference_id(
    value: object, *, expected_registry: str
) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, Mapping):
        registry = value.get("registry")
        identifier = value.get("id")
        version = value.get("version")
        if (
            registry == expected_registry
            and isinstance(identifier, str)
            and identifier
            and isinstance(version, str)
            and version
        ):
            return identifier
    raise TransitionEngineError(
        "WORKFLOW_CONTRACT_REFERENCE_INVALID",
        "edge contract reference is malformed or uses the wrong registry",
        details={
            "expected_registry": expected_registry,
            "reference": _thaw_contract_value(value),
        },
    )


def _transition_engine_contract_reference(
    value: object,
    *,
    expected_registry: str,
    schema_v4: bool,
) -> tuple[str, str | None]:
    identifier = _contract_reference_id(
        value, expected_registry=expected_registry
    )
    if isinstance(value, Mapping):
        version = value.get("version")
        if isinstance(version, str) and version:
            return identifier, version
    if schema_v4:
        raise TransitionEngineError(
            "WORKFLOW_CONTRACT_UNSUPPORTED",
            "schema-v4 executable references require an exact version",
            details={
                "registry": expected_registry,
                "identifier": identifier,
                "version": None,
                "compatibility_blocker": True,
            },
        )
    return identifier, None


def _transition_engine_contract_key(
    registry: str, identifier: str
) -> str:
    return f"{registry}:{identifier}"


def _transition_engine_context_mapping(
    context: KernelTransitionContext | Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if context is None:
        return None
    if isinstance(context, KernelTransitionContext):
        return MappingProxyType(
            {
                "contract": context.contract,
                "task_id": context.task_id,
                "workflow_ref": context.workflow_ref,
                "task_lock_held": context.task_lock_held,
                "workspace_lock_held": context.workspace_lock_held,
                "ownership_lock_held": context.ownership_lock_held,
                "evidence_sha256": context.evidence_sha256,
                "evidence_authentic": context.evidence_authentic,
                "evidence_current": context.evidence_current,
                "approval_current": context.approval_current,
                "approval_intent_id": context.approval_intent_id,
                "supported_node_contracts": (
                    context.supported_node_contracts
                ),
                "supported_contract_versions": (
                    context.supported_contract_versions
                ),
                "authorized_effects": context.authorized_effects,
                "requested_effect_paths": (
                    context.requested_effect_paths
                ),
                "authorized_paths": context.authorized_paths,
            }
        )
    if not isinstance(context, Mapping):
        raise TransitionEngineError(
            "KERNEL_CONTEXT_INVALID",
            "kernel transition context must be an immutable proof object",
        )
    frozen = _freeze_contract_value(
        copy.deepcopy(dict(context)), "$kernel_context"
    )
    if not isinstance(frozen, Mapping):
        raise TransitionEngineError(
            "KERNEL_CONTEXT_INVALID",
            "kernel transition context must be an object",
        )
    if frozen.get("contract") != _transition_engine_kernel_context_contract:
        raise TransitionEngineError(
            "KERNEL_CONTEXT_UNSUPPORTED",
            "kernel transition context contract is unsupported",
            details={
                "contract": frozen.get("contract"),
                "supported": [_transition_engine_kernel_context_contract],
            },
        )
    return frozen


def _transition_engine_context_versions(
    context: Mapping[str, object],
    field: str,
    key: str,
) -> tuple[str, ...]:
    values_by_key = context.get(field)
    if not isinstance(values_by_key, Mapping):
        return ()
    values = values_by_key.get(key, ())
    if isinstance(values, str):
        return (values,)
    if isinstance(values, (list, tuple)):
        return tuple(
            item for item in values if isinstance(item, str)
        )
    return ()


def _transition_engine_graph_node(
    graph: Mapping[str, object], node_id: str
) -> Mapping[str, object] | None:
    nodes = graph.get("nodes")
    if isinstance(nodes, Mapping):
        node = nodes.get(node_id)
        return node if isinstance(node, Mapping) else None
    if isinstance(nodes, (list, tuple)):
        for item in nodes:
            if isinstance(item, Mapping) and item.get("id") == node_id:
                return item
    return None


def _transition_engine_require_supported_node(
    graph: Mapping[str, object],
    context: Mapping[str, object],
    node_id: str,
) -> None:
    node = _transition_engine_graph_node(graph, node_id)
    if node is None:
        raise TransitionEngineError(
            "WORKFLOW_NODE_CONTRACT_UNSUPPORTED",
            "schema-v4 transition node is unavailable to the engine",
            details={
                "node_id": node_id,
                "compatibility_blocker": True,
            },
        )
    kind = node.get("kind")
    version = node.get(
        "contract_version", node.get("version", "v1")
    )
    if (
        not isinstance(kind, str)
        or not isinstance(version, str)
        or version
        not in _transition_engine_context_versions(
            context, "supported_node_contracts", kind
        )
    ):
        raise TransitionEngineError(
            "WORKFLOW_NODE_CONTRACT_UNSUPPORTED",
            "workflow node kind or contract version is unsupported",
            details={
                "node_id": node_id,
                "kind": kind,
                "version": version,
                "compatibility_blocker": True,
            },
        )


def _transition_engine_edge_contract_references(
    edge: Mapping[str, object],
) -> tuple[tuple[str, object], ...]:
    references: list[tuple[str, object]] = []
    for field, registry in (
        ("guards", "guards"),
        ("reducers", "reducers"),
    ):
        values = edge.get(field, ())
        if not isinstance(values, (list, tuple)):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID",
                f"edge {field} must be an array",
                details={"edge_id": edge.get("id")},
            )
        references.extend((registry, item) for item in values)
    for field, registry in (
        ("gate", "gates"),
        ("handler", "executors"),
        ("executor", "executors"),
    ):
        value = edge.get(field)
        if value is not None:
            references.append((registry, value))
    return tuple(references)


def _transition_engine_require_supported_contracts(
    edge: Mapping[str, object],
    context: Mapping[str, object],
) -> None:
    for registry, reference in (
        _transition_engine_edge_contract_references(edge)
    ):
        identifier, version = _transition_engine_contract_reference(
            reference,
            expected_registry=registry,
            schema_v4=True,
        )
        key = _transition_engine_contract_key(registry, identifier)
        supported = _transition_engine_context_versions(
            context, "supported_contract_versions", key
        )
        if version not in supported:
            raise TransitionEngineError(
                "WORKFLOW_CONTRACT_UNSUPPORTED",
                "workflow executable contract is unavailable or unsupported",
                details={
                    "registry": registry,
                    "identifier": identifier,
                    "version": version,
                    "supported_versions": list(supported),
                    "compatibility_blocker": True,
                },
            )


def _transition_engine_effect_requires_path(effect: str) -> bool:
    lowered = effect.lower()
    return any(
        marker in lowered
        for marker in _transition_engine_path_effect_markers
    )


def _transition_engine_path_is_authorized(
    path: str, authorized: str
) -> bool:
    if "\x00" in path or "\x00" in authorized:
        return False
    normalized_path = path.replace("\\", "/").rstrip("/")
    normalized_authorized = authorized.replace("\\", "/").rstrip("/")
    if not normalized_path or not normalized_authorized:
        return False
    path_parts = normalized_path.split("/")
    if ".." in path_parts or ".." in normalized_authorized.split("/"):
        return False
    return (
        normalized_path == normalized_authorized
        or normalized_path.startswith(normalized_authorized + "/")
    )


def _transition_engine_extract_paths(value: object) -> tuple[str, ...]:
    paths: set[str] = set()

    def visit(item: object, field: str | None = None) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, str(key))
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child, field)
            return
        if (
            isinstance(item, str)
            and field is not None
            and (
                field == "path"
                or field == "paths"
                or field.endswith("_path")
                or field.endswith("_paths")
                or field in {"worktree", "workspace"}
            )
        ):
            paths.add(item)

    visit(value)
    return tuple(sorted(paths))


def _transition_engine_require_v4_kernel_context(
    graph: Mapping[str, object],
    state: Mapping[str, object],
    edge: Mapping[str, object],
    evidence: Mapping[str, object],
    action_parameters: Mapping[str, object],
    action_outcome: ActionOutcome | None,
    context_value: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if context_value is None:
        raise TransitionEngineError(
            "KERNEL_CONTEXT_REQUIRED",
            "schema-v4 transition evaluation requires kernel proof context",
            details={"schema_version": 4},
        )
    if context_value.get("task_lock_held") is not True:
        raise TransitionEngineError(
            "KERNEL_TASK_LOCK_REQUIRED",
            "schema-v4 evaluation requires the current task lock",
        )
    task_id = state.get("task_id")
    if (
        not isinstance(task_id, str)
        or context_value.get("task_id") != task_id
    ):
        raise TransitionEngineError(
            "KERNEL_TASK_IDENTITY_MISMATCH",
            "kernel context does not identify the current task",
            details={
                "state_task_id": task_id,
                "context_task_id": context_value.get("task_id"),
            },
        )
    workflow_ref = state.get("workflow_ref")
    context_ref = context_value.get("workflow_ref")
    if (
        not isinstance(workflow_ref, Mapping)
        or not isinstance(context_ref, Mapping)
        or _canonical_json_bytes(workflow_ref)
        != _canonical_json_bytes(context_ref)
    ):
        raise TransitionEngineError(
            "KERNEL_WORKFLOW_IDENTITY_MISMATCH",
            "kernel context does not bind the exact pinned workflow",
        )
    graph_identity = {
        "id": graph.get("workflow_id"),
        "version": graph.get("workflow_version"),
        "schema": graph.get("schema"),
    }
    expected_identity = {
        "id": workflow_ref.get("id"),
        "version": workflow_ref.get("version"),
        "schema": workflow_ref.get("schema"),
    }
    for digest_field in ("graph_sha256", "bundle_sha256"):
        if graph.get(digest_field) is not None:
            graph_identity[digest_field] = graph.get(digest_field)
            expected_identity[digest_field] = workflow_ref.get(
                digest_field
            )
    if (
        graph_identity != expected_identity
        or graph_identity["schema"]
        not in _transition_engine_supported_workflow_schemas
    ):
        raise TransitionEngineError(
            "KERNEL_WORKFLOW_IDENTITY_MISMATCH",
            "engine graph does not match the exact pinned workflow",
            details={
                "graph_identity": graph_identity,
                "pinned_identity": expected_identity,
            },
        )
    if context_value.get("evidence_authentic") is not True:
        raise TransitionEngineError(
            "KERNEL_EVIDENCE_AUTHENTICITY_REQUIRED",
            "transition evidence is not proven authentic",
        )
    if context_value.get("evidence_current") is not True:
        raise TransitionEngineError(
            "KERNEL_EVIDENCE_STALE",
            "transition evidence is not proven current",
        )
    actual_evidence_sha256 = _sha256_contract(evidence)
    if context_value.get("evidence_sha256") != actual_evidence_sha256:
        raise TransitionEngineError(
            "KERNEL_EVIDENCE_IDENTITY_MISMATCH",
            "kernel evidence proof does not bind the evaluated evidence",
            details={
                "expected_sha256": context_value.get("evidence_sha256"),
                "actual_sha256": actual_evidence_sha256,
            },
        )
    source = _transition_engine_edge_source(edge)
    target = _transition_engine_edge_target(edge)
    if not isinstance(source, str) or not isinstance(target, str):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "selected edge must identify source and target nodes",
            details={"edge_id": edge.get("id")},
        )
    _transition_engine_require_supported_node(
        graph, context_value, source
    )
    _transition_engine_require_supported_node(
        graph, context_value, target
    )
    _transition_engine_require_supported_contracts(
        edge, context_value
    )

    effects = edge.get("side_effects", ())
    if not isinstance(effects, (list, tuple)):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "edge side effects must be an array",
            details={"edge_id": edge.get("id")},
        )
    effect_values = tuple(
        item for item in effects if isinstance(item, str)
    )
    if len(effect_values) != len(effects):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "edge side effects must use stable string identities",
            details={"edge_id": edge.get("id")},
        )
    authorized_effects = context_value.get("authorized_effects", ())
    if not isinstance(authorized_effects, (list, tuple)):
        authorized_effects = ()
    unauthorized_effects = sorted(
        set(effect_values) - set(authorized_effects)
    )
    if unauthorized_effects:
        raise TransitionEngineError(
            "KERNEL_EFFECT_UNAUTHORIZED",
            "workflow graph cannot broaden kernel effect authority",
            details={"effects": unauthorized_effects},
        )
    allowed_writes = edge.get("allowed_state_writes", ())
    workspace_sensitive = any(
        _transition_engine_effect_requires_path(effect)
        for effect in effect_values
    ) or any(
        isinstance(path, str)
        and (
            _path_is_within(path, "/workspace")
            or _path_is_within(path, "/repositories")
        )
        for path in (
            allowed_writes
            if isinstance(allowed_writes, (list, tuple))
            else ()
        )
    )
    ownership_sensitive = any(
        any(
            marker in effect.lower()
            for marker in ("filesystem", "git", "repository", "workspace")
        )
        for effect in effect_values
    )
    if (
        workspace_sensitive
        and context_value.get("workspace_lock_held") is not True
    ):
        raise TransitionEngineError(
            "KERNEL_WORKSPACE_LOCK_REQUIRED",
            "transition effects require the workspace registry lock",
        )
    if (
        ownership_sensitive
        and context_value.get("ownership_lock_held") is not True
    ):
        raise TransitionEngineError(
            "KERNEL_OWNERSHIP_LOCK_REQUIRED",
            "transition effects require a current ownership lock",
        )

    requested_paths = set(
        item
        for item in context_value.get("requested_effect_paths", ())
        if isinstance(item, str)
    )
    requested_paths.update(
        _transition_engine_extract_paths(action_parameters)
    )
    if action_outcome is not None:
        requested_paths.update(
            _transition_engine_extract_paths(
                action_outcome.external_postconditions
            )
        )
    if (
        any(
            _transition_engine_effect_requires_path(effect)
            for effect in effect_values
        )
        and not requested_paths
    ):
        raise TransitionEngineError(
            "KERNEL_EFFECT_PATH_REQUIRED",
            "filesystem and Git effects require exact requested paths",
            details={"effects": sorted(effect_values)},
        )
    authorized_paths = tuple(
        item
        for item in context_value.get("authorized_paths", ())
        if isinstance(item, str)
    )
    unauthorized_paths = sorted(
        path
        for path in requested_paths
        if not any(
            _transition_engine_path_is_authorized(path, root)
            for root in authorized_paths
        )
    )
    if unauthorized_paths:
        raise TransitionEngineError(
            "KERNEL_EFFECT_PATH_UNAUTHORIZED",
            "effect path is outside controller-authorized scope",
            details={"paths": unauthorized_paths},
        )
    return context_value


def _transition_engine_require_current_approval(
    edge: Mapping[str, object],
    intent: Mapping[str, object],
    approval_outcome: ApprovalOutcome | None,
    context_value: Mapping[str, object] | None,
    *,
    preview: bool,
) -> None:
    if preview:
        return
    if edge.get("gate") is None:
        return
    if context_value is None or context_value.get(
        "approval_current"
    ) is not True:
        raise TransitionEngineError(
            "KERNEL_APPROVAL_STALE",
            "transition approval is not proven current",
        )
    intent_id = intent.get("intent_id")
    if (
        not isinstance(intent_id, str)
        or context_value.get("approval_intent_id") != intent_id
    ):
        raise TransitionEngineError(
            "KERNEL_APPROVAL_INTENT_MISMATCH",
            "current approval is not bound to this transition intent",
            details={
                "approval_intent_id": context_value.get(
                    "approval_intent_id"
                ),
                "transition_intent_id": intent_id,
            },
        )
    if approval_outcome is not None:
        approval_intent_id = approval_outcome.approval.get("intent_id")
        if approval_intent_id != intent_id:
            raise TransitionEngineError(
                "KERNEL_APPROVAL_INTENT_MISMATCH",
                "approval outcome is not bound to this transition intent",
                details={
                    "approval_intent_id": approval_intent_id,
                    "transition_intent_id": intent_id,
                },
            )


def _transition_engine_require_exact_approval_outcome(
    edge: Mapping[str, object],
    approval_outcome: ApprovalOutcome | None,
) -> None:
    """Require one typed approval bound to the exact gated schema-v4 edge."""

    gate = edge.get("gate")
    edge_id = edge.get("id")
    if gate is None:
        if approval_outcome is not None:
            raise TransitionEngineError(
                "APPROVAL_OUTCOME_MISMATCH",
                "an ungated transition cannot carry an approval outcome",
                details={
                    "edge_id": edge_id,
                    "actual_gate_id": approval_outcome.gate_id,
                    "actual_edge_id": (
                        approval_outcome.proposed_edge_id
                    ),
                },
            )
        return
    if not isinstance(gate, Mapping) or not isinstance(
        gate.get("id"), str
    ):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "schema-v4 gated edge has no exact gate identity",
            details={"edge_id": edge_id},
        )
    if approval_outcome is None:
        raise TransitionEngineError(
            "APPROVAL_OUTCOME_REQUIRED",
            "schema-v4 gated transition requires a typed approval outcome",
            details={
                "edge_id": edge_id,
                "gate_id": gate.get("id"),
            },
        )
    if (
        approval_outcome.gate_id != gate.get("id")
        or approval_outcome.proposed_edge_id != edge_id
    ):
        raise TransitionEngineError(
            "APPROVAL_OUTCOME_MISMATCH",
            "approval outcome does not bind the selected gate and edge",
            details={
                "expected_gate_id": gate.get("id"),
                "actual_gate_id": approval_outcome.gate_id,
                "expected_edge_id": edge_id,
                "actual_edge_id": approval_outcome.proposed_edge_id,
            },
        )


def _transition_engine_resolve_handler(
    resolver: Callable[[str, str | None], Callable[..., object]],
    identifier: str,
    *,
    registry: str,
    version: str | None,
) -> Callable[..., object]:
    try:
        resolved = resolver(identifier, version)
    except KeyError as exc:
        raise TransitionEngineError(
            "WORKFLOW_CONTRACT_UNAVAILABLE",
            "pinned workflow contract is unavailable",
            details={
                "registry": registry,
                "identifier": identifier,
                "version": version,
                "compatibility_blocker": True,
            },
        ) from exc
    except Exception as exc:
        if getattr(exc, "code", None) not in (
            _transition_engine_missing_contract_codes
        ):
            raise
        raise TransitionEngineError(
            "WORKFLOW_CONTRACT_UNAVAILABLE",
            "pinned workflow contract is unavailable",
            details={
                "registry": registry,
                "identifier": identifier,
                "version": version,
                "compatibility_blocker": True,
            },
        ) from exc
    if not callable(resolved):
        raise TransitionEngineError(
            "WORKFLOW_CONTRACT_UNAVAILABLE",
            "pinned workflow contract has no callable implementation",
            details={
                "registry": registry,
                "identifier": identifier,
                "version": version,
                "compatibility_blocker": True,
            },
        )
    return resolved


class TransitionEngine:
    """Resolve and evaluate one pinned workflow edge without committing it."""

    def __init__(
        self,
        graph: Mapping[str, object],
        *,
        guard_resolver: Callable[
            [str, str | None], Callable[..., GuardResult]
        ],
        reducer_resolver: Callable[
            [str, str | None], Callable[..., ReducerResult]
        ],
        invariant_checks: Sequence[
            Callable[[Mapping[str, object], Mapping[str, object]], None]
        ] = (),
        kernel_effect_applier: Callable[
            [
                Mapping[str, object],
                Mapping[str, object],
                ActionOutcome | None,
                ApprovalOutcome | None,
                Mapping[str, object],
            ],
            KernelEffectResult,
        ]
        | None = None,
    ) -> None:
        frozen_graph = _freeze_contract_value(dict(graph), "$graph")
        if not isinstance(frozen_graph, Mapping):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID", "workflow graph must be an object"
            )
        self.graph = frozen_graph
        edges = self.graph.get("edges")
        if not isinstance(edges, tuple):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID",
                "workflow graph must contain an edge array",
            )
        self._edges = tuple(
            item for item in edges if isinstance(item, Mapping)
        )
        if len(self._edges) != len(edges):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID", "every graph edge must be an object"
            )
        self._guard_resolver = guard_resolver
        self._reducer_resolver = reducer_resolver
        self._invariant_checks = tuple(invariant_checks)
        self._kernel_effect_applier = kernel_effect_applier

    def resolve_edge(
        self,
        source: str,
        action_id: str,
        *,
        edge_id: str | None = None,
    ) -> Mapping[str, object]:
        if source in _TERMINAL_NODE_IDS:
            raise TransitionEngineError(
                "TERMINAL_TRANSITION_FORBIDDEN",
                "terminal workflow nodes cannot have outgoing movement",
                details={"source": source},
            )
        candidates = [
            edge
            for edge in self._edges
            if _transition_engine_edge_source(edge) == source
            and _edge_trigger_action(edge) == action_id
        ]
        if edge_id is not None:
            selected = [
                edge for edge in candidates if edge.get("id") == edge_id
            ]
            if len(selected) != 1:
                raise TransitionEngineError(
                    "EDGE_NOT_AVAILABLE",
                    "selected edge is not available for this source and action",
                    details={
                        "source": source,
                        "action_id": action_id,
                        "edge_id": edge_id,
                    },
                )
            return selected[0]
        if not candidates:
            raise TransitionEngineError(
                "EDGE_NOT_AVAILABLE",
                "no workflow edge is available for this source and action",
                details={"source": source, "action_id": action_id},
            )
        priorities: list[tuple[int, Mapping[str, object]]] = []
        for candidate in candidates:
            priority = candidate.get("priority", 0)
            if isinstance(priority, bool) or not isinstance(priority, int):
                raise TransitionEngineError(
                    "EDGE_PRIORITY_INVALID",
                    "edge priority must be an integer",
                    details={"edge_id": candidate.get("id")},
                )
            priorities.append((priority, candidate))
        highest = max(item[0] for item in priorities)
        winners = [edge for priority, edge in priorities if priority == highest]
        if len(winners) != 1:
            raise TransitionEngineError(
                "EDGE_SELECTION_AMBIGUOUS",
                "multiple eligible edges have equal precedence",
                details={
                    "source": source,
                    "action_id": action_id,
                    "priority": highest,
                    "edge_ids": sorted(str(edge.get("id")) for edge in winners),
                },
            )
        return winners[0]

    def build_intent(
        self,
        state: Mapping[str, object],
        edge: Mapping[str, object],
        *,
        action_id: str,
        action_parameters: Mapping[str, object],
        evidence: Mapping[str, object],
    ) -> dict[str, object]:
        workflow_ref = state.get("workflow_ref")
        if not isinstance(workflow_ref, Mapping):
            raise TransitionEngineError(
                "WORKFLOW_REF_REQUIRED",
                "V4 transition requires an exact task workflow reference",
            )
        evidence_sha256 = _sha256_contract(evidence)
        payload = {
            "contract": "dev-flow-transition-intent/v1",
            "task_id": state.get("task_id"),
            "base_revision": state.get("revision"),
            "workflow_ref": workflow_ref,
            "edge_id": edge.get("id"),
            "source": _transition_engine_edge_source(edge),
            "target": _transition_engine_edge_target(edge),
            "trigger": _transition_engine_edge_trigger(edge),
            "handlers": _edge_contract_ids(edge),
            "action_id": action_id,
            "action_parameters": action_parameters,
            "evidence_sha256": evidence_sha256,
            "confirmation_mode": edge.get("confirmation"),
            "side_effects": edge.get("side_effects", ()),
        }
        digest = _sha256_contract(payload)
        return {
            **payload,
            "intent_id": f"dev-flow-transition-intent/v1:{digest}",
        }

    def evaluate(
        self,
        state: Mapping[str, object],
        *,
        expected_revision: int,
        action_id: str,
        action_parameters: Mapping[str, object],
        evidence: Mapping[str, object],
        edge_id: str | None = None,
        action_outcome: ActionOutcome | None = None,
        approval_outcome: ApprovalOutcome | None = None,
        confirm_intent: str | None = None,
        preview: bool = False,
        guard_capability: object = None,
        reducer_capability: object = None,
        kernel_context: (
            KernelTransitionContext | Mapping[str, object] | None
        ) = None,
    ) -> TransitionEvaluation:
        revision = state.get("revision")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or revision != expected_revision
        ):
            raise TransitionEngineError(
                "REVISION_CONFLICT",
                "expected revision does not match the committed task",
                details={
                    "expected_revision": expected_revision,
                    "actual_revision": revision,
                },
            )
        source = state.get("status")
        if not isinstance(source, str):
            raise TransitionEngineError(
                "TASK_STATE_INVALID", "task status must be a string"
            )
        if (
            state.get("schema_version") == V4_TASK_SCHEMA_VERSION
            and approval_outcome is not None
            and type(approval_outcome) is not ApprovalOutcome
        ):
            raise TransitionEngineError(
                "APPROVAL_OUTCOME_INVALID",
                (
                    "schema-v4 approval input must use the exact "
                    "ApprovalOutcome contract"
                ),
            )
        selected_edge_id = edge_id
        if action_outcome is not None:
            if action_outcome.action_id != action_id:
                raise TransitionEngineError(
                    "ACTION_OUTCOME_MISMATCH",
                    "action outcome identity does not match the request",
                )
            selected_edge_id = action_outcome.proposed_edge_id
        if approval_outcome is not None:
            if (
                selected_edge_id is not None
                and selected_edge_id
                != approval_outcome.proposed_edge_id
            ):
                raise TransitionEngineError(
                    "APPROVAL_OUTCOME_MISMATCH",
                    "action and approval outcomes propose different edges",
                )
            selected_edge_id = approval_outcome.proposed_edge_id
        edge = self.resolve_edge(
            source, action_id, edge_id=selected_edge_id
        )
        target = _transition_engine_edge_target(edge)
        if not isinstance(target, str):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID",
                "selected edge has no target node",
                details={"edge_id": edge.get("id")},
            )
        confirmation = edge.get("confirmation")
        if (
            target in _TERMINAL_NODE_IDS
            and confirmation != "explicit"
        ):
            raise TransitionEngineError(
                "TERMINAL_CONFIRMATION_REQUIRED",
                "terminal movement must always be explicitly confirmed",
                details={"edge_id": edge.get("id"), "target": target},
            )

        schema_v4 = state.get("schema_version") == V4_TASK_SCHEMA_VERSION
        if schema_v4:
            _transition_engine_require_exact_approval_outcome(
                edge, approval_outcome
            )
        context_value = _transition_engine_context_mapping(
            kernel_context
        )
        if schema_v4:
            context_value = (
                _transition_engine_require_v4_kernel_context(
                    self.graph,
                    state,
                    edge,
                    evidence,
                    action_parameters,
                    action_outcome,
                    context_value,
                )
            )

        immutable_state = _freeze_contract_value(
            copy.deepcopy(dict(state)), "$guard/state"
        )
        immutable_evidence = _freeze_contract_value(
            copy.deepcopy(dict(evidence)), "$guard/evidence"
        )
        guard_results: list[tuple[str, GuardResult]] = []
        combined_guard_evidence: dict[str, object] = {}
        guards = edge.get("guards", ())
        if not isinstance(guards, tuple):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID",
                "edge guards must be an array",
                details={"edge_id": edge.get("id")},
        )
        for guard_reference in guards:
            guard_id, guard_version = (
                _transition_engine_contract_reference(
                    guard_reference,
                    expected_registry="guards",
                    schema_v4=schema_v4,
                )
            )
            evaluator = _transition_engine_resolve_handler(
                self._guard_resolver,
                guard_id,
                registry="guards",
                version=guard_version,
            )
            result = evaluator(
                immutable_state,
                immutable_evidence,
                guard_capability,
            )
            if not isinstance(result, GuardResult):
                raise TransitionEngineError(
                    "GUARD_RESULT_INVALID",
                    "guard did not return a typed GuardResult",
                    details={"guard_id": guard_id},
                )
            guard_results.append((guard_id, result))
            combined_guard_evidence[guard_id] = result.evidence
            if not result.passed:
                raise TransitionEngineError(
                    "TRANSITION_GUARD_BLOCKED",
                    "a current transition guard rejected the edge",
                    details={
                        "edge_id": edge.get("id"),
                        "guard_id": guard_id,
                        "blockers": [
                            _thaw_contract_value(item)
                            for item in result.blockers
                        ],
                    },
                )

        intent_evidence: dict[str, object] = {
            "request": evidence,
            "guards": combined_guard_evidence,
        }
        if action_outcome is not None:
            intent_evidence["action_records"] = (
                action_outcome.evidence_records
            )
        if (
            approval_outcome is not None
            and approval_outcome.evidence_records
        ):
            intent_evidence["approval_records"] = (
                approval_outcome.evidence_records
            )
        if approval_outcome is not None:
            # Bind the real, validated approval material into the intent while
            # excluding only the intent link itself.  This keeps preview and
            # apply identities stable: apply adds the freshly computed
            # ``intent_id`` to the outcome after preview, but every other
            # approval field remains part of the canonical evidence digest.
            approval_binding = _thaw_contract_value(
                approval_outcome.approval
            )
            if not isinstance(approval_binding, dict):
                raise TransitionEngineError(
                    "APPROVAL_OUTCOME_INVALID",
                    "approval outcome record must be an object",
                )
            approval_binding.pop("intent_id", None)
            intent_evidence["approval"] = approval_binding
        intent = self.build_intent(
            state,
            edge,
            action_id=action_id,
            action_parameters=action_parameters,
            evidence=intent_evidence,
        )
        if schema_v4:
            _transition_engine_require_current_approval(
                edge,
                intent,
                approval_outcome,
                context_value,
                preview=preview,
            )
        if not preview and confirmation == "explicit":
            if (
                not isinstance(confirm_intent, str)
                or not secrets.compare_digest(
                    intent["intent_id"], confirm_intent
                )
            ):
                raise TransitionEngineError(
                    "TRANSITION_INTENT_REQUIRED"
                    if not confirm_intent
                    else "INTENT_STALE",
                    "explicit movement requires the current transition intent",
                    details={"preview": intent},
                )
        elif (
            confirm_intent is not None
            and not secrets.compare_digest(
                intent["intent_id"], confirm_intent
            )
        ):
            raise TransitionEngineError(
                "INTENT_STALE",
                "supplied transition intent does not match current evidence",
                details={"preview": intent},
            )

        candidate: dict[str, object] = copy.deepcopy(dict(state))
        audit_facts: list[AuditFact] = []
        pending_kernel_delta: dict[str, object] = {
            "set": {},
            "remove": [],
            "operations": [],
        }
        if action_outcome is not None:
            audit_facts.extend(action_outcome.audit_facts)
        if approval_outcome is not None:
            audit_facts.extend(approval_outcome.audit_facts)
        reducers = edge.get("reducers", ())
        if not isinstance(reducers, tuple):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID",
                "edge reducers must be an array",
                details={"edge_id": edge.get("id")},
        )
        allowed_writes = edge.get("allowed_state_writes")
        if not isinstance(allowed_writes, tuple):
            raise TransitionEngineError(
                "WORKFLOW_GRAPH_INVALID",
                "edge must declare allowed state writes",
                details={"edge_id": edge.get("id")},
            )
        for reducer_reference in reducers:
            reducer_id, reducer_version = (
                _transition_engine_contract_reference(
                    reducer_reference,
                    expected_registry="reducers",
                    schema_v4=schema_v4,
                )
            )
            reducer = _transition_engine_resolve_handler(
                self._reducer_resolver,
                reducer_id,
                registry="reducers",
                version=reducer_version,
            )
            reducer_input = _freeze_contract_value(
                copy.deepcopy(candidate), "$reducer/state"
            )
            result = reducer(
                reducer_input,
                edge,
                action_outcome,
                approval_outcome,
                reducer_capability,
            )
            if not isinstance(result, ReducerResult):
                raise TransitionEngineError(
                    "REDUCER_RESULT_INVALID",
                    "reducer did not return a typed ReducerResult",
                    details={"reducer_id": reducer_id},
                )
            next_candidate = _thaw_contract_value(
                result.candidate_state
            )
            if not isinstance(next_candidate, dict):
                raise TransitionEngineError(
                    "REDUCER_RESULT_INVALID",
                    "reducer candidate state must be an object",
                    details={"reducer_id": reducer_id},
                )
            if next_candidate.get("status") != source:
                raise TransitionEngineError(
                    "REDUCER_STATUS_WRITE_FORBIDDEN",
                    "only the transition engine may set task status",
                    details={"reducer_id": reducer_id},
                )
            reducer_changed = json_pointer_diff(candidate, next_candidate)
            enforce_allowed_state_writes(
                reducer_changed, allowed_writes
            )
            candidate = next_candidate
            audit_facts.extend(result.audit_facts)
            pending_kernel_delta = _transition_engine_merge_kernel_delta(
                pending_kernel_delta,
                result.kernel_state_delta,
            )
        if (
            pending_kernel_delta["set"]
            or pending_kernel_delta["remove"]
            or pending_kernel_delta["operations"]
        ):
            next_candidate = _transition_engine_apply_kernel_delta(
                candidate,
                pending_kernel_delta,
                edge,
                action_parameters,
            )
            kernel_delta_changed = json_pointer_diff(
                candidate, next_candidate
            )
            _transition_engine_enforce_kernel_writes(
                kernel_delta_changed,
                _transition_engine_kernel_write_paths(edge),
            )
            candidate = next_candidate
        if self._kernel_effect_applier is not None:
            effect_result = self._kernel_effect_applier(
                _freeze_contract_value(
                    copy.deepcopy(candidate), "$kernel/state"
                ),
                edge,
                action_outcome,
                approval_outcome,
                _freeze_contract_value(
                    copy.deepcopy(dict(action_parameters)),
                    "$kernel/action_parameters",
                ),
            )
            if not isinstance(effect_result, KernelEffectResult):
                raise TransitionEngineError(
                    "KERNEL_EFFECT_RESULT_INVALID",
                    "kernel effect applier did not return a typed result",
                    details={"edge_id": edge.get("id")},
                )
            next_candidate = _thaw_contract_value(
                effect_result.candidate_state
            )
            if not isinstance(next_candidate, dict):
                raise TransitionEngineError(
                    "KERNEL_EFFECT_RESULT_INVALID",
                    "kernel effect candidate state must be an object",
                )
            if next_candidate.get("status") != source:
                raise TransitionEngineError(
                    "KERNEL_STATUS_WRITE_FORBIDDEN",
                    "only the transition engine may set task status",
                )
            kernel_changed = json_pointer_diff(candidate, next_candidate)
            _transition_engine_enforce_kernel_writes(
                kernel_changed,
                _transition_engine_kernel_write_paths(edge),
            )
            candidate = next_candidate
            audit_facts.extend(effect_result.audit_facts)
        candidate["status"] = target

        changed = json_pointer_diff(state, candidate)
        changed = _transition_engine_enforce_combined_writes(
            changed,
            allowed_writes,
            _transition_engine_kernel_write_paths(edge),
        )
        for invariant in self._invariant_checks:
            invariant(state, candidate)

        evaluation = TransitionEvaluation(
            edge_id=str(edge.get("id")),
            source=source,
            target=target,
            intent=intent,
            candidate_state=candidate,
            changed_paths=changed,
            guard_results=tuple(guard_results),
            audit_facts=tuple(audit_facts),
        )
        if schema_v4 and not preview:
            _transition_engine_register_evaluation_issuance(
                evaluation,
                state=state,
                action_id=action_id,
                action_parameters=action_parameters,
                evidence=evidence,
                action_outcome=action_outcome,
                approval_outcome=approval_outcome,
                kernel_context=context_value,
            )
        return evaluation
