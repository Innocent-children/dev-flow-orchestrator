# Loaded by scripts/dev_flow.py after the pinned transition service.
# Responsibility: select one catalog action, evaluate it through registered
# contracts, and commit only through the one-shot engine proof boundary.
from __future__ import annotations

import copy
import secrets
from dataclasses import dataclass
from typing import Callable, Mapping


_workflow_action_selection_parameter = "catalog_selection"
_workflow_action_safe_movement_effects = frozenset(
    {
        "approval",
        "evidence-or-approval-invalidation",
        "risk-escalation",
        "task-state",
    }
)
_workflow_action_engine_proof_binding_contract = (
    "dev-flow-v3-engine-commit-proof-binding/v1"
)
_workflow_action_engine_proof_binding_domain = (
    b"dev-flow-v3-engine-commit-proof-binding-v1\0"
)
_workflow_action_scoped_candidate_domain = (
    b"dev-flow-v3-scoped-candidate-projection-v1\0"
)
_workflow_action_quarantined_receipt_authority = object()


@dataclass(frozen=True)
class WorkflowActionReceiptContext:
    """Controller-owned proof that one verified journal is durably promoted.

    The reauthentication resolver is invoked only while validating the
    context. Its secret result is never copied into an outcome, intent, event,
    proof binding, error detail, or retained service object.
    """

    index: Mapping[str, object]
    journal: Mapping[str, object]
    expected_index: CASToken
    reauthenticate: Callable[[], str | bytes | None]
    pre_effect_state: Mapping[str, object] | None = None
    neutralize_manager_nonce: bool = False
    reconciliation_authority: object | None = None


def _workflow_action_error(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> TransitionEngineError:
    return TransitionEngineError(code, message, details=details)


def _workflow_action_public_mapping(
    value: Mapping[str, object] | None,
    *,
    role: str,
) -> dict[str, object]:
    try:
        public = copy.deepcopy(
            _workflow_transition_public(dict(value or {}))
        )
    except (TypeError, ValueError) as exc:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_REQUEST_INVALID",
            f"{role} must be a JSON-compatible object",
        ) from exc
    if not isinstance(public, dict):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_REQUEST_INVALID",
            f"{role} must be an object",
        )
    return public


def _workflow_action_bundle(
    state: Mapping[str, object],
) -> object:
    if state.get("schema_version") != V3_TASK_SCHEMA_VERSION:
        raise _workflow_action_error(
            "V3_ACTION_SERVICE_REQUIRED",
            "catalog action service requires a schema-v3 task",
        )
    status = state.get("status")
    if not isinstance(status, str) or not status:
        raise _workflow_action_error(
            "TASK_STATE_INVALID",
            "catalog action service requires one current node",
        )
    return _workflow_transition_bundle(state)


def resolve_v3_node_action_edge(
    state: Mapping[str, object],
    public_command: str,
    *,
    selector: str | None = None,
) -> Mapping[str, object]:
    """Resolve one exact compiled same-node edge from its public selector."""

    bundle = _workflow_action_bundle(state)
    status = str(state["status"])
    try:
        edge = bundle.resolve_public_action(
            status, public_command, selector=selector
        )
    except WorkflowCatalogError as exc:
        raise _workflow_action_error(
            exc.code, exc.message, details=exc.details
        ) from exc
    if (
        edge.get("class") != "action"
        or edge.get("source") != status
        or edge.get("target") != status
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_EDGE_INVALID",
            "public node action did not resolve one exact same-node edge",
            details={"status": status, "edge_id": edge.get("id")},
        )
    return edge


def _workflow_action_movement_trigger(
    public_command: str,
    target: str,
) -> str:
    if public_command == "cancel":
        if target != "CANCELLED":
            raise _workflow_action_error(
                "WORKFLOW_ACTION_PLACEMENT_INVALID",
                "cancel can select only the pinned CANCELLED movement",
                details={
                    "public_command": public_command,
                    "target": target,
                },
            )
        return "cancel"
    if public_command == "transition":
        return "transition-cancel" if target == "CANCELLED" else "transition"
    raise _workflow_action_error(
        "WORKFLOW_ACTION_UNDECLARED",
        "movement service exposes only transition and cancel selectors",
        details={"public_command": public_command},
    )


def resolve_v3_movement_action_edge(
    state: Mapping[str, object],
    public_command: str,
    *,
    target: str,
    edge_selector: str | None = None,
) -> Mapping[str, object]:
    """Resolve one existing movement edge through the frozen CLI selectors."""

    bundle = _workflow_action_bundle(state)
    source = str(state["status"])
    if not isinstance(target, str) or not target or target == source:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_PLACEMENT_INVALID",
            "movement requires a distinct explicit target node",
            details={"source": source, "target": target},
        )
    trigger_id = _workflow_action_movement_trigger(
        public_command, target
    )
    candidates = [
        edge
        for edge in bundle.legal_movement_edges(source)
        if edge.get("target") == target
        and isinstance(edge.get("trigger"), Mapping)
        and edge["trigger"].get("id") == trigger_id
    ]
    if edge_selector is not None:
        candidates = [
            edge
            for edge in candidates
            if edge.get("id") == edge_selector
        ]
    if len(candidates) != 1:
        raise _workflow_action_error(
            (
                "WORKFLOW_ACTION_SELECTION_AMBIGUOUS"
                if len(candidates) > 1
                else "WORKFLOW_ACTION_PLACEMENT_INVALID"
            ),
            "movement selector did not resolve one pinned edge",
            details={
                "source": source,
                "target": target,
                "public_command": public_command,
                "trigger_id": trigger_id,
                "edge_selector": edge_selector,
                "edge_ids": sorted(
                    str(edge.get("id")) for edge in candidates
                ),
            },
        )
    return candidates[0]


def _workflow_action_handler_descriptor(
    edge: Mapping[str, object],
) -> dict[str, object]:
    reference = edge.get("handler")
    if (
        not isinstance(reference, Mapping)
        or reference.get("registry") != "executors"
        or not isinstance(reference.get("id"), str)
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_HANDLER_INVALID",
            "pinned action edge has no exact executor descriptor",
            details={"edge_id": edge.get("id")},
        )
    identifier = str(reference["id"])
    version = _workflow_transition_require_handler_version(
        "executors",
        identifier,
        (
            str(reference["version"])
            if isinstance(reference.get("version"), str)
            else None
        ),
    )
    resolver = workflow_runtime_services().handler_resolver
    registration = resolver.resolve("executors", identifier, version)
    dispatcher = resolver.resolve_callable(
        "executors", identifier, version, "dispatcher"
    )
    if not callable(dispatcher):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_HANDLER_INVALID",
            "pinned executor descriptor has no registered dispatcher",
            details={
                "edge_id": edge.get("id"),
                "handler_id": identifier,
                "version": version,
            },
        )
    fact = _workflow_transition_handler_fact(
        "executors", identifier, version, registration
    )
    symbols = getattr(registration, "symbols", {})
    fact.update(
        {
            "dispatcher_symbol": (
                symbols.get("dispatcher")
                if isinstance(symbols, Mapping)
                else None
            ),
            "descriptor_only": True,
            "executed": False,
        }
    )
    return fact


def _workflow_action_exact_outcome(
    edge: Mapping[str, object],
    outcome: ActionOutcome,
    handler: Mapping[str, object],
) -> ActionOutcome:
    trigger = edge.get("trigger")
    action_id = (
        trigger.get("id") if isinstance(trigger, Mapping) else None
    )
    edge_id = edge.get("id")
    if (
        type(outcome) is not ActionOutcome
        or outcome.action_id != action_id
        or outcome.proposed_edge_id != edge_id
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_OUTCOME_MISMATCH",
            "typed action outcome does not bind the selected pinned edge",
            details={
                "expected_action_id": action_id,
                "actual_action_id": getattr(outcome, "action_id", None),
                "expected_edge_id": edge_id,
                "actual_edge_id": getattr(
                    outcome, "proposed_edge_id", None
                ),
            },
        )
    return ActionOutcome(
        outcome.action_id,
        outcome.proposed_edge_id,
        evidence_records=outcome.evidence_records,
        proposed_state_delta=outcome.proposed_state_delta,
        audit_facts=(
            *outcome.audit_facts,
            AuditFact(
                "pinned-action-handler-resolved",
                {
                    "edge_id": edge_id,
                    "handler": dict(handler),
                },
            ),
        ),
        external_postconditions=outcome.external_postconditions,
    )


