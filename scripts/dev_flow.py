#!/usr/bin/env python3
"""A deterministic, local control plane for Codex development work.

The module intentionally depends only on Python's standard library.  Every
normal CLI response (including errors) is one JSON object on stdout so hooks
and skills do not need to scrape prose.
"""

from __future__ import annotations

from pathlib import Path as _DevFlowBootstrapPath
import sys as _DevFlowBootstrapSys
import types as _DevFlowBootstrapTypes

# ``importlib.util.module_from_spec(...); loader.exec_module(module)`` does not
# itself register ``module`` in ``sys.modules``. Python 3.9's dataclass
# decorator nevertheless consults that registry while resolving postponed
# annotations. Install a temporary sentinel only for that compatibility path,
# and always remove it again; normal imports and direct execution already have
# the real module registered.
_DevFlowBootstrapModuleSentinel = None
if __name__ not in _DevFlowBootstrapSys.modules:
    _DevFlowBootstrapModuleSentinel = _DevFlowBootstrapTypes.ModuleType(
        __name__
    )
    _DevFlowBootstrapSys.modules[__name__] = (
        _DevFlowBootstrapModuleSentinel
    )

# Bundle identity is shared by the controller catalog and standalone package
# validators. Execute the exact shipped source before the ordered controller
# fragments so isolated ``python -I -S scripts/dev_flow.py`` needs no package
# import path.
_DEV_FLOW_SUPPORT_NAMES = ("workflow_bundle_identity.py",)
_DEV_FLOW_SCRIPT_DIRECTORY = _DevFlowBootstrapPath(__file__).resolve().parent

# Runtime layout version 1 intentionally executes trusted, ordered source
# fragments in this module's globals. This preserves direct-script,
# spec_from_file_location, isolated -I/-S startup, cache, ContextVar,
# and monkeypatch behavior while keeping dev_flow.py as the sole facade.
_DEV_FLOW_PART_NAMES = (
    "workflow_registry.py",
    "workflow_handlers.py",
    "workflow_builtin_handlers.py",
    "workflow_catalog.py",
    "workflow_state.py",
    "transition_engine.py",
    "agent_protocol.py",
    "node_telemetry.py",
    "external_tools.py",
    "external_write_bridge.py",
    "repository_plan.py",
    "orchestration_authority.py",
    "orchestration_results.py",
    "runtime_adapters.py",
    "workflow_projection.py",
    "workflow_transition_service.py",
    "action_execution_journal.py",
    "action_execution_store.py",
    "workflow_action_service.py",
    "workflow_action_transaction.py",
    "workflow_action_reconciliation.py",
    "workflow_v4_handlers.py",
    "orchestration_action_adapters.py",
    "core.py",
    "mutation.py",
    "scope.py",
    "manager_channel.py",
    "workflow_action_recovery_cli.py",
    "workflow_action_recovery_commands.py",
    "process.py",
    "orchestration_service.py",
    "mcp_controller_service.py",
    "git.py",
    "commands.py",
    "baseline.py",
    "workspace.py",
    "review.py",
    "cli.py",
    "workflow_runtime.py",
)
_DEV_FLOW_PART_DIRECTORY = (
    _DevFlowBootstrapPath(__file__).resolve().with_name("dev_flow_parts")
)


def _DevFlowLoadRuntime() -> None:
    for support_name in _DEV_FLOW_SUPPORT_NAMES:
        support_path = _DEV_FLOW_SCRIPT_DIRECTORY / support_name
        if not support_path.is_file():
            raise RuntimeError(
                "incomplete dev-flow installation: missing runtime support "
                + support_name
            )
        support_source = support_path.read_bytes()
        exec(
            compile(support_source, str(support_path), "exec"),
            globals(),
            globals(),
        )
    for part_name in _DEV_FLOW_PART_NAMES:
        part_path = _DEV_FLOW_PART_DIRECTORY / part_name
        if not part_path.is_file():
            raise RuntimeError(
                "incomplete dev-flow installation: missing runtime part "
                + part_name
            )
        part_source = part_path.read_bytes()
        exec(
            compile(part_source, str(part_path), "exec"),
            globals(),
            globals(),
        )


try:
    _DevFlowLoadRuntime()
    # Package-owned orchestration validators may register only while the
    # ordered runtime fragments are loading. Close that authority before the
    # runtime catalog becomes observable.
    freeze_orchestration_action_semantic_validators()
    # Build the handler registries and package catalog only after every
    # ordered fragment is present in this module's shared namespace. The
    # initializer publishes its singleton only after the complete audit and
    # catalog load succeed, so a partial runtime is never observable.
    _WORKFLOW_RUNTIME_SERVICES = initialize_workflow_runtime(globals())
finally:
    if (
        _DevFlowBootstrapModuleSentinel is not None
        and _DevFlowBootstrapSys.modules.get(__name__)
        is _DevFlowBootstrapModuleSentinel
    ):
        del _DevFlowBootstrapSys.modules[__name__]

del (
    _DevFlowLoadRuntime,
    _DevFlowBootstrapModuleSentinel,
    _DevFlowBootstrapTypes,
    _DevFlowBootstrapSys,
    _DEV_FLOW_SCRIPT_DIRECTORY,
    _DEV_FLOW_SUPPORT_NAMES,
    _DEV_FLOW_PART_DIRECTORY,
    _DEV_FLOW_PART_NAMES,
    _DevFlowBootstrapPath,
)


if __name__ == "__main__":
    raise SystemExit(main())
