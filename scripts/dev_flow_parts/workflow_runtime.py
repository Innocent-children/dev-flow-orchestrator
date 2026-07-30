# Loaded last by scripts/dev_flow.py into its shared module namespace.
# Responsibility: compose the immutable package catalog and registries without
# importing optional runtimes or target-repository code.
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


WORKFLOW_V4_REQUIRED_SUITES = MappingProxyType(
    {
        ("full", "single-repository"): frozenset(
            {
                "v4-static-closure",
                "v4-core-runtime",
                "v4-effect-recovery",
                "v4-external-tools",
            }
        ),
        ("full", "multi-repository"): frozenset(
            {
                "v4-static-closure",
                "v4-core-runtime",
                "v4-effect-recovery",
                "v4-external-tools",
                "v4-multi-repository",
            }
        ),
        ("lite", "single-repository"): frozenset(
            {
                "v4-static-closure",
                "v4-core-runtime",
                "v4-effect-recovery",
            }
        ),
    }
)
WORKFLOW_V4_VERSION = 4

_WORKFLOW_RUNTIME_ACTION_EDGE_FIELDS = frozenset(
    {
        "allowed_artifact_kinds",
        "allowed_state_writes",
        "automatic",
        "canonical_event",
        "class",
        "confirmation",
        "effect_classification",
        "effects",
        "gate",
        "guards",
        "handler",
        "id",
        "kernel_effects",
        "kernel_invalidates",
        "kernel_state_writes",
        "policy",
        "priority",
        "public_command",
        "reducers",
        "required_suites",
        "requires_note",
        "resume_policy",
        "side_effects",
        "source",
        "target",
        "tool_capabilities",
        "tool_policy",
        "trigger",
    }
)
_WORKFLOW_RUNTIME_V4_ACTION_EDGE_FIELDS = frozenset(
    {*_WORKFLOW_RUNTIME_ACTION_EDGE_FIELDS, "handler_closure"}
)
_WORKFLOW_RUNTIME_ACTION_EFFECT_FIELDS = frozenset(
    {
        "concurrency",
        "dependencies",
        "dispatch",
        "id",
        "idempotency",
        "parallel_group",
        "quarantine",
        "receipt",
        "recovery",
        "scopes",
        "settlement",
        "target_controls",
    }
)
_WORKFLOW_RUNTIME_ACTION_QUARANTINE_FIELDS = frozenset(
    {"compensation", "reconciliation"}
)
_WORKFLOW_RUNTIME_ACTION_RECOVERY_FIELDS = frozenset(
    {"mode", "on_uncertain", "redispatch"}
)
_WORKFLOW_RUNTIME_ACTION_REFERENCE_ROLES = MappingProxyType(
    {
        "guards": "evaluator",
        "reducers": "reducer",
        "gates": "builder",
        "executors": "dispatcher",
    }
)


class WorkflowBundleIdentityApi:
    """Narrow object capability passed to catalog and handler validation."""

    BundleFile = BundleFile
    HandlerImplementation = HandlerImplementation
    compute_workflow_bundle_identity = staticmethod(
        compute_workflow_bundle_identity
    )
    handler_implementation_sha256 = staticmethod(
        handler_implementation_sha256
    )


_WORKFLOW_RUNTIME_OPERATION_SYMBOLS = frozenset(
    {
        "_atomic_write_json",
        "_config_lock",
        "_current_repository_fingerprints",
        "_file_lock",
        "_fingerprint_repo",
        "_flush_pending_event",
        "_git",
        "_git_diff",
        "_git_evidence",
        "_git_evidence_optional",
        "_git_mutating",
        "_held_task_directory",
        "_latest_passing_test_is_current",
        "_locked_state",
        "_osc_read_bounded_events",
        "_persist_state_transaction",
        "_read_task_state_structural_snapshot",
        "_require_current_impact",
        "_require_current_plan_gate",
        "_require_current_route_selection",
        "_require_current_workspace_indexes",
        "_review_is_current",
        "_task_dir",
        "_task_lock",
        "_task_namespace_lock",
        "_workspace_registry_lock",
        "build_codex_exec_invocation",
        "build_runtime_attempt_record",
        "build_runtime_execution_request",
        "build_runtime_handle_record",
        "build_runtime_replacement_proof",
        "build_v4_runtime_replacement_proof",
        "create_mcp_controller_service",
        "load_state",
        "load_state_for_inspection",
        "orchestration_controller_service",
        "parse_codex_exec_jsonl",
        "plan_runtime_dispatch",
        "plan_v4_runtime_dispatch",
        "runtime_adapter_contracts",
        "update_runtime_attempt",
        "update_runtime_handle",
    }
)
_WORKFLOW_RUNTIME_VALUE_SYMBOLS = frozenset(
    {
        "_HELD_LOCK_DIRECTORIES",
        "_RUNTIME_ADAPTER_REGISTRY",
    }
)


@dataclass(frozen=True)
class _WorkflowRuntimeOperation:
    """One fixed package operation resolved late for facade compatibility."""

    symbol: str
    namespace: Mapping[str, object] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.symbol not in _WORKFLOW_RUNTIME_OPERATION_SYMBOLS:
            raise WorkflowCatalogError(
                "WORKFLOW_RUNTIME_CAPABILITY_UNDECLARED",
                "runtime service requested an undeclared package operation",
                details={"symbol": self.symbol},
            )
        self._resolve()

    def _resolve(self) -> object:
        implementation = self.namespace.get(self.symbol)
        if not callable(implementation):
            raise WorkflowCatalogError(
                "WORKFLOW_RUNTIME_CAPABILITY_UNAVAILABLE",
                "runtime service operation is missing or not callable",
                details={"symbol": self.symbol},
            )
        return implementation

    def __call__(self, *args: object, **kwargs: object) -> object:
        implementation = self._resolve()
        return implementation(*args, **kwargs)  # type: ignore[operator]


@dataclass(frozen=True)
class _WorkflowRuntimeValue:
    """One fixed package-owned value resolved late from the facade."""

    symbol: str
    namespace: Mapping[str, object] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.symbol not in _WORKFLOW_RUNTIME_VALUE_SYMBOLS:
            raise WorkflowCatalogError(
                "WORKFLOW_RUNTIME_CAPABILITY_UNDECLARED",
                "runtime service requested an undeclared package value",
                details={"symbol": self.symbol},
            )
        self.get()

    def get(self) -> object:
        if self.symbol not in self.namespace:
            raise WorkflowCatalogError(
                "WORKFLOW_RUNTIME_CAPABILITY_UNAVAILABLE",
                "runtime service value is missing",
                details={"symbol": self.symbol},
            )
        return self.namespace[self.symbol]