def _workflow_action_exact_approval(
    edge: Mapping[str, object],
    outcome: ApprovalOutcome | None,
) -> ApprovalOutcome | None:
    gate = edge.get("gate")
    if gate is None:
        if outcome is not None:
            raise _workflow_action_error(
                "WORKFLOW_ACTION_APPROVAL_MISMATCH",
                "an ungated action cannot carry an approval outcome",
                details={"edge_id": edge.get("id")},
            )
        return None
    if not isinstance(gate, Mapping) or type(outcome) is not ApprovalOutcome:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_APPROVAL_REQUIRED",
            "gated action requires one typed pinned ApprovalOutcome",
            details={"edge_id": edge.get("id")},
        )
    gate_id = gate.get("id")
    if (
        outcome.gate_id != gate_id
        or outcome.proposed_edge_id != edge.get("id")
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_APPROVAL_MISMATCH",
            "approval outcome does not bind the selected gate and edge",
            details={
                "expected_gate_id": gate_id,
                "actual_gate_id": outcome.gate_id,
                "expected_edge_id": edge.get("id"),
                "actual_edge_id": outcome.proposed_edge_id,
            },
        )
    version = _workflow_transition_require_handler_version(
        "gates",
        str(gate_id),
        (
            str(gate["version"])
            if isinstance(gate.get("version"), str)
            else None
        ),
    )
    resolver = workflow_runtime_services().handler_resolver
    registration = resolver.resolve("gates", str(gate_id), version)
    fact = _workflow_transition_handler_fact(
        "gates", str(gate_id), version, registration
    )
    return ApprovalOutcome(
        outcome.gate_id,
        outcome.proposed_edge_id,
        outcome.approval,
        evidence_records=outcome.evidence_records,
        audit_facts=(
            *outcome.audit_facts,
            AuditFact(
                "pinned-action-gate-resolved",
                {
                    "edge_id": edge.get("id"),
                    "handler": fact,
                },
            ),
        ),
    )


def _workflow_action_graph(
    bundle: object,
    *,
    node_action: bool,
) -> dict[str, object]:
    if not node_action:
        return _workflow_transition_v3_graph(bundle)
    graph = _workflow_transition_graph(bundle)
    movement_edges = tuple(getattr(bundle, "movement_edges", ()))
    action_edges = tuple(getattr(bundle, "action_edges", ()))
    expanded = copy.deepcopy(
        _workflow_transition_public(
            (*movement_edges, *action_edges)
        )
    )
    if not isinstance(expanded, list):
        raise _workflow_action_error(
            "WORKFLOW_GRAPH_INVALID",
            "pinned bundle action closure is unavailable",
        )
    for edge in expanded:
        if not isinstance(edge, dict) or edge.get("class") != "action":
            continue
        writes = {
            item
            for item in edge.get("kernel_state_writes", ())
            if isinstance(item, str)
        }
        writes.update(
            item
            for item in edge.get("kernel_invalidates", ())
            if isinstance(item, str)
        )
        edge["kernel_invalidates"] = sorted(
            writes, key=lambda item: item.encode("utf-8")
        )
    graph["edges"] = expanded
    return graph


def _workflow_action_receipt_required(
    edge: Mapping[str, object],
) -> bool:
    effects = edge.get("effects")
    if isinstance(effects, (list, tuple)):
        return any(
            isinstance(effect, Mapping)
            and effect.get("dispatch") == "single-dispatch"
            for effect in effects
        )
    side_effects = {
        item
        for item in edge.get("side_effects", ())
        if isinstance(item, str)
    }
    return bool(
        side_effects - _workflow_action_safe_movement_effects
    )


def _workflow_action_verified_journal_receipt(
    state: Mapping[str, object],
    bundle: object,
    edge: Mapping[str, object],
    context: WorkflowActionReceiptContext | None,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    required = _workflow_action_receipt_required(edge)
    if context is None:
        return None, None
    if type(context) is not WorkflowActionReceiptContext:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_CONTEXT_INVALID",
            "verified receipt authority requires the strict journal context",
        )
    if not required:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_UNEXPECTED",
            "an effect-free action cannot carry a journal receipt context",
            details={"edge_id": edge.get("id")},
        )
    if not callable(context.reauthenticate):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_REAUTH_REQUIRED",
            "journal receipt context requires a reauthentication resolver",
        )
    manager_secret: str | bytes | None = None
    reauthentication_failed = False
    journal_failure: tuple[str, str] | None = None
    normalized_journal: dict[str, object] | None = None
    normalized_index: dict[str, object] | None = None
    try:
        try:
            manager_secret = context.reauthenticate()
        except Exception:
            reauthentication_failed = True
        if not reauthentication_failed:
            try:
                normalized_journal = normalize_journal(context.journal)
                normalized_index = normalize_index(context.index)
                assert_journal_promoted(
                    normalized_index,
                    normalized_journal,
                    expected_index=context.expected_index,
                    manager_secret=manager_secret,
                )
            except ActionExecutionJournalError as exc:
                journal_failure = (exc.code, exc.message)
    finally:
        manager_secret = None
    if reauthentication_failed:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_REAUTH_FAILED",
            "journal receipt reauthentication failed",
        )
    if journal_failure is not None:
        # Journal diagnostics are intentionally not forwarded with arbitrary
        # details so reauthentication material can never enter an exception.
        raise _workflow_action_error(*journal_failure)
    if normalized_journal is None or normalized_index is None:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_CONTEXT_INVALID",
            "journal receipt context could not be normalized",
        )
    bindings = normalized_journal.get("bindings")
    receipt = normalized_journal.get("receipt")
    handler = edge.get("handler")
    handler_id = (
        handler.get("id") if isinstance(handler, Mapping) else None
    )
    binding_state = state
    if context.pre_effect_state is not None:
        candidate = copy.deepcopy(
            _workflow_action_public_mapping(
                context.pre_effect_state,
                role="journal pre-effect state",
            )
        )
        event_type = edge.get("canonical_event")
        if not isinstance(event_type, str) or not event_type:
            authorization_edge_id = (
                bindings.get("authorization_action_edge_id")
                if isinstance(bindings, Mapping)
                else None
            )
            authorization_edges = [
                candidate_edge
                for candidate_edge in getattr(
                    bundle, "action_edges", ()
                )
                if candidate_edge.get("id")
                == authorization_edge_id
            ]
            if len(authorization_edges) == 1:
                event_type = authorization_edges[0].get(
                    "canonical_event"
                )
        if not isinstance(event_type, str) or not event_type:
            raise _workflow_action_error(
                "WORKFLOW_ACTION_CATALOG_INVALID",
                "receipt-bound manager action has no canonical event",
                details={"edge_id": edge.get("id")},
            )
        if _sha256_contract(candidate) != _sha256_contract(state):
            try:
                (
                    _manager_invocation,
                    manager_request,
                    _manager_preauthorization,
                ) = _manager_validated_preauthorization_v1(
                    candidate, event_type=event_type
                )
                _manager_validate_nonce_delta(
                    candidate,
                    state,
                    capability_id=manager_request.capability_id,
                    nonce_sha256=manager_request_nonce_digest(
                        manager_request
                    ),
                )
            except FlowError as exc:
                raise _workflow_action_error(
                    exc.code, exc.message, details=exc.details
                ) from exc
        binding_state = candidate
    expected = {
        "task_id": binding_state.get("task_id"),
        "workflow_id": getattr(bundle, "workflow_id", None),
        "workflow_version": str(
            getattr(bundle, "workflow_version", "")
        ),
        "workflow_bundle_sha256": getattr(
            bundle, "bundle_sha256", None
        ),
        "action_edge_id": edge.get("id"),
        "completion_edge_id": edge.get("id"),
        "handler_id": handler_id,
    }
    actual = {
        "task_id": normalized_journal.get("task_id"),
        **(
            {
                key: bindings.get(key)
                for key in expected
                if key != "task_id"
            }
            if isinstance(bindings, Mapping)
            else {}
        ),
    }
    mismatches = sorted(
        key
        for key, value in expected.items()
        if actual.get(key) != value
    )
    revision_policy = (
        bindings.get("revision_policy")
        if isinstance(bindings, Mapping)
        else None
    )
    prepared_revision = (
        bindings.get("task_revision")
        if isinstance(bindings, Mapping)
        else None
    )
    prepared_state_sha256 = (
        bindings.get("pre_effect_state_sha256")
        if isinstance(bindings, Mapping)
        else None
    )
    current_revision = binding_state.get("revision")
    if revision_policy == "exact-revision":
        if prepared_revision != current_revision:
            mismatches.append("task_revision")
        if prepared_state_sha256 != _sha256_contract(binding_state):
            mismatches.append("pre_effect_state_sha256")
    elif revision_policy == "disjoint-scope-revalidate":
        if (
            isinstance(prepared_revision, bool)
            or not isinstance(prepared_revision, int)
            or isinstance(current_revision, bool)
            or not isinstance(current_revision, int)
            or current_revision < prepared_revision
        ):
            mismatches.append("task_revision")
        if (
            not isinstance(prepared_state_sha256, str)
            or not _workflow_catalog_sha256_re.fullmatch(
                prepared_state_sha256
            )
        ):
            mismatches.append("pre_effect_state_sha256")
        elif (
            current_revision == prepared_revision
            and prepared_state_sha256
            != _sha256_contract(binding_state)
        ):
            mismatches.append("pre_effect_state_sha256")
    else:
        mismatches.append("revision_policy")
    mismatches = sorted(set(mismatches))
    if mismatches:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_BINDING_MISMATCH",
            "verified journal does not bind the current pinned action",
            details={
                "edge_id": edge.get("id"),
                "fields": mismatches,
            },
        )
    journal_phase = normalized_journal.get("phase")
    quarantined_reconciliation = (
        journal_phase == "QUARANTINED"
        and context.reconciliation_authority
        is _workflow_action_quarantined_receipt_authority
        and isinstance(normalized_journal.get("quarantine"), Mapping)
    )
    if (
        journal_phase != "RECEIPT_VERIFIED"
        and not quarantined_reconciliation
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_PHASE_INVALID",
            "action commit requires a promoted RECEIPT_VERIFIED journal "
            "or an authenticated reconciliation receipt",
            details={
                "edge_id": edge.get("id"),
                "phase": journal_phase,
            },
        )
    if not isinstance(receipt, dict):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_RECEIPT_INVALID",
            "receipt-authorized journal has no typed receipt",
            details={"edge_id": edge.get("id")},
        )
    authorization_edge_id = (
        bindings.get("authorization_action_edge_id")
        if isinstance(bindings, Mapping)
        else None
    )
    completion_edge_id = (
        bindings.get("completion_edge_id")
        if isinstance(bindings, Mapping)
        else None
    )
    if (
        not isinstance(authorization_edge_id, str)
        or not authorization_edge_id
        or completion_edge_id != edge.get("id")
        or not isinstance(receipt, Mapping)
        or receipt.get("authorization_action_edge_id")
        != authorization_edge_id
        or receipt.get("completion_edge_id") != completion_edge_id
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_EDGE_ROLE_MISMATCH",
            "verified journal receipt does not bind both action edge roles",
            details={"completion_edge_id": edge.get("id")},
        )
    if authorization_edge_id != completion_edge_id:
        completion_trigger = edge.get("trigger")
        authorization_matches = tuple(
            candidate
            for candidate in bundle.legal_action_edges(
                str(state.get("status"))
            )
            if candidate.get("id") == authorization_edge_id
            and isinstance(
                candidate.get("public_command"), Mapping
            )
            and isinstance(completion_trigger, Mapping)
            and candidate["public_command"].get("id")
            == completion_trigger.get("id")
            and isinstance(candidate.get("trigger"), Mapping)
            and candidate["trigger"].get("kind") == "action"
            and completion_trigger.get("kind") == "action"
        )
        if len(authorization_matches) != 1:
            raise _workflow_action_error(
                "WORKFLOW_ACTION_JOURNAL_EDGE_ROLE_MISMATCH",
                "completion receipt has no unique same-command authorization action",
                details={
                    "authorization_action_edge_id": (
                        authorization_edge_id
                    ),
                    "completion_edge_id": completion_edge_id,
                },
            )
    return (
        copy.deepcopy(receipt),
        {
            "schema": normalized_journal.get("schema"),
            "execution_id": normalized_journal.get("execution_id"),
            "journal_record_sha256": normalized_journal.get(
                "record_sha256"
            ),
            "index_record_sha256": normalized_index.get(
                "record_sha256"
            ),
            "candidate_after_sha256": bindings.get(
                "candidate_after_sha256"
            ),
            "revision_policy": bindings.get("revision_policy"),
            "authorization_action_edge_id": (
                authorization_edge_id
            ),
            "completion_edge_id": completion_edge_id,
        },
    )


