# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: V4-only policy and versioned execution/recovery bindings.
from __future__ import annotations


def _v4_dispatch_executor(request: object, capabilities: object) -> object:
    """Authorize dispatch only after the durable V4 claim is contained."""

    if capabilities != ():
        raise ValueError("V4 dispatch accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 dispatch request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "dispatch"
        or request.get("claim_phase") != "CLAIMED"
        or request.get("containment_phase") != "SPAWN_PENDING"
        or request.get("single_dispatch") is not True
    ):
        raise ValueError("V4 dispatch request is not durably authorized")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "dispatch",
        "authorized": True,
    }


def _v4_observation_executor(
    request: object, capabilities: object
) -> object:
    """Authorize observation without granting redispatch authority."""

    if capabilities != ():
        raise ValueError("V4 observation accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 observation request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "observation"
        or request.get("redispatch") is not False
        or request.get("target_bound") is not True
    ):
        raise ValueError("V4 observation request is not target-bound")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "observation",
        "authorized": True,
    }


def _v4_settlement_executor(
    request: object, capabilities: object
) -> object:
    """Authorize settlement only for a verified durable receipt."""

    if capabilities != ():
        raise ValueError("V4 settlement accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 settlement request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "settlement"
        or request.get("receipt_verified") is not True
        or request.get("fresh_authority") is not True
    ):
        raise ValueError("V4 settlement request lacks verified authority")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "settlement",
        "authorized": True,
    }


def _v4_reattachment_executor(
    request: object, capabilities: object
) -> object:
    """Authorize authenticated observe-only reattachment."""

    if capabilities != ():
        raise ValueError("V4 reattachment accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 reattachment request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "reattachment"
        or request.get("authenticated_live_handle") is not True
        or request.get("redispatch") is not False
    ):
        raise ValueError("V4 reattachment is not authenticated observe-only")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "reattachment",
        "authorized": True,
    }


def _v4_control_executor(request: object, capabilities: object) -> object:
    """Authorize a target-bound control operation."""

    if capabilities != ():
        raise ValueError("V4 control accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 control request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "control"
        or request.get("target_bound") is not True
        or request.get("fresh_authority") is not True
    ):
        raise ValueError("V4 control request lacks fresh target authority")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "control",
        "authorized": True,
    }


def _v4_accepted_executor(request: object, capabilities: object) -> object:
    """Authorize ACCEPTED only from a stored verified receipt."""

    if capabilities != ():
        raise ValueError("V4 accepted accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 accepted request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "accepted"
        or request.get("stored_receipt_verified") is not True
        or request.get("fresh_authority") is not True
    ):
        raise ValueError("V4 ACCEPTED lacks a verified stored receipt")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "accepted",
        "authorized": True,
    }


def _v4_abandoned_executor(request: object, capabilities: object) -> object:
    """Authorize ABANDONED only from controller-owned live evidence."""

    if capabilities != ():
        raise ValueError("V4 abandoned accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 abandoned request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "abandoned"
        or request.get("controller_owned_live_evidence") is not True
        or request.get("target_bound") is not True
        or request.get("no_business_outcome") is not True
    ):
        raise ValueError("V4 ABANDONED lacks controller-owned live evidence")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "abandoned",
        "authorized": True,
    }


def _v4_unresolved_executor(request: object, capabilities: object) -> object:
    """Authorize fail-closed UNRESOLVED quarantine."""

    if capabilities != ():
        raise ValueError("V4 unresolved accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 unresolved request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "unresolved"
        or request.get("scope_blocked") is not True
        or request.get("redispatch") is not False
    ):
        raise ValueError("V4 UNRESOLVED must remain blocked")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "unresolved",
        "authorized": True,
    }


def _v4_compensation_executor(
    request: object, capabilities: object
) -> object:
    """Authorize compensation only after both independent gates."""

    if capabilities != ():
        raise ValueError("V4 compensation accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 compensation request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "compensation"
        or request.get("workflow_gate_verified") is not True
        or request.get("opaque_host_grant_consumed") is not True
        or request.get("new_execution") is not True
    ):
        raise ValueError("V4 compensation lacks independent authorization")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "compensation",
        "authorized": True,
    }