@dataclass(frozen=True)
class WorkflowStoreService:
    """Fixed task-state storage capabilities for authoritative services."""

    _load_state: _WorkflowRuntimeOperation = field(repr=False)
    _load_state_for_inspection: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _task_directory: _WorkflowRuntimeOperation = field(repr=False)
    _read_structural_snapshot: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _atomic_write_json: _WorkflowRuntimeOperation = field(repr=False)
    _flush_pending_event: _WorkflowRuntimeOperation = field(repr=False)
    _read_bounded_events: _WorkflowRuntimeOperation = field(repr=False)
    _persist_state_transaction: _WorkflowRuntimeOperation = field(
        repr=False
    )

    def load_state(self, *args: object, **kwargs: object) -> object:
        return self._load_state(*args, **kwargs)

    def load_state_for_inspection(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._load_state_for_inspection(*args, **kwargs)

    def task_directory(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._task_directory(*args, **kwargs)

    def read_structural_snapshot(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._read_structural_snapshot(*args, **kwargs)

    def atomic_write_json(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._atomic_write_json(*args, **kwargs)

    def flush_pending_event(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._flush_pending_event(*args, **kwargs)

    def read_bounded_events(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._read_bounded_events(*args, **kwargs)

    def persist_state_transaction(
        self, *args: object, **kwargs: object
    ) -> object:
        """Persist through the raw boundary; schema-v4 still needs its proof."""

        return self._persist_state_transaction(*args, **kwargs)


@dataclass(frozen=True)
class WorkflowLockService:
    """Fixed lock capabilities sharing the facade's canonical ContextVar."""

    _file_lock: _WorkflowRuntimeOperation = field(repr=False)
    _task_lock: _WorkflowRuntimeOperation = field(repr=False)
    _task_namespace_lock: _WorkflowRuntimeOperation = field(repr=False)
    _workspace_registry_lock: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _config_lock: _WorkflowRuntimeOperation = field(repr=False)
    _locked_state: _WorkflowRuntimeOperation = field(repr=False)
    _held_task_directory: _WorkflowRuntimeOperation = field(repr=False)
    _held_lock_directories: _WorkflowRuntimeValue = field(repr=False)

    def file_lock(self, *args: object, **kwargs: object) -> object:
        return self._file_lock(*args, **kwargs)

    def task_lock(self, *args: object, **kwargs: object) -> object:
        return self._task_lock(*args, **kwargs)

    def task_namespace_lock(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._task_namespace_lock(*args, **kwargs)

    def workspace_registry_lock(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._workspace_registry_lock(*args, **kwargs)

    def config_lock(self, *args: object, **kwargs: object) -> object:
        return self._config_lock(*args, **kwargs)

    def locked_state(self, *args: object, **kwargs: object) -> object:
        return self._locked_state(*args, **kwargs)

    def held_task_directory(self) -> object:
        return self._held_task_directory()

    def held_directories(self) -> tuple[str, ...]:
        context = self._held_lock_directories.get()
        getter = getattr(context, "get", None)
        if not callable(getter):
            raise WorkflowCatalogError(
                "WORKFLOW_RUNTIME_CAPABILITY_INVALID",
                "held-lock capability is not a ContextVar-like value",
                details={"symbol": "_HELD_LOCK_DIRECTORIES"},
            )
        value = getter()
        if not isinstance(value, tuple) or any(
            not isinstance(item, str) for item in value
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_RUNTIME_CAPABILITY_INVALID",
                "held-lock capability returned an invalid lock set",
                details={"symbol": "_HELD_LOCK_DIRECTORIES"},
            )
        return value

    def workflow_transition_locks(
        self,
        state: Mapping[str, object],
    ) -> tuple[bool, bool, bool]:
        held = self.held_directories()
        task_directory = self.held_task_directory()
        task_held = (
            isinstance(task_directory, Path)
            and task_directory.name == state.get("task_id")
        )
        workspace_held = any(
            not isinstance(task_directory, Path)
            or value
            != str(task_directory.resolve(strict=False))
            for value in held
        )
        return task_held, workspace_held, workspace_held


@dataclass(frozen=True)
class WorkflowEvidenceService:
    """Fixed high-level evidence and currentness capabilities."""

    _fingerprint_repository: _WorkflowRuntimeOperation = field(repr=False)
    _current_repository_fingerprints: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _require_current_impact: _WorkflowRuntimeOperation = field(repr=False)
    _require_current_route_selection: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _require_current_workspace_indexes: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _require_current_plan_gate: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _review_is_current: _WorkflowRuntimeOperation = field(repr=False)
    _latest_passing_test_is_current: _WorkflowRuntimeOperation = field(
        repr=False
    )

    def fingerprint_repository(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._fingerprint_repository(*args, **kwargs)

    def current_repository_fingerprints(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._current_repository_fingerprints(*args, **kwargs)

    def require_current_impact(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._require_current_impact(*args, **kwargs)

    def require_current_route_selection(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._require_current_route_selection(*args, **kwargs)

    def require_current_workspace_indexes(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._require_current_workspace_indexes(*args, **kwargs)

    def require_current_plan_gate(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._require_current_plan_gate(*args, **kwargs)

    def review_is_current(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._review_is_current(*args, **kwargs)

    def latest_passing_test_is_current(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._latest_passing_test_is_current(
            *args, **kwargs
        )


@dataclass(frozen=True)
class WorkflowGitService:
    """Fixed low-level Git read, evidence, diff, and mutation capabilities."""

    _run: _WorkflowRuntimeOperation = field(repr=False)
    _run_mutating: _WorkflowRuntimeOperation = field(repr=False)
    _observe: _WorkflowRuntimeOperation = field(repr=False)
    _observe_optional: _WorkflowRuntimeOperation = field(repr=False)
    _diff: _WorkflowRuntimeOperation = field(repr=False)

    def run(self, *args: object, **kwargs: object) -> object:
        return self._run(*args, **kwargs)

    def run_mutating(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._run_mutating(*args, **kwargs)

    def observe(self, *args: object, **kwargs: object) -> object:
        return self._observe(*args, **kwargs)

    def observe_optional(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._observe_optional(*args, **kwargs)

    def diff(self, *args: object, **kwargs: object) -> object:
        return self._diff(*args, **kwargs)


@dataclass(frozen=True)
class WorkflowAdapterService:
    """Fixed host-adapter contracts and package service factories."""

    _registry: _WorkflowRuntimeValue = field(repr=False)
    _runtime_contracts: _WorkflowRuntimeOperation = field(repr=False)
    _build_execution_request: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _build_codex_exec_invocation: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _parse_codex_exec_jsonl: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _build_runtime_handle_record: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _update_runtime_handle: _WorkflowRuntimeOperation = field(repr=False)
    _build_runtime_attempt_record: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _update_runtime_attempt: _WorkflowRuntimeOperation = field(repr=False)
    _build_runtime_replacement_proof: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _build_v4_runtime_replacement_proof: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _plan_runtime_dispatch: _WorkflowRuntimeOperation = field(repr=False)
    _plan_v4_runtime_dispatch: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _create_mcp_controller_service: _WorkflowRuntimeOperation = field(
        repr=False
    )
    _orchestration_controller_service: _WorkflowRuntimeOperation = field(
        repr=False
    )

    @property
    def registry(self) -> object:
        return self._registry.get()

    def runtime_contracts(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._runtime_contracts(*args, **kwargs)

    def build_execution_request(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._build_execution_request(*args, **kwargs)

    def build_codex_exec_invocation(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._build_codex_exec_invocation(*args, **kwargs)

    def parse_codex_exec_jsonl(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._parse_codex_exec_jsonl(*args, **kwargs)

    def build_runtime_handle_record(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._build_runtime_handle_record(*args, **kwargs)

    def update_runtime_handle(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._update_runtime_handle(*args, **kwargs)

    def build_runtime_attempt_record(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._build_runtime_attempt_record(*args, **kwargs)

    def update_runtime_attempt(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._update_runtime_attempt(*args, **kwargs)

    def build_runtime_replacement_proof(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._build_runtime_replacement_proof(*args, **kwargs)

    def build_v4_runtime_replacement_proof(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._build_v4_runtime_replacement_proof(
            *args, **kwargs
        )

    def plan_runtime_dispatch(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._plan_runtime_dispatch(*args, **kwargs)

    def plan_v4_runtime_dispatch(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._plan_v4_runtime_dispatch(*args, **kwargs)

    def create_mcp_controller_service(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._create_mcp_controller_service(*args, **kwargs)

    def orchestration_controller_service(
        self, *args: object, **kwargs: object
    ) -> object:
        return self._orchestration_controller_service(
            *args, **kwargs
        )


@dataclass(frozen=True)
class WorkflowRuntimeServices:
    """One sealed, process-local view of all executable workflow contracts."""

    package_root: Path
    identity_api: object
    registries: object
    handler_manifests: tuple[object, ...]
    handler_resolver: object
    catalog: object
    store: WorkflowStoreService
    locks: WorkflowLockService
    evidence: WorkflowEvidenceService
    git: WorkflowGitService
    adapters: WorkflowAdapterService


_workflow_runtime_services: WorkflowRuntimeServices | None = None


def _workflow_runtime_default_package_root() -> Path:
    runtime_file = Path(__file__).resolve()
    if runtime_file.name == "dev_flow.py":
        return runtime_file.parent.parent
    return runtime_file.parents[2]


def _workflow_runtime_operation(
    namespace: Mapping[str, object],
    symbol: str,
) -> _WorkflowRuntimeOperation:
    return _WorkflowRuntimeOperation(
        symbol=symbol,
        namespace=namespace,
    )


def _workflow_runtime_value(
    namespace: Mapping[str, object],
    symbol: str,
) -> _WorkflowRuntimeValue:
    return _WorkflowRuntimeValue(
        symbol=symbol,
        namespace=namespace,
    )


def _workflow_runtime_store_service(
    namespace: Mapping[str, object],
) -> WorkflowStoreService:
    operation = lambda symbol: _workflow_runtime_operation(  # noqa: E731
        namespace, symbol
    )
    return WorkflowStoreService(
        _load_state=operation("load_state"),
        _load_state_for_inspection=operation(
            "load_state_for_inspection"
        ),
        _task_directory=operation("_task_dir"),
        _read_structural_snapshot=operation(
            "_read_task_state_structural_snapshot"
        ),
        _atomic_write_json=operation("_atomic_write_json"),
        _flush_pending_event=operation("_flush_pending_event"),
        _read_bounded_events=operation("_osc_read_bounded_events"),
        _persist_state_transaction=operation(
            "_persist_state_transaction"
        ),
    )


def _workflow_runtime_lock_service(
    namespace: Mapping[str, object],
) -> WorkflowLockService:
    operation = lambda symbol: _workflow_runtime_operation(  # noqa: E731
        namespace, symbol
    )
    return WorkflowLockService(
        _file_lock=operation("_file_lock"),
        _task_lock=operation("_task_lock"),
        _task_namespace_lock=operation("_task_namespace_lock"),
        _workspace_registry_lock=operation(
            "_workspace_registry_lock"
        ),
        _config_lock=operation("_config_lock"),
        _locked_state=operation("_locked_state"),
        _held_task_directory=operation("_held_task_directory"),
        _held_lock_directories=_workflow_runtime_value(
            namespace, "_HELD_LOCK_DIRECTORIES"
        ),
    )


def _workflow_runtime_evidence_service(
    namespace: Mapping[str, object],
) -> WorkflowEvidenceService:
    operation = lambda symbol: _workflow_runtime_operation(  # noqa: E731
        namespace, symbol
    )
    return WorkflowEvidenceService(
        _fingerprint_repository=operation("_fingerprint_repo"),
        _current_repository_fingerprints=operation(
            "_current_repository_fingerprints"
        ),
        _require_current_impact=operation(
            "_require_current_impact"
        ),
        _require_current_route_selection=operation(
            "_require_current_route_selection"
        ),
        _require_current_workspace_indexes=operation(
            "_require_current_workspace_indexes"
        ),
        _require_current_plan_gate=operation(
            "_require_current_plan_gate"
        ),
        _review_is_current=operation("_review_is_current"),
        _latest_passing_test_is_current=operation(
            "_latest_passing_test_is_current"
        ),
    )


def _workflow_runtime_git_service(
    namespace: Mapping[str, object],
) -> WorkflowGitService:
    operation = lambda symbol: _workflow_runtime_operation(  # noqa: E731
        namespace, symbol
    )
    return WorkflowGitService(
        _run=operation("_git"),
        _run_mutating=operation("_git_mutating"),
        _observe=operation("_git_evidence"),
        _observe_optional=operation("_git_evidence_optional"),
        _diff=operation("_git_diff"),
    )


def _workflow_runtime_adapter_service(
    namespace: Mapping[str, object],
) -> WorkflowAdapterService:
    operation = lambda symbol: _workflow_runtime_operation(  # noqa: E731
        namespace, symbol
    )
    return WorkflowAdapterService(
        _registry=_workflow_runtime_value(
            namespace, "_RUNTIME_ADAPTER_REGISTRY"
        ),
        _runtime_contracts=operation("runtime_adapter_contracts"),
        _build_execution_request=operation(
            "build_runtime_execution_request"
        ),
        _build_codex_exec_invocation=operation(
            "build_codex_exec_invocation"
        ),
        _parse_codex_exec_jsonl=operation(
            "parse_codex_exec_jsonl"
        ),
        _build_runtime_handle_record=operation(
            "build_runtime_handle_record"
        ),
        _update_runtime_handle=operation("update_runtime_handle"),
        _build_runtime_attempt_record=operation(
            "build_runtime_attempt_record"
        ),
        _update_runtime_attempt=operation("update_runtime_attempt"),
        _build_runtime_replacement_proof=operation(
            "build_runtime_replacement_proof"
        ),
        _build_v4_runtime_replacement_proof=operation(
            "build_v4_runtime_replacement_proof"
        ),
        _plan_runtime_dispatch=operation("plan_runtime_dispatch"),
        _plan_v4_runtime_dispatch=operation(
            "plan_v4_runtime_dispatch"
        ),
        _create_mcp_controller_service=operation(
            "create_mcp_controller_service"
        ),
        _orchestration_controller_service=operation(
            "orchestration_controller_service"
        ),
    )


def build_workflow_runtime(
    namespace: Mapping[str, object],
    *,
    package_root: Path | str | None = None,
) -> WorkflowRuntimeServices:
    """Audit, seal, and compose package-owned runtime services atomically."""

    root = (
        _workflow_runtime_default_package_root()
        if package_root is None
        else Path(package_root)
    ).resolve()
    identity_api = WorkflowBundleIdentityApi()
    registries = RuntimeRegistries()
    manifests = initialize_package_handler_registries(
        registries=registries,
        namespace=namespace,
        package_root=root,
    )
    resolver = PackageHandlerResolver(
        registries,
        manifests,
        root,
        identity_api,
    )
    catalog = load_workflow_catalog(
        root / "workflows",
        contract_resolver=resolver,
        identity_api=identity_api,
    )
    return WorkflowRuntimeServices(
        package_root=root,
        identity_api=identity_api,
        registries=registries,
        handler_manifests=tuple(manifests),
        handler_resolver=resolver,
        catalog=catalog,
        store=_workflow_runtime_store_service(namespace),
        locks=_workflow_runtime_lock_service(namespace),
        evidence=_workflow_runtime_evidence_service(namespace),
        git=_workflow_runtime_git_service(namespace),
        adapters=_workflow_runtime_adapter_service(namespace),
    )


def initialize_workflow_runtime(
    namespace: Mapping[str, object],
    *,
    package_root: Path | str | None = None,
) -> WorkflowRuntimeServices:
    """Initialize the process singleton once; replacement is unsupported."""

    global _workflow_runtime_services
    if _workflow_runtime_services is not None:
        raise WorkflowCatalogError(
            "WORKFLOW_RUNTIME_ALREADY_INITIALIZED",
            "workflow runtime services are immutable for this process",
        )
    services = build_workflow_runtime(
        namespace, package_root=package_root
    )
    install_transition_engine_evaluation_lock_observer(
        _workflow_transition_evaluation_lock_binding
    )
    _workflow_runtime_services = services
    return services


def workflow_runtime_services() -> WorkflowRuntimeServices:
    if _workflow_runtime_services is None:
        raise WorkflowCatalogError(
            "WORKFLOW_RUNTIME_UNAVAILABLE",
            "workflow runtime services have not completed initialization",
        )
    return _workflow_runtime_services


def manager_command_action_ids_v1() -> tuple[str, ...]:
    """Project the exact schema-v4 CLI mutation scope from the sealed registry."""

    services = workflow_runtime_services()
    commands = services.registries.commands
    if not commands.sealed:
        raise WorkflowRegistryError(
            "REGISTRY_UNSEALED",
            "manager action projection requires the sealed command registry",
            details={"registry": "commands"},
        )
    actions = {
        registration.action_id
        for registration in commands.entries.values()
        if (
            (
                "controller-mutation"
                in set(registration.authority)
                and registration.command != "start"
            )
            or (
                "controller-recovery-mutation"
                in set(registration.authority)
                and registration.command == "recover-quarantine"
            )
        )
    }
    return tuple(
        sorted(actions, key=lambda item: item.encode("utf-8"))
    )


def _workflow_runtime_creation_error(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> "WorkflowCatalogError":
    return WorkflowCatalogError(code, message, details=details)


def workflow_creation_execution_profile(
    repository_count: int,
) -> str:
    if (
        isinstance(repository_count, bool)
        or not isinstance(repository_count, int)
        or repository_count < 1
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_PROFILE_INVALID",
            "workflow creation requires at least one repository",
            details={"repository_count": repository_count},
        )
    return (
        "single-repository"
        if repository_count == 1
        else "multi-repository"
    )


def _workflow_runtime_activation_entry(
    catalog: object,
    bundle: object,
    execution_profile: str,
) -> Mapping[str, object]:
    activations = getattr(catalog, "activations", ())
    matches = tuple(
        item
        for item in activations
        if isinstance(item, Mapping)
        and item.get("workflow_id")
        == getattr(bundle, "workflow_id", None)
        and item.get("workflow_version")
        == getattr(bundle, "workflow_version", None)
        and item.get("execution_profile") == execution_profile
    )
    if not matches and (
        getattr(bundle, "workflow_version", None)
        == WORKFLOW_V4_VERSION
        and execution_profile
        in tuple(getattr(bundle, "execution_profiles", ()))
    ):
        return MappingProxyType(
            {
                "workflow_id": getattr(bundle, "workflow_id", None),
                "workflow_version": WORKFLOW_V4_VERSION,
                "bundle_sha256": getattr(
                    bundle, "bundle_sha256", None
                ),
                "execution_profile": execution_profile,
                "active": False,
                "required_suites": (),
                "source": "implicit-inactive-preview",
            }
        )
    if len(matches) != 1:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_UNAVAILABLE",
            "workflow activation does not identify one exact profile",
            details={
                "workflow_id": getattr(bundle, "workflow_id", None),
                "workflow_version": getattr(
                    bundle, "workflow_version", None
                ),
                "execution_profile": execution_profile,
                "matches": len(matches),
            },
        )
    return matches[0]


def _workflow_runtime_validate_action_reference(
    services: WorkflowRuntimeServices,
    reference: object,
    *,
    registry: str,
    edge_id: str,
) -> None:
    if not isinstance(reference, Mapping):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "action closure contains an invalid handler reference",
            details={"edge_id": edge_id, "registry": registry},
        )
    if set(reference) != {"registry", "id", "version"} or (
        reference.get("registry") != registry
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "action closure handler reference is not exact",
            details={"edge_id": edge_id, "registry": registry},
        )
    identifier = reference.get("id")
    version = reference.get("version")
    if not isinstance(identifier, str) or not isinstance(version, str):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "action closure handler identity is invalid",
            details={"edge_id": edge_id, "registry": registry},
        )
    try:
        implementation = services.handler_resolver.resolve_callable(
            registry,
            identifier,
            version,
            _WORKFLOW_RUNTIME_ACTION_REFERENCE_ROLES[registry],
        )
        if (
            registry == "executors"
            and identifier.startswith("executor.v4-")
            and implementation
            is globals().get("_disabled_executor_dispatch")
        ):
            raise WorkflowHandlerAuditError(
                "HANDLER_BINDING_DISABLED",
                "V4 action closure references a descriptor-only executor",
                details={
                    "registry": registry,
                    "identifier": identifier,
                    "version": version,
                },
            )
    except (
        WorkflowRegistryError,
        WorkflowHandlerAuditError,
    ) as exc:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "action closure references an unavailable package handler",
            details={
                "edge_id": edge_id,
                "registry": registry,
                "identifier": identifier,
                "version": version,
                "registry_error": exc.code,
            },
        ) from exc


def _workflow_runtime_validate_action_effects(
    edge: Mapping[str, object],
    *,
    edge_id: str,
) -> None:
    effects = edge.get("effects")
    if not isinstance(effects, tuple) or not effects:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "action closure has no immutable effect contract",
            details={"edge_id": edge_id},
        )
    known_ids: set[str] = set()
    effect_by_id: dict[str, Mapping[str, object]] = {}
    for effect in effects:
        if (
            not isinstance(effect, Mapping)
            or set(effect) != _WORKFLOW_RUNTIME_ACTION_EFFECT_FIELDS
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action closure effect contract is not exact",
                details={"edge_id": edge_id},
            )
        effect_id = effect.get("id")
        if (
            not isinstance(effect_id, str)
            or not effect_id
            or effect_id in known_ids
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action closure effect identity is missing or duplicated",
                details={"edge_id": edge_id, "effect_id": effect_id},
            )
        known_ids.add(effect_id)
        effect_by_id[effect_id] = effect
        scopes = effect.get("scopes")
        dependencies = effect.get("dependencies")
        controls = effect.get("target_controls")
        quarantine = effect.get("quarantine")
        recovery = effect.get("recovery")
        if (
            not isinstance(scopes, tuple)
            or not scopes
            or len(set(scopes)) != len(scopes)
            or not all(isinstance(item, str) and item for item in scopes)
            or not isinstance(dependencies, tuple)
            or len(set(dependencies)) != len(dependencies)
            or not all(
                isinstance(item, str) and item for item in dependencies
            )
            or not isinstance(controls, tuple)
            or len(set(controls)) != len(controls)
            or not all(isinstance(item, str) and item for item in controls)
            or not isinstance(quarantine, Mapping)
            or set(quarantine)
            != _WORKFLOW_RUNTIME_ACTION_QUARANTINE_FIELDS
            or not isinstance(recovery, Mapping)
            or set(recovery) != _WORKFLOW_RUNTIME_ACTION_RECOVERY_FIELDS
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action closure lacks canonical scope, dependency, control, "
                "quarantine, or recovery metadata",
                details={"edge_id": edge_id, "effect_id": effect_id},
            )
        dispatch = effect.get("dispatch")
        idempotency = effect.get("idempotency")
        settlement = effect.get("settlement")
        concurrency = effect.get("concurrency")
        receipt = effect.get("receipt")
        if (
            concurrency not in {"exclusive-task", "scoped"}
            or settlement
            not in {
                "asynchronous-handoff",
                "synchronous-quiescence",
            }
            or dispatch not in {"none", "single-dispatch"}
            or (
                dispatch == "single-dispatch"
                and idempotency != "execution-effect-key/v1"
            )
            or (
                dispatch == "none"
                and idempotency != "not-applicable"
            )
            or not isinstance(receipt, str)
            or not receipt
            or recovery.get("redispatch") != "forbidden"
            or recovery.get("mode")
            not in {"observe-or-quarantine/v1", "re-evaluate/v1"}
            or recovery.get("on_uncertain")
            not in {"block", "quarantine"}
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action closure effect dispatch, receipt, settlement, or "
                "recovery contract is incomplete",
                details={"edge_id": edge_id, "effect_id": effect_id},
            )
        if dispatch == "single-dispatch":
            if (
                set(controls)
                != {
                    "control.cancel/v1",
                    "control.reconcile/v1",
                    "control.stop/v1",
                }
                or quarantine.get("reconciliation")
                != "target-bound/v1"
                or quarantine.get("compensation")
                != "new-authorized-execution/v1"
                or recovery.get("mode")
                != "observe-or-quarantine/v1"
                or recovery.get("on_uncertain") != "quarantine"
            ):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "dispatching action lacks target-bound control and "
                    "quarantine closure",
                    details={"edge_id": edge_id, "effect_id": effect_id},
                )
        elif (
            controls
            or quarantine.get("reconciliation") != "not-applicable"
            or quarantine.get("compensation") != "not-applicable"
            or recovery.get("mode") != "re-evaluate/v1"
            or recovery.get("on_uncertain") != "block"
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "effect-free action claims an external recovery path",
                details={"edge_id": edge_id, "effect_id": effect_id},
            )
    for effect_id, effect in effect_by_id.items():
        dependencies = tuple(effect["dependencies"])
        if effect_id in dependencies or not set(dependencies).issubset(
            known_ids
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action effect dependency is unknown or self-referential",
                details={"edge_id": edge_id, "effect_id": effect_id},
            )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(effect_id: str) -> None:
        if effect_id in visited:
            return
        if effect_id in visiting:
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action effect dependency graph contains a cycle",
                details={"edge_id": edge_id, "effect_id": effect_id},
            )
        visiting.add(effect_id)
        for dependency in effect_by_id[effect_id]["dependencies"]:
            visit(str(dependency))
        visiting.remove(effect_id)
        visited.add(effect_id)

    for effect_id in sorted(known_ids):
        visit(effect_id)


def _workflow_runtime_validate_repository_action_matrix(
    bundle: object,
    nodes: Mapping[str, object],
    action_edges: tuple[Mapping[str, object], ...],
) -> None:
    """Validate the exact full@4 repository operation closure."""

    metadata = getattr(bundle, "repository_orchestration", None)
    profiles = tuple(getattr(bundle, "execution_profiles", ()))
    if "multi-repository" not in profiles:
        if metadata is not None:
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "single-repository workflow exposes repository orchestration",
            )
        return
    expected_fields = {
        "schema",
        "execution_profile",
        "action_nodes",
        "map",
        "join",
        "operation_ids",
        "operation_matrix",
    }
    if not isinstance(metadata, Mapping) or set(metadata) != expected_fields:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "full@4 lacks its exact repository orchestration contract",
        )
    operation_ids = metadata.get("operation_ids")
    matrix = metadata.get("operation_matrix")
    expected_operations = tuple(
        sorted(
            _workflow_catalog_repository_required_operation_ids,
            key=lambda item: item.encode("utf-8"),
        )
    )
    if (
        metadata.get("schema")
        != "dev-flow-repository-orchestration/v1"
        or metadata.get("execution_profile") != "multi-repository"
        or operation_ids != expected_operations
        or not isinstance(matrix, tuple)
        or len(matrix) != len(expected_operations)
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "full@4 repository operation inventory is incomplete",
        )
    action_nodes_value = metadata.get("action_nodes")
    action_nodes = frozenset(
        item
        for item in (
            action_nodes_value
            if isinstance(action_nodes_value, tuple)
            else ()
        )
        if isinstance(item, str)
    )
    if (
        not action_nodes
        or len(action_nodes) != len(action_nodes_value)
        or any(
            node_id not in nodes
            or nodes[node_id].get("terminal") is True
            for node_id in action_nodes
        )
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "full@4 repository action-node closure is invalid",
        )
    observed_operations: list[str] = []
    observed_semantic_ids: set[str] = set()
    for item in matrix:
        if not isinstance(item, Mapping):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "repository operation identity must be immutable",
            )
        operation_id = item.get("operation_id")
        if not isinstance(operation_id, str):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "repository operation identity is missing",
            )
        expected = _workflow_catalog_repository_semantic_identities(
            operation_id
        )
        if dict(item) != dict(expected):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "repository operation identity differs from full@4",
                details={"operation_id": operation_id},
            )
        semantic_ids = {
            str(item["action_id"]),
            str(item["validator_id"]),
            str(item["event_id"]),
            str(item["write_set_id"]),
            *(str(value) for value in item["effect_ids"]),
        }
        if observed_semantic_ids.intersection(semantic_ids):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "repository semantic identity is overloaded",
                details={"operation_id": operation_id},
            )
        observed_semantic_ids.update(semantic_ids)
        observed_operations.append(operation_id)
        action_id = str(item["action_id"])
        matches = tuple(
            edge
            for edge in action_edges
            if isinstance(edge.get("trigger"), Mapping)
            and edge["trigger"].get("id") == action_id
            and edge.get("source") == edge.get("target")
        )
        if (
            len(matches) != len(action_nodes)
            or {str(edge.get("source")) for edge in matches}
            != set(action_nodes)
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "repository action is not available at every live node",
                details={"operation_id": operation_id},
            )
    if tuple(observed_operations) != expected_operations:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "repository operation matrix is not canonical",
        )

def _workflow_runtime_validate_action_closure(
    services: WorkflowRuntimeServices,
    bundle: object,
    nodes: Mapping[str, object],
    graph: Mapping[str, object],
) -> frozenset[str]:
    """Revalidate movement reachability and every compiled node action.

    This intentionally does not trust a replaced ``WorkflowBundle`` merely
    because its original graph passed catalog loading. Activation is the last
    boundary before revision one and therefore checks the frozen declarations
    against the separately compiled immutable action edges again.
    """

    movement_edges = getattr(bundle, "edges", None)
    action_edges = getattr(bundle, "action_edges", None)
    entries = graph.get("entry_nodes")
    if (
        not isinstance(movement_edges, tuple)
        or not isinstance(action_edges, tuple)
        or not isinstance(entries, tuple)
        or not entries
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "workflow movement or action closure is unavailable",
        )
    reachable = {
        item for item in entries if isinstance(item, str) and item in nodes
    }
    if len(reachable) != len(entries):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "workflow entry node is invalid",
        )
    changed = True
    while changed:
        changed = False
        for edge in movement_edges:
            if not isinstance(edge, Mapping):
                continue
            source = edge.get("source")
            target = edge.get("target")
            if (
                source in reachable
                and isinstance(target, str)
                and target in nodes
                and target not in reachable
            ):
                reachable.add(target)
                changed = True
    if reachable != set(nodes):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "workflow movement graph does not reach every declared node",
            details={"unreachable": sorted(set(nodes) - reachable)},
        )

    tool_declarations = graph.get("tool_capabilities", ())
    if not isinstance(tool_declarations, tuple):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "external-tool declaration closure is not immutable",
        )
    tool_capabilities: dict[str, Mapping[str, object]] = {}
    expected_tool_fields = {
        "schema",
        "capability_id",
        "tool_id",
        "operations",
        "result_schema",
        "scopes",
    }
    for declaration in tool_declarations:
        if (
            not isinstance(declaration, Mapping)
            or set(declaration) != expected_tool_fields
            or declaration.get("schema")
            != "dev-flow-external-tool-capability/v1"
            or not isinstance(declaration.get("capability_id"), str)
            or not isinstance(declaration.get("operations"), tuple)
            or not isinstance(declaration.get("scopes"), tuple)
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "external-tool declaration is malformed",
            )
        capability_id = str(declaration["capability_id"])
        if capability_id in tool_capabilities:
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "external-tool declaration identity is duplicated",
                details={"capability_id": capability_id},
            )
        tool_capabilities[capability_id] = declaration

    declarations: dict[str, tuple[str, Mapping[str, object]]] = {}
    for node_id, node in nodes.items():
        actions = node.get("actions") if isinstance(node, Mapping) else None
        if not isinstance(actions, tuple):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "reachable node has no immutable action declaration list",
                details={"node_id": node_id},
            )
        for action in actions:
            if not isinstance(action, Mapping):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "reachable node action declaration is invalid",
                    details={"node_id": node_id},
                )
            edge_id = action.get("edge_id")
            if (
                not isinstance(edge_id, str)
                or not edge_id
                or edge_id in declarations
            ):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "reachable node action edge identity is missing or "
                    "duplicated",
                    details={"node_id": node_id, "edge_id": edge_id},
                )
            declarations[edge_id] = (str(node_id), action)
    shared_actions = graph.get("shared_actions", ())
    if not isinstance(shared_actions, tuple):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "shared action closure is not immutable",
        )
    for shared in shared_actions:
        if not isinstance(shared, Mapping) or set(shared) != {
            "action",
            "placements",
        }:
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "shared action declaration is invalid",
            )
        action = shared.get("action")
        placements = shared.get("placements")
        if not isinstance(action, Mapping) or not isinstance(
            placements, tuple
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "shared action or placement list is invalid",
            )
        for placement in placements:
            if (
                not isinstance(placement, Mapping)
                or set(placement) != {"edge_id", "node"}
            ):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "shared action placement is invalid",
                )
            edge_id = placement.get("edge_id")
            node_id = placement.get("node")
            if (
                not isinstance(edge_id, str)
                or not edge_id
                or edge_id in declarations
                or not isinstance(node_id, str)
                or node_id not in nodes
            ):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "shared action placement is missing, duplicated, or "
                    "outside the reachable graph",
                    details={"edge_id": edge_id, "node_id": node_id},
                )
            declarations[edge_id] = (node_id, action)
    compiled_ids = {
        edge.get("id")
        for edge in action_edges
        if isinstance(edge, Mapping)
        and isinstance(edge.get("id"), str)
    }
    if compiled_ids != set(declarations) or len(compiled_ids) != len(
        action_edges
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "compiled action edges do not exactly close node declarations",
            details={
                "missing": sorted(set(declarations) - compiled_ids),
                "unexpected": sorted(compiled_ids - set(declarations)),
            },
        )

    selectors: set[tuple[str, str, str | None, str | None]] = set()
    required_suites: set[str] = set()
    used_tool_capabilities: set[str] = set()
    workflow_version = getattr(bundle, "workflow_version", None)
    v4_action_closure = (
        isinstance(workflow_version, int)
        and not isinstance(workflow_version, bool)
        and workflow_version >= WORKFLOW_V4_VERSION
    )
    expected_action_edge_fields = (
        _WORKFLOW_RUNTIME_V4_ACTION_EDGE_FIELDS
        if v4_action_closure
        else _WORKFLOW_RUNTIME_ACTION_EDGE_FIELDS
    )
    for edge in action_edges:
        assert isinstance(edge, Mapping)
        edge_id = str(edge["id"])
        node_id, declaration = declarations[edge_id]
        if (
            set(edge) != expected_action_edge_fields
            or edge.get("source") != node_id
            or edge.get("target") != node_id
            or edge.get("class") != "action"
            or edge.get("policy") != "node-action"
            or edge.get("automatic") is not False
            or edge.get("priority") != 100
            or edge.get("trigger") != declaration.get("trigger")
            or edge.get("public_command")
            != declaration.get("public_command")
            or edge.get("canonical_event")
            != declaration.get("canonical_event")
            or edge.get("handler_closure")
            != declaration.get("handler_closure")
            or edge.get("tool_policy")
            != declaration.get("tool_policy")
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "compiled action edge differs from its reachable node "
                "declaration",
                details={"edge_id": edge_id, "node_id": node_id},
            )
        tool_policy = edge.get("tool_policy")
        expected_capabilities = (
            ()
            if tool_policy is None
            else tuple(tool_policy.get("capabilities", ()))
        )
        edge_capabilities = edge.get("tool_capabilities")
        if (
            not isinstance(edge_capabilities, tuple)
            or edge_capabilities != expected_capabilities
            or len(edge_capabilities) != len(set(edge_capabilities))
            or any(
                capability_id not in tool_capabilities
                for capability_id in edge_capabilities
            )
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action edge external-tool capability closure differs",
                details={"edge_id": edge_id},
            )
        handler = edge.get("handler")
        external_executor = (
            isinstance(handler, Mapping)
            and handler.get("id") == "executor.external-tool/v1"
        )
        if external_executor != bool(edge_capabilities):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "external-tool executor lacks an exact declared capability",
                details={"edge_id": edge_id},
            )
        used_tool_capabilities.update(
            str(item) for item in edge_capabilities
        )
        trigger = edge.get("trigger")
        public = edge.get("public_command")
        if (
            not isinstance(trigger, Mapping)
            or set(trigger) != {"kind", "id"}
            or trigger.get("kind") != "action"
            or not isinstance(trigger.get("id"), str)
            or not isinstance(public, Mapping)
            or set(public) != {"id", "selector", "values"}
            or not isinstance(public.get("id"), str)
            or not isinstance(public.get("values"), tuple)
            or not isinstance(edge.get("canonical_event"), str)
            or not edge.get("canonical_event")
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action lacks a stable trigger, public command, or audit event",
                details={"edge_id": edge_id},
            )
        selector_name = public.get("selector")
        values = tuple(public["values"])
        if selector_name is None:
            keys = ((node_id, str(public["id"]), None, None),)
            if values:
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "selector-free action declares selector values",
                    details={"edge_id": edge_id},
                )
        else:
            if (
                not isinstance(selector_name, str)
                or not selector_name
                or not values
                or len(set(values)) != len(values)
                or not all(isinstance(item, str) and item for item in values)
            ):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "action selector closure is invalid",
                    details={"edge_id": edge_id},
                )
            keys = tuple(
                (
                    node_id,
                    str(public["id"]),
                    selector_name,
                    str(value),
                )
                for value in values
            )
        if any(key in selectors for key in keys):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "public action selector is ambiguous at a reachable node",
                details={"edge_id": edge_id, "node_id": node_id},
            )
        selectors.update(keys)
        _workflow_runtime_validate_action_reference(
            services,
            edge.get("handler"),
            registry="executors",
            edge_id=edge_id,
        )
        if v4_action_closure:
            closure = edge.get("handler_closure")
            if not isinstance(closure, tuple):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "V4 action handler closure is not immutable",
                    details={"edge_id": edge_id},
                )
            roles = tuple(
                item.get("role")
                for item in closure
                if isinstance(item, Mapping)
            )
            if roles != _workflow_catalog_v4_handler_closure_roles:
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "V4 action handler closure is incomplete or unordered",
                    details={"edge_id": edge_id},
                )
            for item in closure:
                assert isinstance(item, Mapping)
                _workflow_runtime_validate_action_reference(
                    services,
                    item.get("handler"),
                    registry="executors",
                    edge_id=edge_id,
                )
        guards = edge.get("guards")
        reducers = edge.get("reducers")
        gate = edge.get("gate")
        if not isinstance(guards, tuple) or not isinstance(reducers, tuple):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action guard or reducer closure is not immutable",
                details={"edge_id": edge_id},
            )
        for reference in guards:
            _workflow_runtime_validate_action_reference(
                services,
                reference,
                registry="guards",
                edge_id=edge_id,
            )
        for reference in reducers:
            _workflow_runtime_validate_action_reference(
                services,
                reference,
                registry="reducers",
                edge_id=edge_id,
            )
        if not reducers:
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action has no registered reducer",
                details={"edge_id": edge_id},
            )
        if gate is not None:
            _workflow_runtime_validate_action_reference(
                services,
                gate,
                registry="gates",
                edge_id=edge_id,
            )
        for field in (
            "allowed_state_writes",
            "kernel_state_writes",
            "kernel_effects",
            "kernel_invalidates",
            "side_effects",
            "allowed_artifact_kinds",
            "required_suites",
        ):
            value = edge.get(field)
            if not isinstance(value, tuple) or len(value) != len(set(value)):
                raise _workflow_runtime_creation_error(
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                    "action write/effect/suite closure is not canonical",
                    details={"edge_id": edge_id, "field": field},
                )
        suites = set(edge["required_suites"])
        if not {
            "v4-static-closure",
            "v4-effect-recovery",
        }.issubset(suites):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "action omits a required policy or recovery suite",
                details={"edge_id": edge_id},
            )
        if edge.get("tool_policy") is not None and (
            "v4-external-tools" not in suites
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "external-tool action omits its capability/evidence suite",
                details={"edge_id": edge_id},
            )
        required_suites.update(str(item) for item in suites)
        _workflow_runtime_validate_action_effects(edge, edge_id=edge_id)
    _workflow_runtime_validate_repository_action_matrix(
        bundle, nodes, action_edges
    )
    if used_tool_capabilities != set(tool_capabilities):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "external-tool declarations and reachable actions differ",
            details={
                "unused": sorted(
                    set(tool_capabilities) - used_tool_capabilities
                ),
                "undeclared": sorted(
                    used_tool_capabilities - set(tool_capabilities)
                ),
            },
        )
    return frozenset(required_suites)