def _workflow_action_candidate_binding_sha256(
    evaluation: TransitionEvaluation,
    revision_policy: str,
) -> str:
    """Bind exact candidates or only the declared changed projection.

    A scoped PREPARED record must survive unrelated task-state movement, so
    it binds the proposed changed-path projection. The final receipt still
    binds the full candidate produced from the latest authoritative state.
    """

    if revision_policy == "exact-revision":
        return _sha256_contract(evaluation.candidate_state)
    if revision_policy != "disjoint-scope-revalidate":
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_REVISION_POLICY_INVALID",
            "candidate binding requires a supported revision policy",
        )
    candidate = evaluation.candidate_state
    projection: list[dict[str, object]] = []
    for pointer in sorted(
        set(evaluation.changed_paths),
        key=lambda item: item.encode("utf-8"),
    ):
        present, value = _transition_engine_pointer_get(
            candidate, pointer
        )
        projection.append(
            {
                "path": pointer,
                "present": present,
                "value": (
                    _workflow_transition_public(value)
                    if present
                    else None
                ),
            }
        )
    return semantic_sha256(
        _workflow_action_scoped_candidate_domain,
        {
            "edge_id": evaluation.edge_id,
            "changed_paths": projection,
        },
    )


def _workflow_action_manager_neutral_candidate(
    evaluation: TransitionEvaluation,
    pre_effect_state: Mapping[str, object] | None,
) -> dict[str, object]:
    candidate = copy.deepcopy(
        _workflow_transition_public(evaluation.candidate_state)
    )
    if not isinstance(candidate, dict):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_CANDIDATE_MISMATCH",
            "engine candidate is not an object",
        )
    if pre_effect_state is not None:
        invocation = _manager_authority_context_var.get()
        manager_request = getattr(invocation, "request", None)
        capability_id = getattr(
            manager_request, "capability_id", None
        )
        before_orchestration = pre_effect_state.get("orchestration")
        candidate_orchestration = candidate.get("orchestration")
        if (
            isinstance(capability_id, str)
            and isinstance(before_orchestration, Mapping)
            and isinstance(candidate_orchestration, Mapping)
            and isinstance(
                before_orchestration.get(
                    "manager_capabilities"
                ),
                Mapping,
            )
            and isinstance(
                candidate_orchestration.get(
                    "manager_capabilities"
                ),
                Mapping,
            )
        ):
            neutral_orchestration = copy.deepcopy(
                _workflow_transition_public(
                    candidate_orchestration
                )
            )
            before_capabilities = before_orchestration[
                "manager_capabilities"
            ]
            neutral_capabilities = neutral_orchestration[
                "manager_capabilities"
            ]
            assert isinstance(neutral_capabilities, dict)
            if capability_id in before_capabilities:
                neutral_capabilities[capability_id] = (
                    copy.deepcopy(
                        _workflow_transition_public(
                            before_capabilities[capability_id]
                        )
                    )
                )
            else:
                neutral_capabilities.pop(capability_id, None)
            candidate["orchestration"] = neutral_orchestration
    return candidate