def _v4_containment_executor(
    request: object, capabilities: object
) -> object:
    """Authorize containment after its durable cross-link is stored."""

    if capabilities != ():
        raise ValueError("V4 containment accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 containment request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "containment"
        or request.get("durable_crosslink") is not True
        or request.get("target_bound") is not True
    ):
        raise ValueError("V4 containment lacks a durable target cross-link")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "containment",
        "authorized": True,
    }


def _v4_archive_executor(request: object, capabilities: object) -> object:
    """Authorize archive only after terminal state and index closure."""

    if capabilities != ():
        raise ValueError("V4 archive accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 archive request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "archive"
        or request.get("terminal") is not True
        or request.get("index_closed") is not True
    ):
        raise ValueError("V4 archive request is not terminal and closed")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "archive",
        "authorized": True,
    }


def _v4_unblock_executor(request: object, capabilities: object) -> object:
    """Authorize unblock only after terminal reconciliation is committed."""

    if capabilities != ():
        raise ValueError("V4 unblock accepts no ambient capabilities")
    if not isinstance(request, dict):
        raise ValueError("V4 unblock request must be an object")
    if (
        request.get("schema") != "dev-flow-v4-handler-request/v1"
        or request.get("role") != "unblock"
        or request.get("terminal_reconciliation") is not True
        or request.get("archive_verified") is not True
    ):
        raise ValueError("V4 unblock lacks terminal reconciliation")
    return {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": "unblock",
        "authorized": True,
    }


def _workflow_v4_handler_callables(
    state_value: dict[str, object],
    action_id: str,
) -> dict[str, object]:
    """Resolve the complete executable closure from the exact task pin."""

    try:
        bundle = _workflow_transition_bundle(state_value)
    except TransitionEngineError as exc:
        raise WorkflowStateError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if getattr(bundle, "workflow_version", None) != 4:
        raise WorkflowStateError(
            "WORKFLOW_HANDLER_CLOSURE_INVALID",
            "V4 handler closure requires an exact V4 bundle",
        )
    services = workflow_runtime_services()
    declared_indirect_actions = set(manager_command_action_ids_v1())
    orchestration = getattr(
        bundle, "repository_orchestration", None
    )
    if isinstance(orchestration, Mapping):
        declared_indirect_actions.update(
            item
            for item in orchestration.get("operation_ids", ())
            if isinstance(item, str)
        )
    for edge in bundle.edges:
        if isinstance(edge.get("id"), str):
            declared_indirect_actions.add(edge["id"])
        trigger = edge.get("trigger")
        if (
            isinstance(trigger, Mapping)
            and isinstance(trigger.get("id"), str)
        ):
            declared_indirect_actions.add(trigger["id"])
    for edge in bundle.action_edges:
        public_command = edge.get("public_command")
        if (
            isinstance(public_command, Mapping)
            and isinstance(public_command.get("id"), str)
        ):
            declared_indirect_actions.add(public_command["id"])
        for effect in edge.get("effects", ()):
            if not isinstance(effect, Mapping):
                continue
            declared_indirect_actions.update(
                item
                for item in effect.get("target_controls", ())
                if isinstance(item, str)
            )
    resolved: dict[str, object] = {}
    for role in (
        "abandoned",
        "accepted",
        "archive",
        "compensation",
        "containment",
        "control",
        "dispatch",
        "observation",
        "reattachment",
        "settlement",
        "unblock",
        "unresolved",
    ):
        try:
            try:
                reference = bundle.resolve_action_handler(
                    action_id, role
                )
            except WorkflowCatalogError:
                if action_id not in declared_indirect_actions:
                    raise
                candidates = {
                    bundle.resolve_action_handler(
                        str(edge["trigger"]["id"]), role
                    )
                    for edge in bundle.action_edges
                    if isinstance(edge.get("trigger"), Mapping)
                    and isinstance(
                        edge["trigger"].get("id"), str
                    )
                }
                if len(candidates) != 1:
                    raise WorkflowCatalogError(
                        "WORKFLOW_HANDLER_CLOSURE_INVALID",
                        "V4 indirect action has no unique bundle-wide handler",
                        details={
                            "action_id": action_id,
                            "role": role,
                            "match_count": len(candidates),
                        },
                    )
                reference = next(iter(candidates))
            implementation = (
                services.handler_resolver.resolve_callable(
                    reference.registry,
                    reference.identifier,
                    reference.version,
                    "dispatcher",
                )
            )
        except (
            WorkflowCatalogError,
            WorkflowHandlerAuditError,
            WorkflowRegistryError,
        ) as exc:
            raise WorkflowStateError(
                "WORKFLOW_HANDLER_CLOSURE_INVALID",
                (
                    "V4 action lacks one exact executable handler closure: "
                    + action_id
                ),
                details={
                    "action_id": action_id,
                    "role": role,
                    "cause": getattr(exc, "code", type(exc).__name__),
                },
            ) from exc
        if (
            not callable(implementation)
            or implementation is _disabled_executor_dispatch
        ):
            raise WorkflowStateError(
                "WORKFLOW_HANDLER_CLOSURE_INVALID",
                "V4 action handler closure contains a disabled target",
                details={"action_id": action_id, "role": role},
            )
        resolved[role] = implementation
    return resolved