def _workflow_runtime_validate_activation_readiness(
    services: WorkflowRuntimeServices,
    bundle: object,
    activation: Mapping[str, object],
    execution_profile: str,
) -> None:
    """Recheck executable reachability at the creation boundary.

    Catalog loading proves structural validity.  Creation additionally binds
    the exact activation identity, completed safety suites, sealed registries,
    every reachable node contract, and every referenced handler.  This check
    intentionally runs under task-creation serialization so a partially
    initialized runtime can never commit revision one.
    """

    if activation.get("active") is not True:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_INACTIVE",
            "schema-v4 creation is inactive for this workflow profile",
            details={
                "workflow_id": getattr(bundle, "workflow_id", None),
                "workflow_version": getattr(
                    bundle, "workflow_version", None
                ),
                "bundle_sha256": getattr(
                    bundle, "bundle_sha256", None
                ),
                "execution_profile": execution_profile,
            },
        )
    if (
        activation.get("bundle_sha256")
        != getattr(bundle, "bundle_sha256", None)
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_IDENTITY_MISMATCH",
            "active creation profile does not bind the selected bundle",
            details={
                "activation_bundle_sha256": activation.get(
                    "bundle_sha256"
                ),
                "selected_bundle_sha256": getattr(
                    bundle, "bundle_sha256", None
                ),
                "execution_profile": execution_profile,
            },
        )
    profiles = getattr(bundle, "execution_profiles", ())
    if execution_profile not in profiles:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_PROFILE_UNSUPPORTED",
            "selected workflow does not support this execution profile",
            details={
                "workflow_id": getattr(bundle, "workflow_id", None),
                "execution_profile": execution_profile,
                "supported_profiles": list(profiles),
            },
        )
    required = WORKFLOW_V4_REQUIRED_SUITES.get(
        (getattr(bundle, "workflow_id", None), execution_profile)
    )
    if required is None:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_PROFILE_UNSUPPORTED",
            "controller does not implement this execution profile",
            details={"execution_profile": execution_profile},
        )
    declared = activation.get("required_suites")
    completed = {
        item
        for item in (
            declared if isinstance(declared, (list, tuple)) else ()
        )
        if isinstance(item, str)
    }
    missing_suites = sorted(required - completed)
    if missing_suites:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "active workflow profile lacks required safety evidence",
            details={
                "workflow_id": getattr(bundle, "workflow_id", None),
                "execution_profile": execution_profile,
                "missing_suites": missing_suites,
            },
        )
    registries = services.registries
    if getattr(registries, "sealed", None) is not True or not all(
        getattr(registry, "sealed", None) is True
        for registry in registries.all()
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "workflow registries are not completely sealed",
            details={"execution_profile": execution_profile},
        )
    nodes = getattr(bundle, "nodes", None)
    edges = getattr(bundle, "edges", None)
    graph = getattr(bundle, "graph", None)
    if (
        not isinstance(nodes, Mapping)
        or not isinstance(edges, tuple)
        or not isinstance(graph, Mapping)
        or V4_TASK_SCHEMA_VERSION
        not in tuple(graph.get("task_schema_versions", ()))
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "selected bundle lacks a complete schema-v4 graph",
            details={"execution_profile": execution_profile},
        )
    for node_id, node in nodes.items():
        kind = node.get("kind")
        version = node.get("contract_version")
        if version not in _workflow_catalog_supported_node_contracts.get(
            kind, ()
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "reachable node contract is not enabled",
                details={
                    "node_id": node_id,
                    "kind": kind,
                    "contract_version": version,
                },
            )
        recovery = node.get("recovery_policy")
        if (
            not isinstance(recovery, Mapping)
            or recovery.get("mode")
            not in _workflow_catalog_supported_node_recovery_modes
            or recovery.get("on_uncertain")
            not in _workflow_catalog_supported_node_uncertain_outcomes
        ):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_ACTIVATION_INCOMPLETE",
                "reachable node recovery contract is not enabled",
                details={"node_id": node_id},
            )
    broken_edges = [
        (
            {
                "edge_id": edge.get("id"),
                "source": edge.get("source"),
                "target": edge.get("target"),
            }
            if isinstance(edge, Mapping)
            else {"edge_id": None, "source": None, "target": None}
        )
        for edge in edges
        if not isinstance(edge, Mapping)
        or edge.get("source") not in nodes
        or edge.get("target") not in nodes
    ]
    if broken_edges:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "active workflow contains an unreachable or broken edge",
            details={"edges": broken_edges},
        )
    action_required_suites = _workflow_runtime_validate_action_closure(
        services, bundle, nodes, graph
    )
    if execution_profile == "single-repository":
        action_required_suites = frozenset(
            suite
            for suite in action_required_suites
            if suite != "v4-multi-repository"
        )
    missing_action_suites = sorted(
        action_required_suites - completed
    )
    if missing_action_suites:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "active workflow profile lacks required action-closure evidence",
            details={
                "workflow_id": getattr(bundle, "workflow_id", None),
                "execution_profile": execution_profile,
                "missing_suites": missing_action_suites,
            },
        )
    resolver = services.handler_resolver
    try:
        for contract in getattr(bundle, "contracts", ()):
            registration = resolver.resolve(
                contract.registry,
                contract.identifier,
                contract.version,
            )
            role = _WORKFLOW_RUNTIME_ACTION_REFERENCE_ROLES.get(
                contract.registry
            )
            if role is None:
                raise WorkflowHandlerAuditError(
                    "HANDLER_BINDING_UNAVAILABLE",
                    "active workflow contract has no executable role",
                    details={
                        "registry": contract.registry,
                        "identifier": contract.identifier,
                        "version": contract.version,
                    },
                )
            implementation = resolver.resolve_callable(
                contract.registry,
                contract.identifier,
                contract.version,
                role,
            )
            if (
                contract.registry == "executors"
                and contract.identifier.startswith("executor.v4-")
                and implementation
                is globals().get("_disabled_executor_dispatch")
            ):
                raise WorkflowHandlerAuditError(
                    "HANDLER_BINDING_DISABLED",
                    "activation readiness rejects descriptor-only executors",
                    details={
                        "registry": contract.registry,
                        "identifier": contract.identifier,
                        "version": contract.version,
                    },
                )
            if contract.registry in {
                "guards",
                "reducers",
                "gates",
            }:
                capabilities = tuple(
                    getattr(registration, "capabilities", ())
                )
                resolver.capability_membrane(
                    contract.registry,
                    contract.identifier,
                    contract.version,
                    queries=(
                        {
                            capability: (
                                lambda projection: projection
                            )
                            for capability in capabilities
                        }
                        if contract.registry == "guards"
                        else None
                    ),
                )
    except (
        WorkflowRegistryError,
        WorkflowHandlerAuditError,
    ) as exc:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_ACTIVATION_INCOMPLETE",
            "active workflow references an unavailable package handler",
            details={
                "registry_error": exc.code,
                **dict(exc.details),
            },
        ) from exc