def _workflow_action_validate_receipt_candidate(
    evaluation: TransitionEvaluation,
    receipt: Mapping[str, object] | None,
    journal_binding: Mapping[str, object] | None,
    *,
    pre_effect_state: Mapping[str, object] | None = None,
) -> None:
    if receipt is None and journal_binding is None:
        return
    candidate = _workflow_action_manager_neutral_candidate(
        evaluation, pre_effect_state
    )
    candidate_sha256 = _sha256_contract(candidate)
    revision_policy = (
        journal_binding.get("revision_policy")
        if isinstance(journal_binding, Mapping)
        else None
    )
    prepared_candidate_sha256 = None
    if revision_policy == "exact-revision":
        prepared_candidate_sha256 = candidate_sha256
    elif revision_policy == "disjoint-scope-revalidate":
        projection = []
        for pointer in sorted(
            set(evaluation.changed_paths),
            key=lambda item: item.encode("utf-8"),
        ):
            present, value = _transition_engine_pointer_get(
                candidate, pointer
            )
            if pre_effect_state is not None:
                before_present, before_value = (
                    _transition_engine_pointer_get(
                        pre_effect_state, pointer
                    )
                )
                if (
                    before_present == present
                    and (
                        not present
                        or _sha256_contract(before_value)
                        == _sha256_contract(value)
                    )
                ):
                    continue
            projection.append(
                {
                    "path": pointer,
                    "present": present,
                    "value": (
                        _workflow_transition_public(value)
                        if present
                        else None
                    ),
                }
            )
        prepared_candidate_sha256 = semantic_sha256(
            _workflow_action_scoped_candidate_domain,
            {
                "edge_id": evaluation.edge_id,
                "changed_paths": projection,
            },
        )
    if (
        not isinstance(receipt, Mapping)
        or not isinstance(journal_binding, Mapping)
        or receipt.get("candidate_state_sha256") != candidate_sha256
        or journal_binding.get("candidate_after_sha256")
        != prepared_candidate_sha256
        or receipt.get("completion_edge_id")
        != evaluation.edge_id
        or journal_binding.get("completion_edge_id")
        != evaluation.edge_id
        or receipt.get("authorization_action_edge_id")
        != journal_binding.get("authorization_action_edge_id")
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_JOURNAL_CANDIDATE_MISMATCH",
            "verified journal receipt does not bind the engine candidate",
            details={"edge_id": evaluation.edge_id},
        )


def _workflow_action_receipt_sha256(
    receipt: Mapping[str, object] | None,
) -> str | None:
    if receipt is None:
        return None
    public = _workflow_action_public_mapping(
        receipt, role="verified receipt"
    )
    return _sha256_contract(public)


def _workflow_action_parameters(
    edge: Mapping[str, object],
    *,
    node_action: bool,
    public_command: str,
    selector: str | None,
    target: str,
    edge_selector: str | None,
    action_parameters: Mapping[str, object] | None,
) -> dict[str, object]:
    parameters = _workflow_action_public_mapping(
        action_parameters, role="action parameters"
    )
    reserved_parameters = {
        _workflow_action_selection_parameter,
        "verified_journal",
        "verified_receipt_sha256",
    }
    supplied_reserved = sorted(
        reserved_parameters.intersection(parameters)
    )
    if supplied_reserved:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_REQUEST_INVALID",
            "catalog and journal binding metadata is controller-owned",
            details={"fields": supplied_reserved},
        )
    if node_action:
        public = edge.get("public_command")
        selector_name = (
            public.get("selector")
            if isinstance(public, Mapping)
            else None
        )
        if isinstance(selector_name, str):
            supplied = parameters.get(selector_name)
            if supplied is not None and supplied != selector:
                raise _workflow_action_error(
                    "WORKFLOW_ACTION_SELECTOR_UNDECLARED",
                    "action parameter conflicts with the resolved selector",
                    details={
                        "selector": selector_name,
                        "expected": selector,
                        "actual": supplied,
                    },
                )
            parameters[selector_name] = selector
    parameters[_workflow_action_selection_parameter] = {
        "kind": "node-action" if node_action else "movement",
        "public_command": public_command,
        "selector": selector,
        "target": target,
        "edge_selector": edge_selector,
        "edge_id": edge.get("id"),
    }
    return parameters