def _workflow_v4_handler_authorize(
    implementation: object,
    role: str,
    fields: dict[str, object],
) -> None:
    """Invoke one frozen pure handler and require its exact grant."""

    if not callable(implementation):
        raise WorkflowStateError(
            "WORKFLOW_HANDLER_CLOSURE_INVALID",
            "V4 handler target is not callable",
            details={"role": role},
        )
    result = implementation(
        {
            "schema": "dev-flow-v4-handler-request/v1",
            "role": role,
            **fields,
        },
        (),
    )
    if result != {
        "schema": "dev-flow-v4-handler-result/v1",
        "role": role,
        "authorized": True,
    }:
        raise WorkflowStateError(
            "WORKFLOW_HANDLER_AUTHORIZATION_REJECTED",
            "V4 handler did not return its exact authorization result",
            details={"role": role},
        )


def _workflow_v4_manager_default_actions(
    state_value: dict[str, object],
) -> tuple[str, ...]:
    """Project manager actions from the task-pinned V4 bundle."""

    try:
        bundle = _workflow_transition_bundle(state_value)
    except TransitionEngineError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if getattr(bundle, "workflow_version", None) != 4:
        raise FlowError(
            "MANAGER_CAPABILITY_WORKFLOW_INVALID",
            "V4 manager capability projection requires a pinned V4 bundle",
        )
    graph = getattr(bundle, "graph", None)
    if not isinstance(graph, Mapping):
        raise FlowError(
            "MANAGER_CAPABILITY_WORKFLOW_INVALID",
            "pinned V4 workflow graph is unavailable",
        )
    actions = {
        action["id"]
        for node in graph.get("nodes", ())
        if isinstance(node, Mapping)
        for action in node.get("actions", ())
        if isinstance(action, Mapping)
        and isinstance(action.get("id"), str)
    }
    actions.update(
        trigger["id"]
        for edge in graph.get("edge_policies", ())
        if isinstance(edge, Mapping)
        for trigger in (edge.get("trigger"),)
        if isinstance(trigger, Mapping)
        and isinstance(trigger.get("id"), str)
    )
    orchestration = graph.get("repository_orchestration")
    if isinstance(orchestration, Mapping):
        actions.update(
            item
            for item in orchestration.get("operation_ids", ())
            if isinstance(item, str)
        )
        for field in ("map", "join"):
            operation = orchestration.get(field)
            if (
                isinstance(operation, Mapping)
                and isinstance(operation.get("operation_id"), str)
            ):
                actions.add(operation["operation_id"])
    actions.update(manager_command_action_ids_v1())
    return tuple(
        sorted(actions, key=lambda item: item.encode("utf-8"))
    )