def select_task_creation_workflow(
    flow: str,
    repository_count: int,
    *,
    services: WorkflowRuntimeServices | None = None,
) -> Mapping[str, object]:
    """Select one exact active schema-v4 workflow profile."""

    if flow not in {"full", "lite"}:
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_FLOW_INVALID",
            "workflow creation flow must be full or lite",
            details={"flow": flow},
        )
    execution_profile = workflow_creation_execution_profile(
        repository_count
    )
    runtime = services or workflow_runtime_services()

    bundle = runtime.catalog.resolve(flow, WORKFLOW_V4_VERSION)
    activation = _workflow_runtime_activation_entry(
        runtime.catalog, bundle, execution_profile
    )
    _workflow_runtime_validate_activation_readiness(
        runtime, bundle, activation, execution_profile
    )
    return MappingProxyType(
        {
            "schema_version": V4_TASK_SCHEMA_VERSION,
            "kind": "bundle",
            "flow": flow,
            "execution_profile": execution_profile,
            "bundle": bundle,
        }
    )


def _workflow_runtime_node_instance_id(
    task_id: str,
    bundle_sha256: str,
    node_id: str,
    occurrence: int,
) -> str:
    payload = {
        "contract": "dev-flow-node-instance-identity/v1",
        "task_id": task_id,
        "bundle_sha256": bundle_sha256,
        "node_id": node_id,
        "occurrence": occurrence,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:24]
    return f"node:{node_id.lower()}:{occurrence}:{digest}"