def _workflow_action_assignment_effect_paths(
    state: Mapping[str, object],
    edge: Mapping[str, object],
    parameters: Mapping[str, object],
) -> tuple[str, ...]:
    effect_authorization = parameters.get(
        "_catalog_effect_authorization"
    )
    if effect_authorization is None:
        return ()
    if not isinstance(effect_authorization, (list, tuple)):
        raise _workflow_action_error(
            "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
            "catalog effect authorization must be an array",
        )
    declared_effects = {
        str(item["id"]): item
        for item in edge.get("effects", ())
        if (
            isinstance(item, Mapping)
            and isinstance(item.get("id"), str)
        )
    }
    orchestration = state.get("orchestration")
    assignments = (
        orchestration.get("assignments")
        if isinstance(orchestration, Mapping)
        else None
    )
    leases = (
        orchestration.get("leases")
        if isinstance(orchestration, Mapping)
        else None
    )
    if not isinstance(assignments, Mapping):
        assignments = {}
    if not isinstance(leases, Mapping):
        leases = {}
    scope_fields = (
        "repository_ids",
        "node_ids",
        "worktree_ids",
        "lease_ids",
        "paths",
        "external_resources",
    )
    authorized_paths: set[str] = set()
    seen_effects: set[str] = set()
    for binding in effect_authorization:
        if (
            not isinstance(binding, Mapping)
            or set(binding)
            != {
                "effect_id",
                "scope_kinds",
                "scopes",
                "safe_input_sha256",
                "attempt_id",
            }
            or not isinstance(binding.get("effect_id"), str)
            or not isinstance(binding.get("scope_kinds"), (list, tuple))
            or not isinstance(binding.get("scopes"), Mapping)
            or set(binding["scopes"]) != set(scope_fields)
            or not isinstance(
                binding.get("safe_input_sha256"), str
            )
            or not _workflow_catalog_sha256_re.fullmatch(
                binding["safe_input_sha256"]
            )
            or not isinstance(binding.get("attempt_id"), str)
            or not binding["attempt_id"]
        ):
            raise _workflow_action_error(
                "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                "catalog effect authorization has an invalid shape",
            )
        effect_id = str(binding["effect_id"])
        declared = declared_effects.get(effect_id)
        if (
            declared is None
            or effect_id in seen_effects
            or tuple(binding["scope_kinds"])
            != tuple(declared.get("scopes", ()))
        ):
            raise _workflow_action_error(
                "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                "catalog effect authorization is not declared by the selected edge",
                details={"effect_id": effect_id},
            )
        seen_effects.add(effect_id)
        normalized_scopes: dict[str, tuple[str, ...]] = {}
        for field in scope_fields:
            values = binding["scopes"].get(field)
            if (
                not isinstance(values, (list, tuple))
                or any(
                    not isinstance(value, str) or not value
                    for value in values
                )
                or tuple(values)
                != tuple(
                    sorted(
                        set(values),
                        key=lambda value: value.encode("utf-8"),
                    )
                )
            ):
                raise _workflow_action_error(
                    "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                    "catalog effect scopes must be sorted unique strings",
                    details={
                        "effect_id": effect_id,
                        "scope": field,
                    },
                )
            normalized_scopes[field] = tuple(values)
        for path in normalized_scopes["paths"]:
            path_matches = [
                value
                for value in assignments.values()
                if (
                    isinstance(value, Mapping)
                    and value.get("worktree_path") == path
                )
            ]
            if not path_matches:
                continue
            matching = [
                value
                for value in path_matches
                if (
                    value.get("repository_id")
                    in normalized_scopes["repository_ids"]
                    and value.get("node_instance_id")
                    in normalized_scopes["node_ids"]
                    and value.get("worktree_identity_sha256")
                    in normalized_scopes["worktree_ids"]
                    and isinstance(
                        value.get("lease_credential"), Mapping
                    )
                    and value["lease_credential"].get("lease_id")
                    in normalized_scopes["lease_ids"]
                )
            ]
            if len(matching) != 1:
                raise _workflow_action_error(
                    "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                    "effect path and scopes do not identify one persisted assignment",
                    details={
                        "effect_id": effect_id,
                        "path": path,
                        "path_match_count": len(path_matches),
                        "scope_match_count": len(matching),
                    },
                )
            try:
                assignment = validate_worker_assignment(matching[0])
                lease = validate_worker_lease(
                    leases.get(
                        assignment.lease_credential.lease_id
                    )
                )
            except OrchestrationAuthorityError as exc:
                raise _workflow_action_error(
                    getattr(
                        exc,
                        "code",
                        "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                    ),
                    "effect path has no valid assignment and lease authority",
                    details=getattr(exc, "details", {}),
                ) from exc
            expected_scopes = {
                "repository_ids": (assignment.repository_id,),
                "node_ids": (assignment.node_instance_id,),
                "worktree_ids": (
                    assignment.worktree_identity_sha256,
                ),
                "lease_ids": (
                    assignment.lease_credential.lease_id,
                ),
            }
            if (
                lease.task_id != state.get("task_id")
                or lease.node_instance_id
                != assignment.node_instance_id
                or lease.repository_id != assignment.repository_id
                or lease.worktree_identity_sha256
                != assignment.worktree_identity_sha256
                or any(
                    normalized_scopes[field] != expected
                    for field, expected in expected_scopes.items()
                )
            ):
                raise _workflow_action_error(
                    "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                    "effect path scopes do not match its sealed assignment and lease",
                    details={"effect_id": effect_id, "path": path},
                )
            authorized_paths.add(path)
    return tuple(sorted(authorized_paths))


def _workflow_action_kernel_context(
    state: Mapping[str, object],
    bundle: object,
    edge: Mapping[str, object],
    parameters: Mapping[str, object],
    evidence: Mapping[str, object],
    approval_outcome: ApprovalOutcome | None,
    *,
    approval_intent_id: str | None,
) -> KernelTransitionContext:
    task_lock, workspace_lock, ownership_lock = (
        workflow_runtime_services().locks.workflow_transition_locks(state)
    )
    requested_paths = _workflow_transition_authorized_paths(state)
    authorized_paths = set(requested_paths)
    authorized_paths.update(
        _workflow_action_assignment_effect_paths(
            state, edge, parameters
        )
    )
    task_directory = _held_task_directory()
    if (
        task_lock
        and task_directory is not None
        and task_directory.name == state.get("task_id")
    ):
        authorized_paths.add(
            str(task_directory.resolve(strict=False))
        )
    values: dict[str, object] = {
        "task_id": str(state.get("task_id")),
        "workflow_ref": state.get("workflow_ref", {}),
        "task_lock_held": task_lock,
        "workspace_lock_held": workspace_lock,
        "ownership_lock_held": ownership_lock,
        "evidence_sha256": _sha256_contract(evidence),
        "evidence_authentic": True,
        "evidence_current": True,
        "supported_node_contracts": {
            str(kind): tuple(versions)
            for kind, versions in (
                _workflow_catalog_supported_node_contracts.items()
            )
        },
        "supported_contract_versions": (
            _workflow_transition_supported_contracts(bundle)
        ),
        "authorized_effects": tuple(
            item
            for item in edge.get("side_effects", ())
            if isinstance(item, str)
        ),
        "requested_effect_paths": requested_paths,
        "authorized_paths": tuple(sorted(authorized_paths)),
    }
    if approval_outcome is not None and approval_intent_id is not None:
        values.update(
            {
                "approval_current": True,
                "approval_intent_id": approval_intent_id,
            }
        )
    return KernelTransitionContext(**values)


def _workflow_action_engine(
    state: Mapping[str, object],
    bundle: object,
    edge: Mapping[str, object],
    parameters: Mapping[str, object],
    *,
    node_action: bool,
) -> TransitionEngine:
    source = str(edge.get("source"))
    target = str(edge.get("target"))

    def movement_kernel_effects(
        candidate: Mapping[str, object],
        selected: Mapping[str, object],
        _action: object,
        _approval: object,
        _parameters: Mapping[str, object],
    ) -> KernelEffectResult:
        advanced = _workflow_transition_advance_nodes(
            candidate, selected
        )
        return KernelEffectResult(
            advanced,
            (
                AuditFact(
                    "node-lifecycle-advanced",
                    {
                        "edge_id": selected.get("id"),
                        "source": selected.get("source"),
                        "target": selected.get("target"),
                    },
                ),
            ),
        )

    return TransitionEngine(
        _workflow_action_graph(bundle, node_action=node_action),
        guard_resolver=_workflow_transition_registered_guard_resolver(
            state,
            source=source,
            target=target,
            parameters={
                **dict(parameters),
                "requires_note": edge.get("requires_note") is True,
            },
            multi_repository_authority_current=(
                state.get("execution_profile") != "multi-repository"
            ),
        ),
        reducer_resolver=_workflow_transition_registered_reducer_resolver(
            parameters=parameters
        ),
        kernel_effect_applier=(
            None if node_action else movement_kernel_effects
        ),
    )


def _workflow_action_evaluate_selected(
    state: Mapping[str, object],
    bundle: object,
    edge: Mapping[str, object],
    *,
    node_action: bool,
    public_command: str,
    selector: str | None,
    edge_selector: str | None,
    action_outcome: ActionOutcome,
    approval_outcome: ApprovalOutcome | None,
    action_parameters: Mapping[str, object] | None,
    evidence: Mapping[str, object] | None,
    confirm_intent: str | None,
    preview: bool,
    receipt_context: WorkflowActionReceiptContext | None,
    allow_unreceipted_reconciliation_noop: bool = False,
) -> TransitionEvaluation:
    handler = _workflow_action_handler_descriptor(edge)
    exact_action = _workflow_action_exact_outcome(
        edge, action_outcome, handler
    )
    exact_approval = _workflow_action_exact_approval(
        edge, approval_outcome
    )
    verified_receipt, verified_journal = (
        _workflow_action_verified_journal_receipt(
            state, bundle, edge, receipt_context
        )
    )
    parameters = _workflow_action_parameters(
        edge,
        node_action=node_action,
        public_command=public_command,
        selector=selector,
        target=str(edge.get("target")),
        edge_selector=edge_selector,
        action_parameters=action_parameters,
    )
    request_evidence = _workflow_action_public_mapping(
        evidence, role="action evidence"
    )
    request_evidence.update(
        {
            "edge_id": edge.get("id"),
            "handler": handler,
            "public_command": public_command,
            "selector": selector,
        }
    )
    engine = _workflow_action_engine(
        state,
        bundle,
        edge,
        parameters,
        node_action=node_action,
    )
    action_id = exact_action.action_id
    revision = state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise _workflow_action_error(
            "TASK_STATE_INVALID",
            "catalog action requires an integer task revision",
        )
    preview_evaluation = engine.evaluate(
        state,
        expected_revision=revision,
        action_id=action_id,
        action_parameters=parameters,
        evidence=request_evidence,
        edge_id=str(edge.get("id")),
        action_outcome=exact_action,
        approval_outcome=exact_approval,
        preview=True,
        kernel_context=_workflow_action_kernel_context(
            state,
            bundle,
            edge,
            parameters,
            request_evidence,
            None,
            approval_intent_id=None,
        ),
    )
    _workflow_action_validate_receipt_candidate(
        preview_evaluation,
        verified_receipt,
        verified_journal,
        pre_effect_state=(
            receipt_context.pre_effect_state
            if (
                receipt_context is not None
                and receipt_context.neutralize_manager_nonce
            )
            else None
        ),
    )
    if preview:
        return preview_evaluation
    unreceipted_reconciliation_noop = False
    if allow_unreceipted_reconciliation_noop:
        effects = edge.get("effects")
        requested_effect_id = request_evidence.get("effect_id")
        target_effect = next(
            (
                effect
                for effect in effects
                if isinstance(effect, Mapping)
                and effect.get("id") == requested_effect_id
            ),
            None,
        ) if isinstance(effects, (list, tuple)) else None
        delta = exact_action.proposed_state_delta
        unreceipted_reconciliation_noop = (
            request_evidence.get("contract")
            in {
                (
                    "dev-flow-v3-workflow-action-abandonment-"
                    "evaluation/v1"
                ),
                (
                    "dev-flow-v3-workflow-action-compensated-"
                    "evaluation/v1"
                ),
            }
            and verified_receipt is None
            and verified_journal is None
            and isinstance(target_effect, Mapping)
            and "control.reconcile/v1"
            in tuple(target_effect.get("target_controls", ()))
            and not preview_evaluation.changed_paths
            and isinstance(delta, Mapping)
            and not delta.get("set")
            and not delta.get("remove")
            and not delta.get("operations")
        )
        if not unreceipted_reconciliation_noop:
            raise _workflow_action_error(
                "WORKFLOW_ACTION_RECONCILIATION_NOOP_INVALID",
                "unreceipted reconciliation requires one declared "
                "zero-delta target control",
                details={"edge_id": edge.get("id")},
            )
    if (
        _workflow_action_receipt_required(edge)
        and verified_journal is None
        and not unreceipted_reconciliation_noop
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_RECEIPT_REQUIRED",
            "side-effecting action is plan-only until a journal-verified "
            "receipt is supplied",
            details={
                "edge_id": edge.get("id"),
                "preview": _workflow_transition_public(
                    preview_evaluation.intent
                ),
            },
        )
    confirmation = edge.get("confirmation")
    confirmation_required = confirmation != "automatic"
    intent_id = str(preview_evaluation.intent["intent_id"])
    if confirmation_required and not isinstance(confirm_intent, str):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_INTENT_REQUIRED",
            "action confirmation requires the current catalog intent",
            details={
                "edge_id": edge.get("id"),
                "preview": _workflow_transition_public(
                    preview_evaluation.intent
                ),
            },
        )
    if (
        isinstance(confirm_intent, str)
        and not secrets.compare_digest(intent_id, confirm_intent)
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_INTENT_STALE",
            "confirmed action intent does not match current catalog evidence",
            details={
                "edge_id": edge.get("id"),
                "preview": _workflow_transition_public(
                    preview_evaluation.intent
                ),
            },
        )
    if exact_approval is not None:
        approval_intent = exact_approval.approval.get("intent_id")
        if approval_intent != intent_id:
            raise _workflow_action_error(
                "WORKFLOW_ACTION_APPROVAL_MISMATCH",
                "approval outcome is not bound to the current action intent",
                details={
                    "edge_id": edge.get("id"),
                    "expected_intent_id": intent_id,
                    "actual_intent_id": approval_intent,
                },
            )
    evaluation = engine.evaluate(
        state,
        expected_revision=revision,
        action_id=action_id,
        action_parameters=parameters,
        evidence=request_evidence,
        edge_id=str(edge.get("id")),
        action_outcome=exact_action,
        approval_outcome=exact_approval,
        confirm_intent=(
            confirm_intent
            if isinstance(confirm_intent, str)
            else None
        ),
        preview=False,
        kernel_context=_workflow_action_kernel_context(
            state,
            bundle,
            edge,
            parameters,
            request_evidence,
            exact_approval,
            approval_intent_id=(
                intent_id if exact_approval is not None else None
            ),
        ),
    )
    _workflow_action_validate_receipt_candidate(
        evaluation,
        verified_receipt,
        verified_journal,
        pre_effect_state=(
            receipt_context.pre_effect_state
            if (
                receipt_context is not None
                and receipt_context.neutralize_manager_nonce
            )
            else None
        ),
    )
    candidate = _workflow_transition_public(
        evaluation.candidate_state
    )
    if not isinstance(candidate, dict):
        raise _workflow_action_error(
            "TASK_STATE_INVALID",
            "catalog action produced a non-object task candidate",
        )
    try:
        validate_v3_task_state_against_bundle(candidate, bundle)
    except WorkflowStateError as exc:
        raise _workflow_action_error(
            exc.code, exc.message, details=exc.details
        ) from exc
    return evaluation