def install_v4_runtime_policy(
    namespace: dict[str, object],
) -> None:
    """Install V4-only behavior after the sealed runtime is available."""

    if not isinstance(namespace, dict):
        raise WorkflowStateError(
            "WORKFLOW_RUNTIME_NAMESPACE_INVALID",
            "V4 runtime policy requires the shared module namespace",
        )
    original = namespace.get("_manager_default_actions")
    if not callable(original):
        raise WorkflowStateError(
            "WORKFLOW_RUNTIME_NAMESPACE_INVALID",
            "manager capability projection boundary is unavailable",
        )
    if getattr(original, "_dev_flow_v4_wrapper", False):
        return

    def manager_default_actions_with_v4(
        state_value: dict[str, object],
    ) -> tuple[str, ...]:
        reference = state_value.get("workflow_ref")
        if (
            state_value.get("schema_version")
            == V3_TASK_SCHEMA_VERSION
            and isinstance(reference, Mapping)
            and reference.get("version") == 4
        ):
            return _workflow_v4_manager_default_actions(state_value)
        return original(state_value)

    manager_default_actions_with_v4._dev_flow_v4_wrapper = True
    manager_default_actions_with_v4.__name__ = (
        "_manager_default_actions"
    )
    namespace["_manager_default_actions"] = (
        manager_default_actions_with_v4
    )

    original_transaction = namespace.get(
        "execute_v3_workflow_action_transaction"
    )
    if not callable(original_transaction):
        raise WorkflowStateError(
            "WORKFLOW_RUNTIME_NAMESPACE_INVALID",
            "workflow action transaction boundary is unavailable",
        )
    if not getattr(
        original_transaction, "_dev_flow_v4_wrapper", False
    ):
        def execute_workflow_action_transaction_with_v4(
            state_value: dict[str, object],
            task_dir: object,
            invocation: object,
            **keyword_arguments: object,
        ) -> object:
            reference = state_value.get("workflow_ref")
            if not (
                state_value.get("schema_version")
                == V3_TASK_SCHEMA_VERSION
                and isinstance(reference, Mapping)
                and reference.get("version") == 4
            ):
                return original_transaction(
                    state_value,
                    task_dir,
                    invocation,
                    **keyword_arguments,
                )
            outcome = getattr(invocation, "action_outcome", None)
            action_id = getattr(outcome, "action_id", None)
            if not isinstance(action_id, str) or not action_id:
                raise WorkflowStateError(
                    "WORKFLOW_HANDLER_CLOSURE_INVALID",
                    "V4 transaction lacks an exact action identity",
                )
            handlers = _workflow_v4_handler_callables(
                state_value, action_id
            )
            arguments = dict(keyword_arguments)
            dispatcher = arguments.get("dispatcher")
            observer = arguments.get("observer")

            if callable(dispatcher):
                def dispatch_with_v4(context: object) -> object:
                    _workflow_v4_handler_authorize(
                        handlers["containment"],
                        "containment",
                        {
                            "durable_crosslink": True,
                            "target_bound": True,
                        },
                    )
                    _workflow_v4_handler_authorize(
                        handlers["dispatch"],
                        "dispatch",
                        {
                            "claim_phase": "CLAIMED",
                            "containment_phase": "SPAWN_PENDING",
                            "single_dispatch": True,
                        },
                    )
                    observed = dispatcher(context)
                    if type(observed) is WorkflowActionEffectObservation:
                        _workflow_v4_handler_authorize(
                            handlers["observation"],
                            "observation",
                            {
                                "redispatch": False,
                                "target_bound": True,
                            },
                        )
                    return observed

                arguments["dispatcher"] = dispatch_with_v4

            if callable(observer):
                def observe_with_v4(context: object) -> object:
                    observed = observer(context)
                    _workflow_v4_handler_authorize(
                        handlers["observation"],
                        "observation",
                        {
                            "redispatch": False,
                            "target_bound": True,
                        },
                    )
                    return observed

                arguments["observer"] = observe_with_v4

            if arguments.get("target_execution_id") is not None:
                _workflow_v4_handler_authorize(
                    handlers["control"],
                    "control",
                    {
                        "target_bound": True,
                        "fresh_authority": True,
                    },
                )

            result = original_transaction(
                state_value,
                task_dir,
                invocation,
                **arguments,
            )
            if getattr(result, "status", None) in {
                "COMMITTED",
                "RECOVERED_COMMITTED",
            }:
                _workflow_v4_handler_authorize(
                    handlers["settlement"],
                    "settlement",
                    {
                        "receipt_verified": True,
                        "fresh_authority": True,
                    },
                )
            if getattr(result, "archive_path", None) is not None:
                _workflow_v4_handler_authorize(
                    handlers["archive"],
                    "archive",
                    {
                        "terminal": True,
                        "index_closed": True,
                    },
                )
            return result

        execute_workflow_action_transaction_with_v4._dev_flow_v4_wrapper = (
            True
        )
        execute_workflow_action_transaction_with_v4.__name__ = (
            "execute_v3_workflow_action_transaction"
        )
        namespace["execute_v3_workflow_action_transaction"] = (
            execute_workflow_action_transaction_with_v4
        )

    original_recovery = namespace.get(
        "recover_v3_workflow_action_transaction"
    )
    if not callable(original_recovery):
        raise WorkflowStateError(
            "WORKFLOW_RUNTIME_NAMESPACE_INVALID",
            "workflow action recovery boundary is unavailable",
        )
    if not getattr(original_recovery, "_dev_flow_v4_wrapper", False):
        def recover_workflow_action_transaction_with_v4(
            task_dir: object,
            execution_id: str,
            **keyword_arguments: object,
        ) -> object:
            task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
            state_value = load_state(task_path / "state.json")
            reference = state_value.get("workflow_ref")
            if not (
                state_value.get("schema_version")
                == V3_TASK_SCHEMA_VERSION
                and isinstance(reference, Mapping)
                and reference.get("version") == 4
            ):
                return original_recovery(
                    task_dir,
                    execution_id,
                    **keyword_arguments,
                )

            arguments = dict(keyword_arguments)
            live_authenticator = arguments.get(
                "live_runtime_authenticator"
            )
            resolved_handlers: dict[str, object] | None = None
            resolved_action_id: str | None = None

            def handlers_for_journal(
                journal: object,
            ) -> dict[str, object]:
                nonlocal resolved_handlers, resolved_action_id
                plan = (
                    journal.get("plan")
                    if isinstance(journal, Mapping)
                    else None
                )
                action_id = (
                    plan.get("action_id")
                    if isinstance(plan, Mapping)
                    else None
                )
                if not isinstance(action_id, str) or not action_id:
                    bindings = (
                        journal.get("bindings")
                        if isinstance(journal, Mapping)
                        else None
                    )
                    edge_id = (
                        bindings.get(
                            "authorization_action_edge_id"
                        )
                        if isinstance(bindings, Mapping)
                        else None
                    )
                    bundle = _workflow_transition_bundle(
                        state_value
                    )
                    matches = [
                        edge
                        for edge in bundle.action_edges
                        if edge.get("id") == edge_id
                    ]
                    trigger = (
                        matches[0].get("trigger")
                        if len(matches) == 1
                        else None
                    )
                    action_id = (
                        trigger.get("id")
                        if isinstance(trigger, Mapping)
                        else None
                    )
                if not isinstance(action_id, str) or not action_id:
                    raise WorkflowStateError(
                        "WORKFLOW_HANDLER_CLOSURE_INVALID",
                        "V4 recovery journal lacks an exact action identity",
                    )
                if (
                    resolved_handlers is None
                    or resolved_action_id != action_id
                ):
                    resolved_handlers = _workflow_v4_handler_callables(
                        state_value, action_id
                    )
                    resolved_action_id = action_id
                return resolved_handlers

            if callable(live_authenticator):
                def authenticate_live_with_v4(
                    journal: object,
                    containment: object,
                    binding: object,
                ) -> bool:
                    authenticated = live_authenticator(
                        journal, containment, binding
                    )
                    if authenticated is not True:
                        return False
                    handlers = handlers_for_journal(journal)
                    _workflow_v4_handler_authorize(
                        handlers["reattachment"],
                        "reattachment",
                        {
                            "authenticated_live_handle": True,
                            "redispatch": False,
                        },
                    )
                    return True

                arguments["live_runtime_authenticator"] = (
                    authenticate_live_with_v4
                )

            result = original_recovery(
                task_dir,
                execution_id,
                **arguments,
            )
            journal = getattr(result, "journal", None)
            status = getattr(result, "status", None)
            if isinstance(journal, Mapping):
                handlers = handlers_for_journal(journal)
                if status == "QUARANTINE_REQUIRED":
                    _workflow_v4_handler_authorize(
                        handlers["unresolved"],
                        "unresolved",
                        {
                            "scope_blocked": True,
                            "redispatch": False,
                        },
                    )
                if status == "RECOVERED_COMMITTED":
                    _workflow_v4_handler_authorize(
                        handlers["accepted"],
                        "accepted",
                        {
                            "stored_receipt_verified": True,
                            "fresh_authority": True,
                        },
                    )
                    _workflow_v4_handler_authorize(
                        handlers["settlement"],
                        "settlement",
                        {
                            "receipt_verified": True,
                            "fresh_authority": True,
                        },
                    )
                if getattr(result, "archive_path", None) is not None:
                    _workflow_v4_handler_authorize(
                        handlers["archive"],
                        "archive",
                        {
                            "terminal": True,
                            "index_closed": True,
                        },
                    )
            return result

        recover_workflow_action_transaction_with_v4._dev_flow_v4_wrapper = (
            True
        )
        recover_workflow_action_transaction_with_v4.__name__ = (
            "recover_v3_workflow_action_transaction"
        )
        namespace["recover_v3_workflow_action_transaction"] = (
            recover_workflow_action_transaction_with_v4
        )

    original_reconciliation = namespace.get(
        "reconcile_v3_workflow_action_quarantine"
    )
    if not callable(original_reconciliation):
        raise WorkflowStateError(
            "WORKFLOW_RUNTIME_NAMESPACE_INVALID",
            "workflow action reconciliation boundary is unavailable",
        )
    if not getattr(
        original_reconciliation, "_dev_flow_v4_wrapper", False
    ):
        def reconcile_workflow_action_quarantine_with_v4(
            task_dir: object,
            request: object,
            **keyword_arguments: object,
        ) -> object:
            if getattr(request, "workflow_version", None) != "4":
                return original_reconciliation(
                    task_dir,
                    request,
                    **keyword_arguments,
                )
            task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
            state_value = load_state(task_path / "state.json")
            bundle = _workflow_transition_bundle(state_value)
            edge_id = getattr(request, "action_edge_id", None)
            matches = [
                edge
                for edge in bundle.action_edges
                if edge.get("id") == edge_id
            ]
            trigger = (
                matches[0].get("trigger")
                if len(matches) == 1
                else None
            )
            action_id = (
                trigger.get("id")
                if isinstance(trigger, Mapping)
                else None
            )
            if not isinstance(action_id, str) and isinstance(
                edge_id, str
            ):
                action_id = edge_id
            if not isinstance(action_id, str) or not action_id:
                raise WorkflowStateError(
                    "WORKFLOW_HANDLER_CLOSURE_INVALID",
                    "V4 reconciliation target lacks an exact action identity",
                )
            handlers = _workflow_v4_handler_callables(
                state_value, action_id
            )
            _workflow_v4_handler_authorize(
                handlers["containment"],
                "containment",
                {
                    "durable_crosslink": True,
                    "target_bound": True,
                },
            )
            result = original_reconciliation(
                task_dir,
                request,
                **keyword_arguments,
            )
            status = getattr(result, "status", None)
            if status == "ACCEPTED":
                _workflow_v4_handler_authorize(
                    handlers["accepted"],
                    "accepted",
                    {
                        "stored_receipt_verified": True,
                        "fresh_authority": True,
                    },
                )
            elif status == "ABANDONED":
                _workflow_v4_handler_authorize(
                    handlers["abandoned"],
                    "abandoned",
                    {
                        "controller_owned_live_evidence": True,
                        "target_bound": True,
                        "no_business_outcome": True,
                    },
                )
            elif status == "COMPENSATED":
                _workflow_v4_handler_authorize(
                    handlers["compensation"],
                    "compensation",
                    {
                        "workflow_gate_verified": True,
                        "opaque_host_grant_consumed": True,
                        "new_execution": True,
                    },
                )
            elif status == "UNRESOLVED":
                _workflow_v4_handler_authorize(
                    handlers["unresolved"],
                    "unresolved",
                    {
                        "scope_blocked": True,
                        "redispatch": False,
                    },
                )
            if getattr(result, "archive_path", None) is not None:
                _workflow_v4_handler_authorize(
                    handlers["archive"],
                    "archive",
                    {
                        "terminal": True,
                        "index_closed": True,
                    },
                )
                _workflow_v4_handler_authorize(
                    handlers["unblock"],
                    "unblock",
                    {
                        "terminal_reconciliation": True,
                        "archive_verified": True,
                    },
                )
            return result

        reconcile_workflow_action_quarantine_with_v4._dev_flow_v4_wrapper = (
            True
        )
        reconcile_workflow_action_quarantine_with_v4.__name__ = (
            "reconcile_v3_workflow_action_quarantine"
        )
        namespace["reconcile_v3_workflow_action_quarantine"] = (
            reconcile_workflow_action_quarantine_with_v4
        )