def build_v4_task_creation_fields(
    task_id: str,
    bundle: object,
    *,
    execution_profile: str,
) -> dict[str, object]:
    """Build exact pinned identity and deterministic initial node instances."""

    graph = getattr(bundle, "graph", None)
    nodes = getattr(bundle, "nodes", None)
    if not isinstance(graph, Mapping) or not isinstance(nodes, Mapping):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_BUNDLE_INVALID",
            "selected bundle has no validated graph",
        )
    profiles = tuple(getattr(bundle, "execution_profiles", ()))
    if (
        (getattr(bundle, "workflow_id", None), execution_profile)
        not in WORKFLOW_V4_REQUIRED_SUITES
        or execution_profile not in profiles
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_PROFILE_UNSUPPORTED",
            "v4 creation fields require an exact bundle execution profile",
            details={
                "execution_profile": execution_profile,
                "supported_profiles": list(profiles),
            },
        )
    orchestration = getattr(
        bundle, "repository_orchestration", None
    )
    if (
        execution_profile == "multi-repository"
        and not isinstance(orchestration, Mapping)
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_BUNDLE_INVALID",
            "multi-repository creation requires pinned orchestration metadata",
            details={"execution_profile": execution_profile},
        )
    if (
        execution_profile == "single-repository"
        and orchestration is not None
        and "multi-repository" not in profiles
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_BUNDLE_INVALID",
            "single-only bundles cannot carry repository orchestration metadata",
            details={"execution_profile": execution_profile},
        )
    entry_nodes = tuple(graph.get("entry_nodes", ()))
    if not entry_nodes or any(
        not isinstance(item, str) or item not in nodes
        for item in entry_nodes
    ):
        raise _workflow_runtime_creation_error(
            "WORKFLOW_CREATION_BUNDLE_INVALID",
            "selected bundle has no valid entry node",
        )
    bundle_sha256 = str(getattr(bundle, "bundle_sha256", ""))
    instances = [
        {
            "node_instance_id": _workflow_runtime_node_instance_id(
                task_id, bundle_sha256, str(node_id), 1
            ),
            "node_id": str(node_id),
            "state": (
                "READY" if node_id in entry_nodes else "PENDING"
            ),
            "dependencies": [],
            "attempts": [],
        }
        for node_id in nodes
    ]
    instances.sort(
        key=lambda item: str(item["node_instance_id"]).encode("utf-8")
    )
    fields: dict[str, object] = {
        "execution_profile": execution_profile,
        "workflow_ref": {
            "id": getattr(bundle, "workflow_id", None),
            "version": getattr(bundle, "workflow_version", None),
            "schema": graph.get("schema"),
            "graph_sha256": getattr(bundle, "graph_sha256", None),
            "bundle_sha256": bundle_sha256,
        },
        "node_instances": instances,
    }
    if execution_profile == "multi-repository":
        orchestration_factory = globals().get("_osc_empty_state")
        if not callable(orchestration_factory):
            raise _workflow_runtime_creation_error(
                "WORKFLOW_CREATION_RUNTIME_INCOMPLETE",
                "multi-repository creation requires the versioned "
                "orchestration state factory",
            )
        fields["orchestration"] = orchestration_factory()
    return fields