def evaluate_v3_node_action(
    state: Mapping[str, object],
    *,
    public_command: str,
    selector: str | None = None,
    action_outcome: ActionOutcome,
    approval_outcome: ApprovalOutcome | None = None,
    action_parameters: Mapping[str, object] | None = None,
    evidence: Mapping[str, object] | None = None,
    confirm_intent: str | None = None,
    preview: bool = False,
    receipt_context: WorkflowActionReceiptContext | None = None,
) -> TransitionEvaluation:
    """Evaluate one exact compiled same-node action without legacy fallback."""

    edge = resolve_v3_node_action_edge(
        state, public_command, selector=selector
    )
    bundle = _workflow_action_bundle(state)
    return _workflow_action_evaluate_selected(
        state,
        bundle,
        edge,
        node_action=True,
        public_command=public_command,
        selector=selector,
        edge_selector=None,
        action_outcome=action_outcome,
        approval_outcome=approval_outcome,
        action_parameters=action_parameters,
        evidence=evidence,
        confirm_intent=confirm_intent,
        preview=preview,
        receipt_context=receipt_context,
    )


def evaluate_v3_movement_action(
    state: Mapping[str, object],
    *,
    public_command: str,
    target: str,
    action_outcome: ActionOutcome,
    edge_selector: str | None = None,
    approval_outcome: ApprovalOutcome | None = None,
    action_parameters: Mapping[str, object] | None = None,
    evidence: Mapping[str, object] | None = None,
    confirm_intent: str | None = None,
    preview: bool = False,
    receipt_context: WorkflowActionReceiptContext | None = None,
) -> TransitionEvaluation:
    """Evaluate one exact transition/cancel movement through the same engine."""

    edge = resolve_v3_movement_action_edge(
        state,
        public_command,
        target=target,
        edge_selector=edge_selector,
    )
    bundle = _workflow_action_bundle(state)
    return _workflow_action_evaluate_selected(
        state,
        bundle,
        edge,
        node_action=False,
        public_command=public_command,
        selector=None,
        edge_selector=edge_selector,
        action_outcome=action_outcome,
        approval_outcome=approval_outcome,
        action_parameters=action_parameters,
        evidence=evidence,
        confirm_intent=confirm_intent,
        preview=preview,
        receipt_context=receipt_context,
    )


def _workflow_action_resolve_evaluation_edge(
    state: Mapping[str, object],
    evaluation: TransitionEvaluation,
) -> tuple[object, Mapping[str, object], Mapping[str, object]]:
    if type(evaluation) is not TransitionEvaluation:
        raise _workflow_action_error(
            "V3_ENGINE_EVALUATION_UNREGISTERED",
            "commit requires the exact kernel-issued action evaluation",
        )
    bundle = _workflow_action_bundle(state)
    edges = (
        *tuple(getattr(bundle, "movement_edges", ())),
        *tuple(getattr(bundle, "action_edges", ())),
    )
    matches = [
        edge
        for edge in edges
        if edge.get("id") == evaluation.edge_id
    ]
    if len(matches) != 1:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_EDGE_INVALID",
            "evaluation edge is absent from the pinned bundle",
            details={"edge_id": evaluation.edge_id},
        )
    edge = matches[0]
    parameters = evaluation.intent.get("action_parameters")
    if not isinstance(parameters, Mapping):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_REQUEST_INVALID",
            "evaluation has no catalog selection binding",
        )
    selection = parameters.get(_workflow_action_selection_parameter)
    if not isinstance(selection, Mapping):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_REQUEST_INVALID",
            "evaluation has no catalog selection binding",
        )
    kind = selection.get("kind")
    public_command = selection.get("public_command")
    if not isinstance(public_command, str):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_REQUEST_INVALID",
            "evaluation public command binding is invalid",
        )
    if kind == "node-action":
        selected = resolve_v3_node_action_edge(
            state,
            public_command,
            selector=(
                str(selection["selector"])
                if isinstance(selection.get("selector"), str)
                else None
            ),
        )
    elif kind == "movement":
        target = selection.get("target")
        if not isinstance(target, str):
            raise _workflow_action_error(
                "WORKFLOW_ACTION_REQUEST_INVALID",
                "movement evaluation target binding is invalid",
            )
        selected = resolve_v3_movement_action_edge(
            state,
            public_command,
            target=target,
            edge_selector=(
                str(selection["edge_selector"])
                if isinstance(selection.get("edge_selector"), str)
                else None
            ),
        )
    elif kind in {
        "preflight-completion",
        "node-action-completion",
    }:
        target = selection.get("target")
        selector = selection.get("selector")
        authorization_edge_id = selection.get(
            "authorization_action_edge_id"
        )
        completion_edge_id = selection.get("completion_edge_id")
        if (
            not isinstance(target, str)
            or not isinstance(authorization_edge_id, str)
            or not isinstance(completion_edge_id, str)
            or (
                selector is not None
                and not isinstance(selector, str)
            )
            or (
                kind == "preflight-completion"
                and (
                    public_command != "preflight"
                    or not isinstance(selector, str)
                )
            )
        ):
            raise _workflow_action_error(
                "WORKFLOW_ACTION_REQUEST_INVALID",
                "node-action completion selection is incomplete",
            )
        authorization_edge = resolve_v3_node_action_edge(
            state,
            public_command,
            selector=(
                selector if isinstance(selector, str) else None
            ),
        )
        completion_matches = [
            candidate
            for candidate in bundle.legal_movement_edges(
                str(state.get("status"))
            )
            if candidate.get("id") == completion_edge_id
            and candidate.get("target") == target
            and isinstance(candidate.get("trigger"), Mapping)
            and candidate["trigger"].get("kind") == "action"
            and candidate["trigger"].get("id") == public_command
        ]
        if (
            authorization_edge.get("id") != authorization_edge_id
            or len(completion_matches) != 1
            or (
                kind == "node-action-completion"
                and selection.get("canonical_event")
                != authorization_edge.get("canonical_event")
            )
        ):
            raise _workflow_action_error(
                "WORKFLOW_ACTION_JOURNAL_EDGE_ROLE_MISMATCH",
                "action completion does not bind both catalog edge roles",
                details={
                    "authorization_action_edge_id": (
                        authorization_edge_id
                    ),
                    "completion_edge_id": completion_edge_id,
                },
            )
        selected = completion_matches[0]
    else:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_REQUEST_INVALID",
            "evaluation catalog selection kind is invalid",
            details={"kind": kind},
        )
    trigger = selected.get("trigger")
    if (
        selected.get("id") != edge.get("id")
        or evaluation.source != state.get("status")
        or evaluation.source != edge.get("source")
        or evaluation.target != edge.get("target")
        or not isinstance(trigger, Mapping)
        or evaluation.intent.get("action_id") != trigger.get("id")
    ):
        raise _workflow_action_error(
            "V3_ENGINE_EVALUATION_MISMATCH",
            "evaluation does not bind the current exact pinned action edge",
            details={"edge_id": evaluation.edge_id},
        )
    return bundle, edge, selection


def _workflow_action_event_type(
    edge: Mapping[str, object],
    selection: Mapping[str, object],
) -> str:
    if edge.get("class") == "action":
        event_type = edge.get("canonical_event")
        if isinstance(event_type, str) and event_type:
            return event_type
        raise _workflow_action_error(
            "WORKFLOW_ACTION_EVENT_INVALID",
            "compiled action edge has no canonical audit event",
            details={"edge_id": edge.get("id")},
        )
    public_command = selection.get("public_command")
    if public_command == "cancel":
        return "task_cancelled"
    if public_command == "transition":
        return "state_transitioned"
    if selection.get("kind") == "preflight-completion":
        if public_command == "preflight":
            return "preflight_recorded"
    if selection.get("kind") == "node-action-completion":
        event_type = selection.get("canonical_event")
        if isinstance(event_type, str) and event_type:
            return event_type
    raise _workflow_action_error(
        "WORKFLOW_ACTION_EVENT_INVALID",
        "movement selector has no canonical event adapter",
        details={
            "edge_id": edge.get("id"),
            "public_command": public_command,
        },
    )


def _workflow_action_event_payload(
    evaluation: TransitionEvaluation,
    edge: Mapping[str, object],
    selection: Mapping[str, object],
    execution_binding: Mapping[str, object] | None = None,
) -> dict[str, object]:
    parameters = evaluation.intent.get("action_parameters")
    payload = {
        str(key): copy.deepcopy(_workflow_transition_public(value))
        for key, value in (
            parameters.items()
            if isinstance(parameters, Mapping)
            else ()
        )
        if key != _workflow_action_selection_parameter
    }
    payload.update(
        {
            "action_id": evaluation.intent.get("action_id"),
            "edge_id": edge.get("id"),
            "from": evaluation.source,
            "to": evaluation.target,
            "intent_id": evaluation.intent.get("intent_id"),
            "public_command": selection.get("public_command"),
            "selector": selection.get("selector"),
        }
    )
    if execution_binding is not None:
        execution_id = execution_binding.get("execution_id")
        receipt_sha256 = execution_binding.get("receipt_sha256")
        if (
            not isinstance(execution_id, str)
            or not execution_id
            or not isinstance(receipt_sha256, str)
            or not _workflow_catalog_sha256_re.fullmatch(
                receipt_sha256
            )
        ):
            raise _workflow_action_error(
                "WORKFLOW_ACTION_RECEIPT_INVALID",
                "action event execution binding is invalid",
            )
        payload["execution"] = {
            "schema": "dev-flow-v3-action-event-binding/v1",
            "execution_id": execution_id,
            "receipt_sha256": receipt_sha256,
        }
    return payload


def _workflow_action_commit_components(
    old_state: Mapping[str, object],
    evaluation: TransitionEvaluation,
    *,
    execution_binding: Mapping[str, object] | None = None,
) -> tuple[
    object,
    Mapping[str, object],
    Mapping[str, object],
    str,
    dict[str, object],
    tuple[tuple[str, dict[str, object]], ...],
]:
    bundle, edge, selection = _workflow_action_resolve_evaluation_edge(
        old_state, evaluation
    )
    event_type = _workflow_action_event_type(edge, selection)
    payload = _workflow_action_event_payload(
        evaluation,
        edge,
        selection,
        execution_binding=execution_binding,
    )
    additional_events = tuple(
        workflow_transition_audit_events(evaluation)
    )
    return (
        bundle,
        edge,
        selection,
        event_type,
        payload,
        additional_events,
    )


def _workflow_action_evaluation_binding(
    evaluation: TransitionEvaluation,
) -> dict[str, object]:
    return {
        "edge_id": evaluation.edge_id,
        "source": evaluation.source,
        "target": evaluation.target,
        "intent": _workflow_transition_public(evaluation.intent),
        "candidate_state_sha256": _sha256_contract(
            evaluation.candidate_state
        ),
        "changed_paths": list(evaluation.changed_paths),
        "guard_results": [
            {
                "guard_id": guard_id,
                "passed": result.passed,
                "evidence": _workflow_transition_public(
                    result.evidence
                ),
                "blockers": _workflow_transition_public(
                    result.blockers
                ),
            }
            for guard_id, result in evaluation.guard_results
        ],
        "audit_facts": [
            {
                "fact_type": fact.fact_type,
                "payload": _workflow_transition_public(fact.payload),
            }
            for fact in evaluation.audit_facts
        ],
    }


def workflow_action_engine_proof_binding_sha256(
    old_state: Mapping[str, object],
    evaluation: TransitionEvaluation,
    task_dir: object,
    verified_receipt: Mapping[str, object],
    *,
    execution_id: str,
) -> str:
    """Digest the exact one-shot proof binding without covering itself.

    The opaque proof and its process-private MAC are never serialized.  This
    digest binds the restart-stable semantic proof core; live lock
    capabilities are added and authenticated only by the process-private
    broker. The ``engine_proof_sha256`` field is excluded to avoid
    self-reference.
    """

    public_receipt = _workflow_action_public_mapping(
        verified_receipt, role="verified receipt"
    )
    required = {
        "receipt_sha256",
        "candidate_state_sha256",
        "event_batch_sha256",
        "engine_proof_sha256",
        "authorization_action_edge_id",
        "completion_edge_id",
    }
    if set(public_receipt) != required:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_RECEIPT_INVALID",
            "verified receipt does not match the exact commit schema",
        )
    receipt_core = {
        key: public_receipt[key]
        for key in (
            "receipt_sha256",
            "candidate_state_sha256",
            "event_batch_sha256",
            "authorization_action_edge_id",
            "completion_edge_id",
        )
    }
    if receipt_core["completion_edge_id"] != evaluation.edge_id:
        raise _workflow_action_error(
            "WORKFLOW_ACTION_RECEIPT_EDGE_ROLE_MISMATCH",
            "engine proof receipt does not bind its completion edge",
            details={"completion_edge_id": evaluation.edge_id},
        )
    (
        _bundle,
        _edge,
        _selection,
        event_type,
        payload,
        additional_events,
    ) = _workflow_action_commit_components(
        old_state,
        evaluation,
        execution_binding={
            "execution_id": execution_id,
            "receipt_sha256": receipt_core["receipt_sha256"],
        },
    )
    task_directory = Path(task_dir).resolve(strict=True)
    resolution = resolve_loaded_task_workflow(
        old_state, purpose="mutation"
    )
    workflow_ref = _workflow_transition_public(
        old_state.get("workflow_ref", {})
    )
    if (
        not isinstance(resolution, Mapping)
        or not isinstance(resolution.get("bundle_sha256"), str)
        or not isinstance(workflow_ref, dict)
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_RECEIPT_INVALID",
            "engine proof binding cannot resolve the pinned workflow",
        )
    observed = {
        "contract": _workflow_action_engine_proof_binding_contract,
        "task_directory": {
            "path": str(task_directory),
            "identity": _serializable_path_identity(task_directory),
        },
        "task": {
            "task_id": old_state.get("task_id"),
            "schema_version": old_state.get("schema_version"),
            "expected_revision": old_state.get("revision"),
        },
        "workflow": {
            "workflow_ref": workflow_ref,
            "resolved_bundle_sha256": resolution["bundle_sha256"],
        },
        "old_state_sha256": _sha256_contract(old_state),
        "candidate_state_sha256": _sha256_contract(
            evaluation.candidate_state
        ),
        "event_batch": _workflow_transition_event_batch_binding(
            event_type,
            payload,
            additional_events,
            event_ids=None,
            transaction_id=None,
        ),
        "verified_receipt": receipt_core,
    }
    return semantic_sha256(
        _workflow_action_engine_proof_binding_domain,
        {
            **observed,
            "evaluation": _workflow_action_evaluation_binding(
                evaluation
            ),
        },
    )