def _workflow_runtime_bundle_resolver(
    reference: Mapping[str, object],
) -> object:
    services = workflow_runtime_services()
    bundle_sha256 = reference.get("bundle_sha256")
    try:
        bundle = services.catalog.resolve_identity(str(bundle_sha256))
    except WorkflowCatalogError as exc:
        raise WorkflowStateError(
            exc.code,
            exc.message,
            details={
                **dict(exc.details),
                "workflow_id": reference.get("id"),
                "workflow_version": reference.get("version"),
                "bundle_sha256": bundle_sha256,
            },
        ) from exc
    if (
        getattr(bundle, "workflow_id", None) != reference.get("id")
        or getattr(bundle, "workflow_version", None)
        != reference.get("version")
    ):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_MISMATCH",
            "bundle identity resolves to a different workflow ID or version",
            details={
                "expected": {
                    "id": reference.get("id"),
                    "version": reference.get("version"),
                    "bundle_sha256": bundle_sha256,
                },
                "actual": {
                    "id": getattr(bundle, "workflow_id", None),
                    "version": getattr(bundle, "workflow_version", None),
                    "bundle_sha256": getattr(
                        bundle, "bundle_sha256", None
                    ),
                },
            },
        )
    return bundle


def resolve_loaded_task_workflow(
    state: Mapping[str, object],
    *,
    purpose: str,
    candidate_state: Mapping[str, object] | None = None,
    candidate_event_type: str | None = None,
    payload: Mapping[str, object] | None = None,
    creation_task_id: str | None = None,
    creation_repository_count: int | None = None,
) -> Mapping[str, object]:
    """Resolve a persisted task only through the sealed process catalog."""

    services = workflow_runtime_services()
    if purpose == "creation":
        flow = state.get("flow")
        if (
            not isinstance(flow, str)
            or not isinstance(creation_task_id, str)
            or not creation_task_id
            or creation_repository_count is None
        ):
            raise WorkflowStateError(
                "WORKFLOW_CREATION_CONTEXT_INVALID",
                "workflow creation requires flow, task, and repository count",
            )
        selection = select_task_creation_workflow(
            flow,
            creation_repository_count,
            services=services,
        )
        result = {
            key: value
            for key, value in selection.items()
            if key != "bundle"
        }
        bundle = selection.get("bundle")
        if bundle is not None:
            result["creation_fields"] = build_v4_task_creation_fields(
                creation_task_id,
                bundle,
                execution_profile=str(selection["execution_profile"]),
            )
        return _workflow_runtime_public_value(result)  # type: ignore[return-value]
    resolution = resolve_task_workflow(
        state,
        bundle_resolver=_workflow_runtime_bundle_resolver,
        purpose=purpose,
    )
    if candidate_state is not None:
        if purpose != "mutation" or not isinstance(
            candidate_event_type, str
        ):
            raise WorkflowStateError(
                "WORKFLOW_MOVEMENT_CONTEXT_INVALID",
                "candidate movement requires a mutation event identity",
            )
        try:
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_PROOF_REQUIRED",
                (
                    "schema-v4 candidates must be evaluated and committed "
                    "through the one-shot engine proof boundary"
                ),
            )
        except TransitionEngineError as exc:
            raise WorkflowStateError(
                exc.code, exc.message, details=exc.details
            ) from exc
    return resolution


def _workflow_runtime_public_value(value: object) -> object:
    """Copy immutable runtime descriptors into protocol-safe JSON values."""

    if isinstance(value, Mapping):
        return {
            str(key): _workflow_runtime_public_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _workflow_runtime_public_value(item) for item in value
        ]
    return value


def inspect_loaded_task_state(
    state: object,
) -> dict[str, object]:
    """Inspect persisted workflow identity without authorizing side effects."""

    inspection = inspect_task_state(
        state,
        resolver=resolve_loaded_task_workflow,
    )
    public = _workflow_runtime_public_value(inspection)
    if not isinstance(public, dict):  # Defensive: helper returns an object.
        raise TypeError("workflow inspection did not produce an object")
    return public