def build_v3_workflow_action_receipt(
    old_state: Mapping[str, object],
    evaluation: TransitionEvaluation,
    task_dir: object,
    *,
    execution_id: str,
    effect_receipt_sha256: str,
    authorization_action_edge_id: str | None = None,
    completion_edge_id: str | None = None,
) -> dict[str, object]:
    """Build the exact journal receipt for one already observed execution."""

    if (
        not isinstance(effect_receipt_sha256, str)
        or not _workflow_catalog_sha256_re.fullmatch(
            effect_receipt_sha256
        )
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_RECEIPT_INVALID",
            "effect receipt identity must be lowercase SHA-256",
        )
    if (
        authorization_action_edge_id is None
        and completion_edge_id is None
    ):
        authorization_action_edge_id = evaluation.edge_id
        completion_edge_id = evaluation.edge_id
    if (
        not isinstance(authorization_action_edge_id, str)
        or not authorization_action_edge_id
        or not isinstance(completion_edge_id, str)
        or not completion_edge_id
        or completion_edge_id != evaluation.edge_id
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_RECEIPT_EDGE_ROLE_MISMATCH",
            "receipt requires exact authorization and completion edge roles",
            details={"completion_edge_id": evaluation.edge_id},
        )
    (
        _bundle,
        _edge,
        _selection,
        event_type,
        payload,
        additional_events,
    ) = _workflow_action_commit_components(
        old_state,
        evaluation,
        execution_binding={
            "execution_id": execution_id,
            "receipt_sha256": effect_receipt_sha256,
        },
    )
    event_batch = _workflow_transition_event_batch_binding(
        event_type,
        payload,
        additional_events,
        event_ids=None,
        transaction_id=None,
    )
    receipt = {
        "receipt_sha256": effect_receipt_sha256,
        "candidate_state_sha256": _sha256_contract(
            evaluation.candidate_state
        ),
        "event_batch_sha256": _sha256_contract(event_batch),
        "engine_proof_sha256": "0" * 64,
        "authorization_action_edge_id": (
            authorization_action_edge_id
        ),
        "completion_edge_id": completion_edge_id,
    }
    receipt["engine_proof_sha256"] = (
        workflow_action_engine_proof_binding_sha256(
            old_state,
            evaluation,
            task_dir,
            receipt,
            execution_id=execution_id,
        )
    )
    return receipt


def commit_v3_workflow_action(
    old_state: dict[str, object],
    evaluation: TransitionEvaluation,
    task_dir: object,
    *,
    receipt_context: WorkflowActionReceiptContext | None = None,
) -> dict[str, object]:
    """Commit one exact action evaluation through proof-backed raw storage."""

    (
        bundle,
        edge,
        selection,
        event_type,
        payload,
        additional_events,
    ) = _workflow_action_commit_components(old_state, evaluation)
    verified_receipt, verified_journal = (
        _workflow_action_verified_journal_receipt(
            old_state, bundle, edge, receipt_context
        )
    )
    if verified_receipt is not None:
        if (
            not isinstance(verified_journal, Mapping)
            or not isinstance(
                verified_journal.get("execution_id"), str
            )
        ):
            raise _workflow_action_error(
                "WORKFLOW_ACTION_JOURNAL_CONTEXT_INVALID",
                "verified receipt has no bound execution identity",
            )
        (
            bundle,
            edge,
            selection,
            event_type,
            payload,
            additional_events,
        ) = _workflow_action_commit_components(
            old_state,
            evaluation,
            execution_binding={
                "execution_id": verified_journal["execution_id"],
                "receipt_sha256": verified_receipt[
                    "receipt_sha256"
                ],
            },
        )
    if (
        _workflow_action_receipt_required(edge)
        and verified_journal is None
    ):
        raise _workflow_action_error(
            "WORKFLOW_ACTION_RECEIPT_REQUIRED",
            "side-effecting action cannot commit without its verified receipt",
            details={"edge_id": edge.get("id")},
        )
    _workflow_action_validate_receipt_candidate(
        evaluation,
        verified_receipt,
        verified_journal,
        pre_effect_state=(
            receipt_context.pre_effect_state
            if (
                receipt_context is not None
                and receipt_context.neutralize_manager_nonce
            )
            else None
        ),
    )
    candidate = copy.deepcopy(
        _workflow_transition_public(evaluation.candidate_state)
    )
    if not isinstance(candidate, dict):
        raise _workflow_action_error(
            "TASK_STATE_INVALID",
            "engine action candidate must be an object",
        )
    manager_registry_operation = None
    if event_type in {
        MANAGER_CAPABILITY_ISSUED_EVENT,
        MANAGER_CAPABILITY_REVOKED_EVENT,
    }:
        parameters = evaluation.intent.get("action_parameters")
        operation = (
            parameters.get("operation")
            if isinstance(parameters, Mapping)
            else None
        )
        expected_operation = (
            "authorize"
            if event_type == MANAGER_CAPABILITY_ISSUED_EVENT
            else "revoke"
        )
        verifier = (
            parameters.get("verifier")
            if isinstance(parameters, Mapping)
            else None
        )
        if (
            not isinstance(parameters, Mapping)
            or operation != expected_operation
            or parameters.get("authority") != "operator"
            or not isinstance(verifier, Mapping)
        ):
            raise _workflow_action_error(
                "MANAGER_REGISTRY_AUTHORIZATION_INVALID",
                "operator registry action lacks its exact engine binding",
            )
        try:
            parsed_verifier = validate_manager_capability_verifier(
                verifier
            )
            expected_candidate, manager_registry_operation = (
                _manager_registry_candidate(
                    dict(old_state),
                    operation=expected_operation,
                    verifier=parsed_verifier,
                )
            )
        except (FlowError, OrchestrationAuthorityError) as exc:
            raise _workflow_action_error(
                getattr(
                    exc,
                    "code",
                    "MANAGER_REGISTRY_AUTHORIZATION_INVALID",
                ),
                str(
                    getattr(
                        exc,
                        "message",
                        "operator registry action is invalid",
                    )
                ),
                details=getattr(exc, "details", {}),
            ) from exc
        if _sha256_contract(expected_candidate) != _sha256_contract(
            candidate
        ):
            raise _workflow_action_error(
                "MANAGER_REGISTRY_AUTHORIZATION_STALE",
                "operator registry action differs from its engine candidate",
            )
    if verified_receipt is not None:
        event_batch = _workflow_transition_event_batch_binding(
            event_type,
            payload,
            additional_events,
            event_ids=None,
            transaction_id=None,
        )
        if verified_receipt.get(
            "event_batch_sha256"
        ) != _sha256_contract(event_batch):
            raise _workflow_action_error(
                "WORKFLOW_ACTION_JOURNAL_EVENT_MISMATCH",
                "verified journal receipt does not bind the commit event batch",
                details={"edge_id": edge.get("id")},
            )
        expected_engine_binding = (
            workflow_action_engine_proof_binding_sha256(
                old_state,
                evaluation,
                task_dir,
                verified_receipt,
                execution_id=str(verified_journal["execution_id"]),
            )
        )
        if verified_receipt.get(
            "engine_proof_sha256"
        ) != expected_engine_binding:
            raise _workflow_action_error(
                "WORKFLOW_ACTION_JOURNAL_PROOF_MISMATCH",
                "verified journal receipt does not bind the one-shot "
                "engine proof core",
                details={"edge_id": edge.get("id")},
            )
    if (
        manager_registry_operation is not None
        or selection.get("public_command") == "orchestration"
    ):
        _commit_state(
            old_state,
            candidate,
            task_dir,
            event_type,
            payload,
            additional_events=additional_events,
            _manager_registry_operation=manager_registry_operation,
            _engine_commit_evaluation=evaluation,
            _verified_receipt=verified_receipt,
        )
    else:
        proof = _workflow_transition_mint_engine_commit_proof(
            old_state,
            evaluation,
            task_dir,
            event_type,
            payload,
            additional_events=additional_events,
            verified_receipt=verified_receipt,
        )
        _persist_state_transaction(
            old_state,
            candidate,
            task_dir,
            event_type,
            payload,
            additional_events=additional_events,
            _engine_commit_proof=proof,
            _verified_receipt=verified_receipt,
        )
    return candidate
