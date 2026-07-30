# Loaded by the future bundle-aware controller into the same shared namespace
# as the legacy runtime fragments.  It is also intentionally importable in
# isolation for package validation.  Keep this module standard-library only.
"""Static package handler manifests, binding audit, and registry initialization.

The loader has one deliberately narrow source of registrations: the five
package-relative manifests named by its private fixed inventory. It does not inspect
target repositories, task data, environment variables, Python entry points,
or importable modules.  Handler bindings are late-bound by one shared-runtime
global name so the first registry migration does not change monkeypatch or
ordered-fragment behavior.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import os
import re
import stat
import struct
import unicodedata
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path, PurePosixPath
from types import CodeType, MappingProxyType
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence, Tuple


HANDLER_MANIFEST_VERSION = "dev-flow-handler-registration-manifest/v1"
HANDLER_AUDIT_POLICY = "dev-flow-handler-audit/v1"
HANDLER_IMPLEMENTATION_DOMAIN = b"dev-flow-handler-implementation-v1\x00"

_workflow_handlers_manifest_paths = MappingProxyType(
    {
        "commands": "workflows/runtime/commands.json",
        "guards": "workflows/runtime/guards.json",
        "reducers": "workflows/runtime/reducers.json",
        "gates": "workflows/runtime/gates.json",
        "executors": "workflows/runtime/executors.json",
    }
)
_workflow_handlers_registration_type_names = MappingProxyType(
    {
        "commands": "CommandRegistration",
        "guards": "GuardRegistration",
        "reducers": "ReducerRegistration",
        "gates": "GateRegistration",
        "executors": "ExecutorRegistration",
    }
)
_workflow_handlers_symbol_roles = MappingProxyType(
    {
        "commands": ("handler", "parser_factory"),
        "guards": ("evaluator",),
        "reducers": ("reducer",),
        "gates": ("builder",),
        "executors": ("dispatcher",),
    }
)
_workflow_handlers_contract_ids = MappingProxyType(
    {
        "commands": "dev-flow-command/v1",
        "guards": "dev-flow-guard/v1",
        "reducers": "dev-flow-reducer/v1",
        "gates": "dev-flow-gate/v1",
        "executors": "dev-flow-executor/v1",
    }
)
_workflow_handlers_schema_refs = frozenset(
    {
        "schema.command.arguments/v1",
        "schema.command.result/v1",
        "schema.executor.request/v1",
        "schema.executor.result/v1",
        "schema.gate.projection/v1",
        "schema.gate.result/v1",
        "schema.guard.projection/v1",
        "schema.guard.result/v1",
        "schema.reducer.projection/v1",
        "schema.reducer.result/v1",
    }
)

_workflow_handlers_top_level_fields = frozenset(
    {
        "audit_policy",
        "entries",
        "implementation_file_sets",
        "manifest_version",
        "registry",
    }
)
_workflow_handlers_common_entry_fields = frozenset(
    {
        "audit",
        "authority",
        "capabilities",
        "contract_id",
        "id",
        "implementation_file_set",
        "input_schema_ref",
        "output_schema_ref",
        "symbols",
    }
)
_workflow_handlers_kind_entry_fields = MappingProxyType(
    {
        "commands": frozenset(
            {"action_id", "command", "parser_order"}
        ),
        "guards": frozenset(),
        "reducers": frozenset(),
        "gates": frozenset(),
        "executors": frozenset({"effect_classification"}),
    }
)
_workflow_handlers_audit_fields = frozenset(
    {"allowed_globals", "allowed_imports", "profile"}
)
_workflow_handlers_implementation_file_fields = frozenset({"kind", "path"})
_workflow_handlers_file_kinds = frozenset({"J", "T", "B"})
_workflow_handlers_effect_classifications = frozenset(
    {
        "barrier",
        "deterministic",
        "external",
        "human",
        "read-only",
        "workspace-write",
    }
)
_workflow_handlers_audit_profiles_by_kind = MappingProxyType(
    {
        "commands": frozenset({"legacy-controller-v1"}),
        "guards": frozenset(
            {"legacy-read-only-wrapper-v1", "pure-v1"}
        ),
        "reducers": frozenset({"pure-v1"}),
        "gates": frozenset({"legacy-controller-v1", "pure-v1"}),
        "executors": frozenset({"pure-v1"}),
    }
)
_workflow_handlers_legacy_runtime_allowed_imports = frozenset(
    {
        "__future__",
        "argparse",
        "copy",
        "contextlib",
        "contextvars",
        "dataclasses",
        "datetime",
        "errno",
        "fcntl",
        "hashlib",
        "hmac",
        "json",
        "msvcrt",
        "os",
        "pathlib",
        "re",
        "secrets",
        "shlex",
        "shutil",
        "socket",
        "stat",
        "struct",
        "subprocess",
        "sys",
        "tarfile",
        "tempfile",
        "threading",
        "time",
        "typing",
        "unicodedata",
        "urllib",
        "uuid",
    }
)
_workflow_handlers_legacy_kernel_globals = frozenset(
    {
        "__file__",
        "V3_TASK_SCHEMA_VERSION",
        "WorkflowCatalogError",
        "WorkflowHandlerAuditError",
        "WorkflowProjectionError",
        "WorkflowStateError",
        "WORKFLOW_AGENT_PROFILE",
        "ActionOutcome",
        "ApprovalOutcome",
        "AuditFact",
        "TransitionEngineError",
        "TransitionEvaluation",
        "WorkflowActionDispatchContext",
        "WorkflowActionEffectBinding",
        "WorkflowActionEffectObservation",
        "WorkflowActionInvocation",
        "WorkflowActionTransactionError",
        "WorkflowActionTransactionResult",
        "_v3_command_approve_commit",
        "_v3_command_set_route_commit",
        "_manager_workflow_action_authorization_v1",
        "_workflow_transition_exact_state_delta",
        "_workflow_transition_public",
        "action_execution_active_path",
        "action_execution_archive_path",
        "build_workflow_task_next",
        "commit_v3_workflow_action",
        "evaluate_v3_node_action",
        "execute_v3_workflow_action_transaction",
        "inspect_loaded_task_state",
        "manager_command_action_ids_v1",
        "manager_authority_transaction_service_v1",
        "manager_process_commit_gate_v1",
        "preview_v3_workflow_action_transaction",
        "recover_v3_workflow_action_transaction",
        "resolve_v3_node_action_edge",
        "resolve_v3_workflow_action_completion_edge",
        "resolve_loaded_task_workflow",
        "semantic_sha256",
        "v3_command_movement_commit_v1",
        "v3_command_movement_evaluate_v1",
        "v3_command_movement_preview_v1",
        "validate_task_state_for_mutation",
        "validate_v3_task_state",
        "v3_record_test_command_v1",
        "v3_review_snapshot_command_v1",
        "workflow_action_recovery_apply_v1",
        "workflow_action_recovery_inspect_v1",
        "workflow_action_recovery_preview_v1",
    }
)
_workflow_handlers_legacy_read_only_kernel_globals = frozenset(
    {
        "EVIDENCE_CONTRACT_VERSION",
        "FlowError",
        "LITE_GATE",
        "SCHEMA_VERSION",
        "_analysis_workspace_integrity_error",
        "_assert_branch_checkout_binding",
        "_capture_lite_change_assessment",
        "_current_repository_fingerprints",
        "_fingerprint_repo",
        "_flow",
        "_git_optional",
        "_index_provenance_evidence",
        "_json_bytes",
        "_latest_passing_test_is_current",
        "_lite_preflight_evidence_sha256",
        "_lite_transition_guard",
        "_live_approved_remote_url",
        "_load_recorded_fingerprint",
        "_planning_context_sha256",
        "_preflight_remote_evidence_sha256",
        "_recorded_path_matches",
        "_require_current_evidence",
        "_require_current_plan_artifact",
        "_require_current_plan_gate",
        "_require_current_route_selection",
        "_require_current_workspace_indexes",
        "_require_gate",
        "_require_gate_for_latest_artifact",
        "_require_lite_gate",
        "_require_review_gate",
        "_require_review_report_for_latest_snapshot",
        "_require_route_gate",
        "_require_workspace_ready",
        "_review_is_current",
        "_review_snapshot_integrity_error",
        "_sha256_bytes",
        "_sha256_file",
        "_test_identity",
        "_uses_confirmation_contract",
        "_validate_degraded_index_metadata",
        "_working_path",
        "_workspace_index_staleness",
        "_workspace_integrity_error",
        "_workspace_plan_evidence",
    }
)
_workflow_handlers_forbidden_in_process_imports = frozenset(
    {
        "ctypes",
        "ftplib",
        "http",
        "importlib",
        "multiprocessing",
        "pkg_resources",
        "requests",
        "shutil",
        "smtplib",
        "socket",
        "subprocess",
        "urllib",
    }
)
_workflow_handlers_pure_allowed_imports = frozenset(
    {
        "collections",
        "dataclasses",
        "hashlib",
        "json",
        "re",
        "types",
        "typing",
    }
)
_workflow_handlers_forbidden_in_process_names = frozenset(
    {
        "__import__",
        "_commit_state",
        "_execute_worktree",
        "_git",
        "_git_mutating",
        "_run",
        "compile",
        "delattr",
        "eval",
        "exec",
        "globals",
        "locals",
        "open",
        "setattr",
        "vars",
    }
)
_workflow_handlers_forbidden_in_process_prefixes = (
    "_atomic_write",
    "_discard_",
    "_restore_",
    "_store_",
    "command_",
)
_workflow_handlers_forbidden_mutating_attributes = frozenset(
    {
        "__delitem__",
        "__iand__",
        "__ior__",
        "__isub__",
        "__ixor__",
        "__setitem__",
        "add",
        "chmod",
        "commit",
        "connect",
        "entry_points",
        "exec",
        "execute",
        "kill",
        "mkdir",
        "open",
        "popen",
        "putenv",
        "register",
        "remove",
        "rename",
        "replace",
        "reset",
        "rmdir",
        "run",
        "send",
        "spawn",
        "symlink_to",
        "terminate",
        "touch",
        "unlink",
        "unsetenv",
        "write",
        "write_bytes",
        "write_text",
        "__setattr__",
        "system",
    }
)
_workflow_handlers_mutating_input_methods = frozenset(
    {
        "add",
        "append",
        "clear",
        "difference_update",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)
_workflow_handlers_allowed_guard_capabilities = frozenset(
    {"legacy.kernel-evidence-read"}
)
# Annotation nodes are deliberately skipped by the private reference visitor;
# a typing name used in executable code remains an audited global.
_workflow_handlers_type_only_globals: frozenset[str] = frozenset()
_workflow_handlers_builtin_names = frozenset(dir(builtins))

_workflow_handlers_handler_id_re = re.compile(
    r"^(?P<identifier>[a-z][a-z0-9._-]*(?:/[a-z][a-z0-9._-]*)*)/"
    r"(?P<version>v[1-9][0-9]*)$"
)
_workflow_handlers_contract_id_re = re.compile(
    r"^[a-z][a-z0-9._-]*(?:/[a-z][a-z0-9._-]*)*/v[1-9][0-9]*$"
)
_workflow_handlers_schema_ref_re = re.compile(
    r"^schema\.[a-z][a-z0-9._-]*/v[1-9][0-9]*$"
)
_workflow_handlers_symbol_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_workflow_handlers_capability_re = re.compile(
    r"^[a-z][a-z0-9._-]*(?:/[a-z][a-z0-9._-]*)*$"
)
_workflow_handlers_file_set_re = re.compile(r"^[a-z][a-z0-9._-]*$")
_workflow_handlers_portable_segment_re = re.compile(r"^[A-Za-z0-9._-]+$")
_workflow_handlers_glob_characters = frozenset("*?[]{}")
_workflow_handlers_utf8_bom = b"\xef\xbb\xbf"
_workflow_handlers_signed_int64_min = -(2**63)
_workflow_handlers_signed_int64_max = 2**63 - 1


class WorkflowHandlerAuditError(ValueError):
    """Stable, structured failure raised before registry mutation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, object]] = None,
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


@dataclass(frozen=True)
class ImplementationFileDeclaration:
    """One exact, explicitly classified package implementation file."""

    path: str
    kind: str


@dataclass(frozen=True)
class ImplementationFileSet:
    """Exact implementation bytes plus audited semantic entry points."""

    files: Tuple[ImplementationFileDeclaration, ...]
    semantic_roots: Tuple[str, ...] = ()


@dataclass(frozen=True)
class HandlerRegistrationSpec:
    """One immutable, audited registration description."""

    registry_kind: str
    handler_id: str
    identifier: str
    contract_version: str
    contract_id: str
    authority: Tuple[str, ...]
    capabilities: Tuple[str, ...]
    input_schema_ref: str
    output_schema_ref: str
    implementation_files: Tuple[ImplementationFileDeclaration, ...]
    implementation_sha256: str
    symbols: Mapping[str, str]
    semantic_roots: Tuple[str, ...]
    audit_profile: str
    allowed_globals: Tuple[str, ...]
    allowed_imports: Tuple[str, ...]
    command: Optional[str] = None
    action_id: Optional[str] = None
    parser_order: Optional[int] = None
    effect_classification: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority", tuple(self.authority))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(
            self, "implementation_files", tuple(self.implementation_files)
        )
        object.__setattr__(
            self, "symbols", MappingProxyType(dict(self.symbols))
        )
        object.__setattr__(
            self, "semantic_roots", tuple(self.semantic_roots)
        )
        object.__setattr__(
            self, "allowed_globals", tuple(self.allowed_globals)
        )
        object.__setattr__(
            self, "allowed_imports", tuple(self.allowed_imports)
        )


@dataclass(frozen=True)
class HandlerRegistrationManifest:
    """One of the five fixed package manifest documents."""

    registry_kind: str
    path: str
    entries: Tuple[HandlerRegistrationSpec, ...]


def _workflow_handlers_validate_command_parser_registrations(
    entries: Sequence[HandlerRegistrationSpec],
) -> None:
    command_names = [item.command for item in entries]
    parser_orders = [item.parser_order for item in entries]
    parser_factories = [
        item.symbols["parser_factory"] for item in entries
    ]

    def duplicates(values: Sequence[object]) -> list[object]:
        return sorted(
            {
                item
                for item in values
                if values.count(item) > 1
            }
        )

    duplicate_commands = duplicates(command_names)
    duplicate_orders = duplicates(parser_orders)
    duplicate_factories = duplicates(parser_factories)
    if (
        duplicate_commands
        or duplicate_orders
        or duplicate_factories
        or sorted(parser_orders) != list(range(len(entries)))
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_COMMAND_PARSER_REGISTRATION_INVALID",
            (
                "command spellings, parser factories, and contiguous "
                "parser orders must be unique"
            ),
            details={
                "duplicate_commands": duplicate_commands,
                "duplicate_parser_orders": duplicate_orders,
                "duplicate_parser_factories": duplicate_factories,
                "parser_orders": sorted(parser_orders),
            },
        )


class PackageHandlerResolver:
    """Sealed catalog facade over audited package registrations and identity."""

    def __init__(
        self,
        registries: object,
        manifests: Sequence[HandlerRegistrationManifest],
        package_root: os.PathLike[str],
        identity_api: object,
    ) -> None:
        if not bool(getattr(registries, "sealed", False)):
            raise WorkflowHandlerAuditError(
                "HANDLER_REGISTRY_UNSEALED",
                "catalog handler resolution requires sealed registries",
            )
        root = Path(package_root).resolve()
        if not root.is_dir():
            raise WorkflowHandlerAuditError(
                "HANDLER_PACKAGE_ROOT_INVALID",
                "handler package root must be an existing directory",
                details={"package_root": str(root)},
            )
        specs: dict[
            Tuple[str, str, str], HandlerRegistrationSpec
        ] = {}
        for manifest in manifests:
            if manifest.registry_kind not in _workflow_handlers_manifest_paths:
                raise WorkflowHandlerAuditError(
                    "HANDLER_MANIFEST_REGISTRY_MISMATCH",
                    "resolver received an unsupported handler registry",
                    details={"registry": manifest.registry_kind},
                )
            for spec in manifest.entries:
                key = (
                    manifest.registry_kind,
                    spec.identifier,
                    spec.contract_version,
                )
                if key in specs:
                    raise WorkflowHandlerAuditError(
                        "HANDLER_ID_DUPLICATE",
                        "resolver handler identities must be unique",
                        details={
                            "registry": key[0],
                            "identifier": key[1],
                            "version": key[2],
                        },
                    )
                specs[key] = spec
        for symbol in (
            "BundleFile",
            "HandlerImplementation",
            "handler_implementation_sha256",
        ):
            if not callable(getattr(identity_api, symbol, None)):
                raise WorkflowHandlerAuditError(
                    "HANDLER_IDENTITY_API_INVALID",
                    "handler identity API is missing a required operation",
                    details={"symbol": symbol},
                )
        self._registries = registries
        self._manifests = tuple(manifests)
        self._package_root = root
        self._identity_api = identity_api
        self._specs = MappingProxyType(specs)
        self.sealed = True

    @property
    def references(self) -> frozenset[Tuple[str, str, str]]:
        return frozenset(self._specs)

    def resolve(
        self, registry: str, identifier: str, version: str
    ) -> object:
        key = (registry, identifier, version)
        try:
            spec = self._specs[key]
        except KeyError as exc:
            raise WorkflowHandlerAuditError(
                "HANDLER_REFERENCE_UNKNOWN",
                "catalog references an unregistered package handler",
                details={
                    "registry": registry,
                    "identifier": identifier,
                    "version": version,
                },
            ) from exc
        typed_registry = getattr(self._registries, registry, None)
        resolve = getattr(typed_registry, "resolve", None)
        if not callable(resolve):
            raise WorkflowHandlerAuditError(
                "HANDLER_REGISTRY_INTERFACE_INVALID",
                "sealed registry set lacks a typed resolver",
                details={"registry": registry},
            )
        registration = resolve(identifier, version)
        if (
            getattr(registration, "implementation_sha256", None)
            != spec.implementation_sha256
        ):
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPLEMENTATION_IDENTITY_MISMATCH",
                "registered handler digest differs from its audited manifest",
                details={
                    "registry": registry,
                    "identifier": identifier,
                    "version": version,
                },
            )
        return registration

    def resolve_callable(
        self,
        registry: str,
        identifier: str,
        version: str,
        role: str,
    ) -> Callable[..., object]:
        """Resolve only the callable frozen during package initialization."""

        self.resolve(registry, identifier, version)
        typed_registry = getattr(self._registries, registry, None)
        resolver = getattr(typed_registry, "resolve_callable", None)
        if not callable(resolver):
            raise WorkflowHandlerAuditError(
                "HANDLER_REGISTRY_INTERFACE_INVALID",
                "sealed registry lacks a frozen executable resolver",
                details={"registry": registry},
            )
        try:
            implementation = resolver(identifier, version, role)
        except Exception as exc:
            if getattr(exc, "code", None) is not None:
                raise
            raise WorkflowHandlerAuditError(
                "HANDLER_BINDING_UNAVAILABLE",
                "frozen package handler binding is unavailable",
                details={
                    "registry": registry,
                    "identifier": identifier,
                    "version": version,
                    "role": role,
                },
            ) from exc
        if not callable(implementation):
            raise WorkflowHandlerAuditError(
                "HANDLER_BINDING_UNAVAILABLE",
                "frozen package handler binding is not callable",
                details={
                    "registry": registry,
                    "identifier": identifier,
                    "version": version,
                    "role": role,
                },
            )
        return implementation

    def capability_membrane(
        self,
        registry: str,
        identifier: str,
        version: str,
        *,
        queries: Optional[Mapping[str, Callable[..., object]]] = None,
    ) -> object:
        """Construct the minimum immutable in-process capability membrane."""

        registration = self.resolve(registry, identifier, version)
        declared = tuple(
            getattr(registration, "capabilities", ())
        )
        supplied = {} if queries is None else dict(queries)
        unknown = sorted(set(supplied) - set(declared))
        missing = sorted(set(declared) - set(supplied))
        if unknown or missing:
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_BINDING_MISMATCH",
                "runtime capability bindings must exactly match registration",
                details={
                    "registry": registry,
                    "identifier": identifier,
                    "version": version,
                    "missing": missing,
                    "unknown": unknown,
                },
            )
        if registry == "guards":
            return GuardCapabilities(_queries=supplied)
        if registry == "reducers":
            if declared:
                raise WorkflowHandlerAuditError(
                    "HANDLER_CAPABILITY_FORBIDDEN",
                    "reducers cannot receive runtime capabilities",
                    details={
                        "identifier": identifier,
                        "capabilities": list(declared),
                    },
                )
            return ReducerCapabilities()
        if registry == "gates":
            if declared:
                raise WorkflowHandlerAuditError(
                    "HANDLER_CAPABILITY_FORBIDDEN",
                    "pure gate builders cannot receive runtime capabilities",
                    details={
                        "identifier": identifier,
                        "capabilities": list(declared),
                    },
                )
            return GateCapabilities()
        raise WorkflowHandlerAuditError(
            "HANDLER_CAPABILITY_REGISTRY_UNSUPPORTED",
            "only in-process guards, reducers, and gates use kernel membranes",
            details={"registry": registry},
        )

    def identity_handlers(
        self, references: Sequence[object]
    ) -> Tuple[object, ...]:
        """Return exact identity-module handlers for reachable contracts."""

        selected: dict[str, HandlerRegistrationSpec] = {}
        for reference in references:
            if isinstance(reference, Mapping):
                registry = reference.get("registry")
                identifier = reference.get("identifier", reference.get("id"))
                version = reference.get("version")
            else:
                registry = getattr(reference, "registry", None)
                identifier = getattr(reference, "identifier", None)
                version = getattr(reference, "version", None)
            if not all(
                isinstance(item, str) and item
                for item in (registry, identifier, version)
            ):
                raise WorkflowHandlerAuditError(
                    "HANDLER_REFERENCE_INVALID",
                    "identity handler references must name registry, ID, and version",
                )
            key = (registry, identifier, version)
            try:
                spec = self._specs[key]
            except KeyError as exc:
                raise WorkflowHandlerAuditError(
                    "HANDLER_REFERENCE_UNKNOWN",
                    "identity references an unknown package handler",
                    details={
                        "registry": registry,
                        "identifier": identifier,
                        "version": version,
                    },
                ) from exc
            self.resolve(registry, identifier, version)
            selected[spec.handler_id] = spec

        bundle_file_type = getattr(self._identity_api, "BundleFile")
        handler_type = getattr(
            self._identity_api, "HandlerImplementation"
        )
        compute_sha256 = getattr(
            self._identity_api, "handler_implementation_sha256"
        )
        handlers: list[object] = []
        for handler_id in sorted(
            selected, key=lambda item: item.encode("utf-8")
        ):
            spec = selected[handler_id]
            files = tuple(
                bundle_file_type(
                    declaration.path,
                    declaration.kind,
                    _workflow_handlers_contained_regular_file(
                        self._package_root, declaration.path
                    ).read_bytes(),
                )
                for declaration in spec.implementation_files
            )
            observed = compute_sha256(
                spec.handler_id, spec.contract_id, files
            )
            if observed != spec.implementation_sha256:
                raise WorkflowHandlerAuditError(
                    "HANDLER_IMPLEMENTATION_IDENTITY_MISMATCH",
                    "package handler bytes changed after registry initialization",
                    details={"handler_id": spec.handler_id},
                )
            handlers.append(
                handler_type(spec.handler_id, spec.contract_id, files)
            )
        return tuple(handlers)


class GuardCapabilities:
    """Immutable membrane exposing only declared kernel evidence queries."""

    __slots__ = ("_contract_version", "_queries")

    def __init__(
        self,
        contract_version: str = "v1",
        _queries: Optional[Mapping[str, Callable[..., object]]] = None,
    ) -> None:
        if contract_version != "v1":
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_VERSION_UNSUPPORTED",
                "guard capability contract version is unsupported",
                details={"contract_version": contract_version},
            )
        if _queries is None:
            supplied_queries: Mapping[
                str, Callable[..., object]
            ] = {}
        elif isinstance(_queries, Mapping):
            supplied_queries = _queries
        else:
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_INVALID",
                "guard evidence queries must be a mapping",
            )
        frozen: dict[str, Callable[..., object]] = {}
        for capability, query in supplied_queries.items():
            if capability not in _workflow_handlers_allowed_guard_capabilities:
                raise WorkflowHandlerAuditError(
                    "HANDLER_CAPABILITY_FORBIDDEN",
                    "guard capability is not a declared read-only query",
                    details={"capability": capability},
                )
            if not callable(query):
                raise WorkflowHandlerAuditError(
                    "HANDLER_CAPABILITY_INVALID",
                    "guard evidence queries must be callable",
                    details={"capability": capability},
                )
            frozen[capability] = query
        object.__setattr__(self, "_contract_version", contract_version)
        object.__setattr__(self, "_queries", MappingProxyType(frozen))

    def __setattr__(self, _name: str, _value: object) -> None:
        raise FrozenInstanceError("cannot assign to immutable capabilities")

    @property
    def contract_version(self) -> str:
        return self._contract_version

    @property
    def available_queries(self) -> Tuple[str, ...]:
        return tuple(sorted(self._queries, key=lambda item: item.encode("utf-8")))

    def query(
        self, capability: str, projection: object
    ) -> object:
        try:
            query = self._queries[capability]
        except KeyError as exc:
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_UNDECLARED",
                "guard requested an undeclared evidence query",
                details={"capability": capability},
            ) from exc
        return query(projection)


class ReducerCapabilities:
    """Immutable reducer membrane; intentionally exposes no operations."""

    __slots__ = ("_contract_version",)

    def __init__(self, contract_version: str = "v1") -> None:
        if contract_version != "v1":
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_VERSION_UNSUPPORTED",
                "reducer capability contract version is unsupported",
                details={"contract_version": contract_version},
            )
        object.__setattr__(self, "_contract_version", contract_version)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise FrozenInstanceError("cannot assign to immutable capabilities")

    @property
    def contract_version(self) -> str:
        return self._contract_version


class GateCapabilities:
    """Immutable pure gate-builder membrane; exposes no side effects."""

    __slots__ = ("_contract_version",)

    def __init__(self, contract_version: str = "v1") -> None:
        if contract_version != "v1":
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_VERSION_UNSUPPORTED",
                "gate capability contract version is unsupported",
                details={"contract_version": contract_version},
            )
        object.__setattr__(self, "_contract_version", contract_version)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise FrozenInstanceError("cannot assign to immutable capabilities")

    @property
    def contract_version(self) -> str:
        return self._contract_version


class _workflow_handlers_DuplicateObjectKey(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _workflow_handlers_strict_object(
    pairs: Sequence[Tuple[str, object]]
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _workflow_handlers_DuplicateObjectKey(key)
        value[key] = item
    return value


def _workflow_handlers_parse_int(value: str) -> int:
    parsed = int(value)
    if not (
        _workflow_handlers_signed_int64_min
        <= parsed
        <= _workflow_handlers_signed_int64_max
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_INTEGER_OUT_OF_RANGE",
            "manifest integers must fit the signed 64-bit range",
            details={"literal": value[:80]},
        )
    return parsed


def _workflow_handlers_reject_float(value: str) -> object:
    raise WorkflowHandlerAuditError(
        "HANDLER_MANIFEST_FLOAT_FORBIDDEN",
        "manifest floating-point values are forbidden",
        details={"literal": value[:80]},
    )


def _workflow_handlers_reject_constant(value: str) -> object:
    raise WorkflowHandlerAuditError(
        "HANDLER_MANIFEST_NONFINITE_FORBIDDEN",
        "manifest NaN and infinity values are forbidden",
        details={"literal": value},
    )


def _workflow_handlers_validate_nfc_json(
    value: object, path: str = "$"
) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise WorkflowHandlerAuditError(
                "HANDLER_MANIFEST_UNICODE_INVALID",
                "manifest strings and keys must be valid Unicode",
                details={"path": path, "position": exc.start},
            ) from exc
        if unicodedata.normalize("NFC", value) != value:
            raise WorkflowHandlerAuditError(
                "HANDLER_MANIFEST_NOT_NFC",
                "manifest strings and keys must be NFC",
                details={"path": path},
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _workflow_handlers_validate_nfc_json(
                item, f"{path}/{index}"
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _workflow_handlers_validate_nfc_json(
                key, f"{path}/<key>"
            )
            _workflow_handlers_validate_nfc_json(
                item, f"{path}/{key}"
            )


def _workflow_handlers_strict_json(
    source: bytes, *, path: str
) -> object:
    if source.startswith(_workflow_handlers_utf8_bom):
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_BOM_FORBIDDEN",
            "handler manifests must not contain a UTF-8 BOM",
            details={"path": path},
        )
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_UTF8_INVALID",
            "handler manifests must be valid UTF-8",
            details={"path": path, "position": exc.start},
        ) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_workflow_handlers_strict_object,
            parse_float=_workflow_handlers_reject_float,
            parse_int=_workflow_handlers_parse_int,
            parse_constant=_workflow_handlers_reject_constant,
        )
    except _workflow_handlers_DuplicateObjectKey as exc:
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_DUPLICATE_KEY",
            "handler manifest object keys must be unique",
            details={"path": path, "key": exc.key},
        ) from exc
    except json.JSONDecodeError as exc:
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_JSON_INVALID",
            "handler manifest is malformed JSON",
            details={
                "path": path,
                "line": exc.lineno,
                "column": exc.colno,
            },
        ) from exc
    _workflow_handlers_validate_nfc_json(value)
    return value


def _workflow_handlers_require_object(
    value: object, *, path: str
) -> MutableMapping[str, object]:
    if not isinstance(value, dict):
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_TYPE_MISMATCH",
            "manifest value must be an object",
            details={"path": path},
        )
    return value


def _workflow_handlers_require_array(
    value: object, *, path: str
) -> list[object]:
    if not isinstance(value, list):
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_TYPE_MISMATCH",
            "manifest value must be an array",
            details={"path": path},
        )
    return value


def _workflow_handlers_require_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_TYPE_MISMATCH",
            "manifest value must be a non-empty string",
            details={"path": path},
        )
    return value


def _workflow_handlers_require_exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    path: str,
) -> None:
    observed = frozenset(value)
    if observed != expected:
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_FIELDS_INVALID",
            "manifest object fields do not match the versioned schema",
            details={
                "path": path,
                "missing": sorted(expected - observed),
                "unknown": sorted(observed - expected),
            },
        )


def _workflow_handlers_sorted_unique_strings(
    value: object,
    *,
    path: str,
    pattern: Optional[re.Pattern[str]] = None,
) -> Tuple[str, ...]:
    items = _workflow_handlers_require_array(value, path=path)
    strings: list[str] = []
    for index, item in enumerate(items):
        candidate = _workflow_handlers_require_string(
            item, path=f"{path}/{index}"
        )
        if pattern is not None and not pattern.fullmatch(candidate):
            raise WorkflowHandlerAuditError(
                "HANDLER_MANIFEST_VALUE_INVALID",
                "manifest string does not match its contract grammar",
                details={"path": f"{path}/{index}", "value": candidate},
            )
        strings.append(candidate)
    expected = sorted(set(strings), key=lambda item: item.encode("utf-8"))
    if strings != expected:
        raise WorkflowHandlerAuditError(
            "HANDLER_MANIFEST_ORDER_INVALID",
            "manifest arrays must be unique and sorted by UTF-8 bytes",
            details={"path": path},
        )
    return tuple(strings)


def _workflow_handlers_portable_path(value: str, *, path: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:", value)
        or any(
            character in value
            for character in _workflow_handlers_glob_characters
        )
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_PATH_INVALID",
            "implementation paths must be exact package-relative POSIX paths",
            details={"path": path, "value": value},
        )
    candidate = PurePosixPath(value)
    parts = value.split("/")
    if (
        candidate.as_posix() != value
        or any(
            part in {"", ".", ".."}
            or not _workflow_handlers_portable_segment_re.fullmatch(
                part
            )
            for part in parts
        )
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_PATH_INVALID",
            "implementation paths must not traverse, collide, or use globs",
            details={"path": path, "value": value},
        )
    return value


def _workflow_handlers_contained_regular_file(
    root: Path, relative: str
) -> Path:
    candidate = root.joinpath(*relative.split("/"))
    current = root
    for segment in relative.split("/")[:-1]:
        current = current / segment
        try:
            parent_metadata = current.lstat()
        except FileNotFoundError as exc:
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPLEMENTATION_FILE_MISSING",
                "declared package handler parent is missing",
                details={"path": relative},
            ) from exc
        if (
            stat.S_ISLNK(parent_metadata.st_mode)
            or not stat.S_ISDIR(parent_metadata.st_mode)
        ):
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPLEMENTATION_FILE_INVALID",
                "declared handler paths must not traverse links",
                details={"path": relative},
            )
    try:
        metadata = candidate.lstat()
    except FileNotFoundError as exc:
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_FILE_MISSING",
            "declared package handler file is missing",
            details={"path": relative},
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_FILE_INVALID",
            "declared handler files must be regular files, not links",
            details={"path": relative},
        )
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_PATH_ESCAPE",
            "declared handler file escapes the package root",
            details={"path": relative},
        )
    return candidate


def _workflow_handlers_canonical_payload(
    source: bytes, kind: str, *, path: str
) -> bytes:
    if kind == "B":
        return source
    if source.startswith(_workflow_handlers_utf8_bom):
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_BOM_FORBIDDEN",
            "text and JSON implementation files must not contain a BOM",
            details={"path": path},
        )
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_UTF8_INVALID",
            "text and JSON implementation files must be UTF-8",
            details={"path": path, "position": exc.start},
        ) from exc
    if kind == "T":
        if unicodedata.normalize("NFC", text) != text:
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPLEMENTATION_NOT_NFC",
                "text implementation files must contain NFC text",
                details={"path": path},
            )
        return (
            text.replace("\r\n", "\n")
            .replace("\r", "\n")
            .encode("utf-8")
        )
    parsed = _workflow_handlers_strict_json(source, path=path)
    return json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _workflow_handlers_u64(value: int) -> bytes:
    return struct.pack(">Q", value)


def _workflow_handlers_implementation_digest(
    handler_id: str,
    contract_id: str,
    files: Sequence[Tuple[ImplementationFileDeclaration, bytes]],
) -> str:
    handler = handler_id.encode("utf-8")
    contract = contract_id.encode("utf-8")
    framed = bytearray(HANDLER_IMPLEMENTATION_DOMAIN)
    framed.extend(_workflow_handlers_u64(len(handler)))
    framed.extend(handler)
    framed.extend(_workflow_handlers_u64(len(contract)))
    framed.extend(contract)
    ordered = sorted(
        files, key=lambda item: item[0].path.encode("utf-8")
    )
    framed.extend(_workflow_handlers_u64(len(ordered)))
    for declaration, payload in ordered:
        encoded_path = declaration.path.encode("utf-8")
        framed.extend(_workflow_handlers_u64(len(encoded_path)))
        framed.extend(encoded_path)
        framed.extend(declaration.kind.encode("ascii"))
        framed.extend(_workflow_handlers_u64(len(payload)))
        framed.extend(payload)
    return hashlib.sha256(bytes(framed)).hexdigest()


def _workflow_handlers_top_level_origins(
    trees: Mapping[str, ast.Module],
) -> Tuple[
    dict[str, list[Tuple[str, ast.AST]]],
    dict[str, Tuple[str, str]],
    dict[str, set[str]],
]:
    origins: dict[str, list[Tuple[str, ast.AST]]] = {}
    imports: dict[str, Tuple[str, str]] = {}
    file_imports: dict[str, set[str]] = {}

    class ModuleOrigins(ast.NodeVisitor):
        def __init__(self, path: str) -> None:
            self.path = path
            self.imported_roots: set[str] = set()

        def _origin(self, name: str, node: ast.AST) -> None:
            origins.setdefault(name, []).append((self.path, node))

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._origin(node.name, node)

        def visit_AsyncFunctionDef(
            self, node: ast.AsyncFunctionDef
        ) -> None:
            self._origin(node.name, node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._origin(node.name, node)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                bound = alias.asname or root
                imports[bound] = (self.path, alias.name)
                self._origin(bound, node)
                self.imported_roots.add(root)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = node.module or ""
            root = module.split(".", 1)[0] if module else ""
            for alias in node.names:
                bound = alias.asname or alias.name
                imports[bound] = (self.path, module)
                self._origin(bound, node)
            if root:
                self.imported_roots.add(root)

        def _assignment_targets(
            self, node: ast.AST, targets: Sequence[ast.AST]
        ) -> None:
            for target in targets:
                pending_targets = [target]
                while pending_targets:
                    nested = pending_targets.pop()
                    if isinstance(nested, ast.Name):
                        self._origin(nested.id, node)
                    elif isinstance(nested, (ast.Tuple, ast.List)):
                        pending_targets.extend(nested.elts)
                    elif isinstance(nested, ast.Starred):
                        pending_targets.append(nested.value)

        def visit_Assign(self, node: ast.Assign) -> None:
            self._assignment_targets(node, node.targets)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._assignment_targets(node, (node.target,))

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self._assignment_targets(node, (node.target,))
            self.visit(node.value)

    for path, tree in trees.items():
        visitor = ModuleOrigins(path)
        visitor.visit(tree)
        file_imports[path] = visitor.imported_roots
    return origins, imports, file_imports


class _workflow_handlers_ScopeLocals(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self.names.add(node.arg)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, _node: ast.Lambda) -> None:
        # Lambda parameters and assignment expressions are scoped to the
        # lambda and must not become locals of the enclosing function.
        return

    def visit_ListComp(self, _node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, _node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, _node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, _node: ast.GeneratorExp) -> None:
        return

    def visit_alias(self, node: ast.alias) -> None:
        self.names.add(node.asname or node.name.split(".", 1)[0])

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if isinstance(node.name, str):
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)


class _workflow_handlers_GlobalReferenceVisitor(ast.NodeVisitor):
    def __init__(self, inherited_locals: Sequence[set[str]] = ()) -> None:
        self._scopes = list(inherited_locals)
        self.references: set[str] = set()

    def _is_local(self, name: str) -> bool:
        return any(name in scope for scope in reversed(self._scopes))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and not self._is_local(node.id):
            if (
                node.id not in _workflow_handlers_builtin_names
                and node.id not in _workflow_handlers_type_only_globals
            ):
                self.references.add(node.id)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)

    def _visit_function(
        self,
        node: ast.AST,
        arguments: ast.arguments,
        body: Sequence[ast.stmt],
        *,
        body_scopes: Optional[Sequence[set[str]]] = None,
    ) -> None:
        for decorator in getattr(node, "decorator_list", ()):
            self.visit(decorator)
        for default in arguments.defaults:
            self.visit(default)
        for default in arguments.kw_defaults:
            if default is not None:
                self.visit(default)
        locals_visitor = _workflow_handlers_ScopeLocals()
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            locals_visitor.visit(argument)
        if arguments.vararg is not None:
            locals_visitor.visit(arguments.vararg)
        if arguments.kwarg is not None:
            locals_visitor.visit(arguments.kwarg)
        for statement in body:
            locals_visitor.visit(statement)
        previous_scopes = self._scopes
        if body_scopes is not None:
            self._scopes = list(body_scopes)
        self._scopes.append(locals_visitor.names)
        for statement in body:
            self.visit(statement)
        self._scopes.pop()
        self._scopes = previous_scopes

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, node.args, node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, node.args, node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        class_locals = _workflow_handlers_ScopeLocals()
        for statement in node.body:
            class_locals.visit(statement)
        outer_scopes = list(self._scopes)
        self._scopes.append(class_locals.names)
        for statement in node.body:
            if isinstance(statement, ast.FunctionDef):
                self._visit_function(
                    statement,
                    statement.args,
                    statement.body,
                    body_scopes=outer_scopes,
                )
            elif isinstance(statement, ast.AsyncFunctionDef):
                self._visit_function(
                    statement,
                    statement.args,
                    statement.body,
                    body_scopes=outer_scopes,
                )
            else:
                self.visit(statement)
        self._scopes.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        locals_visitor = _workflow_handlers_ScopeLocals()
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ):
            locals_visitor.visit(argument)
        if node.args.vararg is not None:
            locals_visitor.visit(node.args.vararg)
        if node.args.kwarg is not None:
            locals_visitor.visit(node.args.kwarg)
        self._scopes.append(locals_visitor.names)
        self.visit(node.body)
        self._scopes.pop()

    def _visit_comprehension(
        self,
        generators: Sequence[ast.comprehension],
        values: Sequence[ast.AST],
    ) -> None:
        comprehension_locals: set[str] = set()
        self._scopes.append(comprehension_locals)
        for generator in generators:
            self.visit(generator.iter)
            targets = _workflow_handlers_ScopeLocals()
            targets.visit(generator.target)
            comprehension_locals.update(targets.names)
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)
        self._scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(
            node.generators, (node.key, node.value)
        )

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))


def _workflow_handlers_global_references(node: ast.AST) -> set[str]:
    visitor = _workflow_handlers_GlobalReferenceVisitor()
    visitor.visit(node)
    return visitor.references


def _workflow_handlers_forbidden_operation(
    node: ast.AST,
) -> Optional[Tuple[str, int]]:
    for nested in ast.walk(node):
        if isinstance(nested, (ast.Global, ast.Nonlocal)):
            return (
                type(nested).__name__.lower(),
                getattr(nested, "lineno", 0),
            )
        if isinstance(nested, ast.Name):
            name = nested.id
            if (
                name in _workflow_handlers_forbidden_in_process_names
                or any(
                    name.startswith(prefix)
                    for prefix in (
                        _workflow_handlers_forbidden_in_process_prefixes
                    )
                )
            ):
                return name, getattr(nested, "lineno", 0)
        if isinstance(nested, ast.Attribute):
            attribute = nested.attr.lower()
            if (
                attribute
                in _workflow_handlers_forbidden_mutating_attributes
            ):
                return attribute, getattr(nested, "lineno", 0)
    return None


def _workflow_handlers_target_root_name(
    node: ast.AST,
) -> Optional[str]:
    current = node
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _workflow_handlers_target_names(
    node: ast.AST,
) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Starred):
        return _workflow_handlers_target_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            name
            for item in node.elts
            for name in _workflow_handlers_target_names(item)
        }
    return set()


def _workflow_handlers_expression_may_alias(
    node: Optional[ast.AST],
    aliases: set[str],
) -> bool:
    """Conservatively propagate references derived from immutable inputs.

    Python expressions can retain an input reference through subscripts,
    method returns, containers, conditionals, boolean fallbacks, unpacking,
    and comprehensions.  Treat any expression containing a known alias as
    alias-bearing. This intentionally favors rejecting a questionable
    in-process handler over accepting a mutation bypass; untrusted or complex
    logic belongs in an external executor.
    """

    if node is None:
        return False
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id in aliases
    if isinstance(
        node,
        (
            ast.Constant,
            ast.FormattedValue,
            ast.JoinedStr,
        ),
    ):
        return any(
            _workflow_handlers_expression_may_alias(child, aliases)
            for child in ast.iter_child_nodes(node)
        )
    if isinstance(node, ast.Lambda):
        return False
    return any(
        _workflow_handlers_expression_may_alias(child, aliases)
        for child in ast.iter_child_nodes(node)
    )


def _workflow_handlers_input_mutation(
    node: ast.AST,
) -> Optional[Tuple[str, int]]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    argument_names = {
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    }
    if node.args.vararg is not None:
        argument_names.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        argument_names.add(node.args.kwarg.arg)
    aliases = set(argument_names)
    nested_nodes = tuple(ast.walk(node))
    changed = True
    while changed:
        changed = False
        for nested in nested_nodes:
            value: Optional[ast.AST] = None
            targets: Sequence[ast.AST] = ()
            if isinstance(nested, ast.Assign):
                value = nested.value
                targets = nested.targets
            elif isinstance(nested, ast.AnnAssign):
                value = nested.value
                targets = (nested.target,)
            elif isinstance(nested, ast.NamedExpr):
                value = nested.value
                targets = (nested.target,)
            elif isinstance(nested, (ast.For, ast.AsyncFor)):
                value = nested.iter
                targets = (nested.target,)
            elif isinstance(nested, ast.comprehension):
                value = nested.iter
                targets = (nested.target,)
            elif isinstance(nested, ast.With):
                for item in nested.items:
                    if (
                        item.optional_vars is not None
                        and _workflow_handlers_expression_may_alias(
                            item.context_expr, aliases
                        )
                    ):
                        for name in _workflow_handlers_target_names(
                            item.optional_vars
                        ):
                            if name not in aliases:
                                aliases.add(name)
                                changed = True
                continue
            if not _workflow_handlers_expression_may_alias(
                value, aliases
            ):
                continue
            for target in targets:
                for name in _workflow_handlers_target_names(target):
                    if name not in aliases:
                        aliases.add(name)
                        changed = True
    for nested in nested_nodes:
        targets: Sequence[ast.AST] = ()
        if isinstance(nested, (ast.Assign, ast.Delete)):
            targets = nested.targets
        elif isinstance(nested, (ast.AnnAssign, ast.AugAssign)):
            targets = (nested.target,)
        for target in targets:
            if (
                isinstance(nested, ast.AugAssign)
                and isinstance(target, ast.Name)
                and target.id in aliases
            ):
                return target.id, getattr(nested, "lineno", 0)
            if isinstance(target, (ast.Attribute, ast.Subscript)):
                root = _workflow_handlers_target_root_name(target)
                if root in aliases:
                    return root or "argument", getattr(
                        nested, "lineno", 0
                    )
        if (
            isinstance(nested, ast.Call)
            and isinstance(nested.func, ast.Attribute)
            and nested.func.attr
            in _workflow_handlers_mutating_input_methods
        ):
            root = _workflow_handlers_target_root_name(
                nested.func.value
            )
            if root in aliases:
                return root or "argument", getattr(
                    nested, "lineno", 0
                )
    return None


class _workflow_handlers_ModuleExecutionVisitor(ast.NodeVisitor):
    """Inspect expressions that execute while a pure fragment is loaded."""

    def __init__(self, forbidden_import_names: Sequence[str]) -> None:
        self.violation: Optional[Tuple[str, int]] = None
        self._forbidden_import_names = frozenset(
            forbidden_import_names
        )

    def _record(self, name: str, node: ast.AST) -> None:
        if self.violation is None:
            self.violation = (name, getattr(node, "lineno", 0))

    def visit_Call(self, node: ast.Call) -> None:
        target = node.func
        if isinstance(target, ast.Name):
            name = target.id
            if (
                name in _workflow_handlers_forbidden_in_process_names
                or any(
                    name.startswith(prefix)
                    for prefix in (
                        _workflow_handlers_forbidden_in_process_prefixes
                    )
                )
            ):
                self._record(name, node)
        elif (
            isinstance(target, ast.Attribute)
            and target.attr.lower()
            in _workflow_handlers_forbidden_mutating_attributes
        ):
            self._record(target.attr.lower(), node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        if (
            node.id in self._forbidden_import_names
            or node.id in _workflow_handlers_forbidden_in_process_names
            or any(
                node.id.startswith(prefix)
                for prefix in (
                    _workflow_handlers_forbidden_in_process_prefixes
                )
            )
        ):
            self._record(node.id, node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            node.attr.lower()
            in _workflow_handlers_forbidden_mutating_attributes
        ):
            self._record(node.attr.lower(), node)
        self.generic_visit(node)

    def _visit_function_header(
        self,
        node: ast.AST,
        arguments: ast.arguments,
    ) -> None:
        for decorator in getattr(node, "decorator_list", ()):
            self.visit(decorator)
        for default in arguments.defaults:
            self.visit(default)
        for default in arguments.kw_defaults:
            if default is not None:
                self.visit(default)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_header(node, node.args)

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> None:
        self._visit_function_header(node, node.args)

    def visit_Lambda(self, _node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for statement in node.body:
            self.visit(statement)


def _workflow_handlers_audit_module_execution(
    spec: HandlerRegistrationSpec,
    trees: Mapping[str, ast.Module],
) -> None:
    if spec.audit_profile != "pure-v1":
        return
    origins, imports, _file_imports = (
        _workflow_handlers_top_level_origins(trees)
    )
    handler_paths = {
        path
        for symbol in spec.symbols.values()
        for path, _node in origins.get(symbol, ())
    }
    paths_to_audit = (
        handler_paths if spec.semantic_roots else set(trees)
    )
    forbidden_import_names = {
        name
        for name, (_path, module) in imports.items()
        if module.split(".", 1)[0]
        not in _workflow_handlers_pure_allowed_imports
        and module != "__future__"
    }
    for path in sorted(paths_to_audit):
        tree = trees[path]
        visitor = _workflow_handlers_ModuleExecutionVisitor(
            forbidden_import_names
        )
        visitor.visit(tree)
        if visitor.violation is None:
            continue
        name, line = visitor.violation
        raise WorkflowHandlerAuditError(
            "HANDLER_CAPABILITY_REFERENCE_FORBIDDEN",
            "pure handler source executes a forbidden load-time operation",
            details={
                "handler_id": spec.handler_id,
                "path": path,
                "line": line,
                "name": name,
            },
        )


def _workflow_handlers_require_source_binding(
    spec: HandlerRegistrationSpec,
    *,
    role: str,
    symbol: str,
    implementation: object,
    namespace: Mapping[str, object],
    package_root: Path,
    declaration: Tuple[str, ast.AST],
) -> None:
    path, node = declaration
    code = getattr(implementation, "__code__", None)
    filename = getattr(code, "co_filename", None)
    first_line = getattr(code, "co_firstlineno", None)
    try:
        observed_path = (
            Path(filename).resolve() if isinstance(filename, str) else None
        )
    except (OSError, RuntimeError):
        observed_path = None
    expected_path = (package_root / path).resolve()
    expected_code: Optional[CodeType] = None
    try:
        compiled = compile(
            expected_path.read_bytes(),
            str(expected_path),
            "exec",
        )
    except (OSError, SyntaxError, UnicodeError):
        compiled = None
    if compiled is not None:
        candidates = [
            value
            for value in compiled.co_consts
            if isinstance(value, CodeType)
            and value.co_name == symbol
            and value.co_firstlineno == getattr(node, "lineno", None)
        ]
        if len(candidates) == 1:
            expected_code = candidates[0]
    if (
        observed_path != expected_path
        or first_line != getattr(node, "lineno", None)
        or not isinstance(code, CodeType)
        or getattr(implementation, "__globals__", None) is not namespace
        or expected_code is None
        or _workflow_handlers_code_fingerprint(code)
        != _workflow_handlers_code_fingerprint(expected_code)
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_SYMBOL_SOURCE_MISMATCH",
            "shared-runtime binding does not match its audited source definition",
            details={
                "handler_id": spec.handler_id,
                "role": role,
                "symbol": symbol,
                "path": path,
            },
        )
    disallowed_shape_flags = 0x20 | 0x80 | 0x200
    if code.co_flags & disallowed_shape_flags:
        raise WorkflowHandlerAuditError(
            "HANDLER_SYMBOL_CONTRACT_INVALID",
            "handler bindings must be synchronous non-generator functions",
            details={
                "handler_id": spec.handler_id,
                "role": role,
                "symbol": symbol,
            },
        )
    expected_arguments: Optional[int] = None
    if spec.audit_profile == "pure-v1":
        expected_arguments = 2
    elif spec.registry_kind == "commands":
        expected_arguments = 3 if role == "parser_factory" else 1
    elif spec.registry_kind == "gates":
        expected_arguments = 1
    if expected_arguments is not None and (
        code.co_argcount != expected_arguments
        or code.co_kwonlyargcount != 0
        or code.co_flags & (0x04 | 0x08)
        or getattr(implementation, "__defaults__", None)
        or getattr(implementation, "__kwdefaults__", None)
        or getattr(implementation, "__closure__", None)
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_SYMBOL_CONTRACT_INVALID",
            "handler binding does not match its typed invocation contract",
            details={
                "handler_id": spec.handler_id,
                "role": role,
                "symbol": symbol,
                "expected_arguments": expected_arguments,
            },
        )


def _workflow_handlers_code_fingerprint(code: CodeType) -> tuple[object, ...]:
    constants = tuple(
        _workflow_handlers_code_fingerprint(value)
        if isinstance(value, CodeType)
        else value
        for value in code.co_consts
    )
    return (
        code.co_argcount,
        getattr(code, "co_posonlyargcount", 0),
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code,
        constants,
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
    )


def _workflow_handlers_audit_symbols(
    spec: HandlerRegistrationSpec,
    *,
    namespace: Mapping[str, object],
    trees: Mapping[str, ast.Module],
    package_root: Path,
) -> None:
    origins, imports, _file_imports = (
        _workflow_handlers_top_level_origins(trees)
    )
    loader_tree = ast.parse(
        (package_root / "scripts/dev_flow.py").read_bytes(),
        filename="scripts/dev_flow.py",
    )
    part_assignment = next(
        (
            node
            for node in loader_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_DEV_FLOW_PART_NAMES"
                for target in node.targets
            )
        ),
        None,
    )
    part_names = (
        ast.literal_eval(part_assignment.value)
        if isinstance(part_assignment, ast.Assign)
        else ()
    )
    runtime_source_order = {
        f"scripts/dev_flow_parts/{name}": index
        for index, name in enumerate(part_names)
    }
    binding_nodes: list[Tuple[str, ast.AST, str, bool]] = []
    for role, symbol in spec.symbols.items():
        implementation = namespace.get(symbol)
        if not callable(implementation):
            raise WorkflowHandlerAuditError(
                "HANDLER_SYMBOL_MISSING",
                "shared-runtime handler symbol is missing or not callable",
                details={
                    "handler_id": spec.handler_id,
                    "role": role,
                    "symbol": symbol,
                },
            )
        declarations = [
            item
            for item in origins.get(symbol, ())
            if isinstance(item[1], (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if len(declarations) != 1:
            raise WorkflowHandlerAuditError(
                "HANDLER_SYMBOL_SOURCE_INVALID",
                "handler symbol must have exactly one package function definition",
                details={
                    "handler_id": spec.handler_id,
                    "role": role,
                    "symbol": symbol,
                    "definition_count": len(declarations),
                },
            )
        _workflow_handlers_require_source_binding(
            spec,
            role=role,
            symbol=symbol,
            implementation=implementation,
            namespace=namespace,
            package_root=package_root,
            declaration=declarations[0],
        )
        binding_nodes.append(
            (declarations[0][0], declarations[0][1], symbol, False)
        )
    for symbol in spec.semantic_roots:
        implementation = namespace.get(symbol)
        if not callable(implementation):
            raise WorkflowHandlerAuditError(
                "HANDLER_SEMANTIC_ROOT_MISSING",
                "declared semantic root is missing or not callable",
                details={
                    "handler_id": spec.handler_id,
                    "symbol": symbol,
                },
            )
        declarations = [
            item
            for item in origins.get(symbol, ())
            if isinstance(item[1], (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if len(declarations) != 1:
            raise WorkflowHandlerAuditError(
                "HANDLER_SEMANTIC_ROOT_SOURCE_INVALID",
                "semantic root must have one exact package function definition",
                details={
                    "handler_id": spec.handler_id,
                    "symbol": symbol,
                    "definition_count": len(declarations),
                },
            )
        implementation_code = getattr(implementation, "__code__", None)
        if (
            not isinstance(implementation_code, CodeType)
            or getattr(implementation, "__globals__", None) is not namespace
            or Path(implementation_code.co_filename).resolve()
            != (package_root / declarations[0][0]).resolve()
            or implementation_code.co_firstlineno
            != getattr(declarations[0][1], "lineno", None)
        ):
            raise WorkflowHandlerAuditError(
                "HANDLER_SEMANTIC_ROOT_SOURCE_MISMATCH",
                "semantic root binding does not match its declared source",
                details={
                    "handler_id": spec.handler_id,
                    "symbol": symbol,
                    "path": declarations[0][0],
                },
            )
        binding_nodes.append(
            (declarations[0][0], declarations[0][1], symbol, True)
        )

    _workflow_handlers_audit_module_execution(spec, trees)
    visited: set[Tuple[str, bool]] = set()
    boundary_globals: set[str] = set()
    used_imports: set[str] = set()
    reachable_paths: set[str] = set()
    pending = list(binding_nodes)
    while pending:
        path, node, symbol, trusted_kernel = pending.pop()
        visit_key = (symbol, trusted_kernel)
        if visit_key in visited:
            continue
        visited.add(visit_key)
        reachable_paths.add(path)
        forbidden = _workflow_handlers_forbidden_operation(node)
        if (
            not trusted_kernel
            and spec.registry_kind in {"guards", "reducers"}
            and forbidden
        ):
            name, line = forbidden
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_REFERENCE_FORBIDDEN",
                "guard or reducer statically references a forbidden operation",
                details={
                    "handler_id": spec.handler_id,
                    "path": path,
                    "line": line,
                    "name": name,
                },
            )
        mutation = _workflow_handlers_input_mutation(node)
        if (
            not trusted_kernel
            and spec.registry_kind in {"guards", "reducers"}
            and mutation
        ):
            name, line = mutation
            raise WorkflowHandlerAuditError(
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
                "guard or reducer mutates an immutable input argument",
                details={
                    "handler_id": spec.handler_id,
                    "path": path,
                    "line": line,
                    "argument": name,
                },
            )
        references = _workflow_handlers_global_references(node)
        for reference in references:
            if (
                not trusted_kernel
                and spec.audit_profile == "legacy-controller-v1"
                and reference in spec.allowed_globals
            ):
                boundary_globals.add(reference)
                continue
            imported = imports.get(reference)
            if imported is not None:
                reachable_paths.add(imported[0])
                if not trusted_kernel:
                    used_imports.add(
                        imported[1].split(".", 1)[0]
                    )
                continue
            declarations = origins.get(reference, ())
            executable_declarations = [
                item
                for item in declarations
                if isinstance(
                    item[1],
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                        ast.ClassDef,
                        ast.Assign,
                        ast.AnnAssign,
                    ),
                )
            ]
            if len(executable_declarations) == 1:
                declaration_path, declaration_node = (
                    executable_declarations[0]
                )
                boundary = (
                    not trusted_kernel
                    and reference in spec.allowed_globals
                )
                if boundary:
                    boundary_globals.add(reference)
                pending.append(
                    (
                        declaration_path,
                        declaration_node,
                        reference,
                        trusted_kernel or boundary,
                    )
                )
                continue
            if len(executable_declarations) > 1:
                if trusted_kernel:
                    ordered_declarations = sorted(
                        executable_declarations,
                        key=lambda item: runtime_source_order.get(
                            item[0], -1
                        ),
                    )
                    declaration_path, declaration_node = (
                        ordered_declarations[-1]
                    )
                    if runtime_source_order.get(declaration_path, -1) >= 0:
                        pending.append(
                            (
                                declaration_path,
                                declaration_node,
                                reference,
                                True,
                            )
                        )
                        continue
                raise WorkflowHandlerAuditError(
                    "HANDLER_GLOBAL_SOURCE_AMBIGUOUS",
                    "handler global has multiple package definitions",
                    details={
                        "handler_id": spec.handler_id,
                        "global": reference,
                    },
                )
            if (
                not trusted_kernel
                and reference in spec.allowed_globals
            ):
                boundary_globals.add(reference)
                continue
            if (
                trusted_kernel
                and reference
                in _workflow_handlers_legacy_kernel_globals
            ):
                continue
            raise WorkflowHandlerAuditError(
                "HANDLER_GLOBAL_UNDECLARED",
                "handler references a global outside its exact implementation set",
                details={
                    "handler_id": spec.handler_id,
                    "global": reference,
                    "source_path": path,
                    "source_symbol": symbol,
                },
            )

    declared_paths = set(trees)
    if reachable_paths != declared_paths:
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_SET_MISMATCH",
            "implementation files must exactly match the audited executable closure",
            details={
                "handler_id": spec.handler_id,
                "missing": sorted(reachable_paths - declared_paths),
                "unused": sorted(declared_paths - reachable_paths),
            },
        )
    declared_globals = set(spec.allowed_globals)
    if boundary_globals != declared_globals:
        raise WorkflowHandlerAuditError(
            "HANDLER_GLOBAL_DECLARATION_MISMATCH",
            "handler global declarations must exactly match audited boundaries",
            details={
                "handler_id": spec.handler_id,
                "missing": sorted(boundary_globals - declared_globals),
                "unused": sorted(declared_globals - boundary_globals),
            },
        )
    if spec.audit_profile == "pure-v1" and declared_globals:
        raise WorkflowHandlerAuditError(
            "HANDLER_GLOBAL_BOUNDARY_FORBIDDEN",
            "pure handlers may not receive arbitrary global capabilities",
            details={
                "handler_id": spec.handler_id,
                "globals": sorted(declared_globals),
            },
        )
    allowed_kernel_globals = (
        _workflow_handlers_legacy_kernel_globals
        if spec.audit_profile == "legacy-controller-v1"
        else _workflow_handlers_legacy_read_only_kernel_globals
        if spec.audit_profile == "legacy-read-only-wrapper-v1"
        else frozenset()
    )
    if (
        spec.audit_profile
        in {"legacy-controller-v1", "legacy-read-only-wrapper-v1"}
        and declared_globals - allowed_kernel_globals
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_GLOBAL_BOUNDARY_FORBIDDEN",
            "legacy global boundaries must be versioned kernel capabilities",
            details={
                "handler_id": spec.handler_id,
                "globals": sorted(
                    declared_globals - allowed_kernel_globals
                ),
            },
        )
    declared_imports = set(spec.allowed_imports)
    if used_imports != declared_imports:
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPORT_DECLARATION_MISMATCH",
            "handler import declarations must exactly match audited imports",
            details={
                "handler_id": spec.handler_id,
                "missing": sorted(used_imports - declared_imports),
                "unused": sorted(declared_imports - used_imports),
            },
        )
    if spec.audit_profile == "legacy-controller-v1":
        forbidden_imports = (
            used_imports
            - _workflow_handlers_legacy_runtime_allowed_imports
        )
        if forbidden_imports:
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPORT_FORBIDDEN",
                "legacy handler imports a module outside its runtime policy",
                details={
                    "handler_id": spec.handler_id,
                    "imports": sorted(forbidden_imports),
                },
            )
    if spec.registry_kind in {"guards", "reducers"}:
        forbidden_imports = (
            used_imports
            & _workflow_handlers_forbidden_in_process_imports
        )
        if spec.audit_profile == "pure-v1":
            forbidden_imports |= (
                used_imports - _workflow_handlers_pure_allowed_imports
            )
        if forbidden_imports:
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPORT_FORBIDDEN",
                "in-process guard or reducer imports a forbidden capability",
                details={
                    "handler_id": spec.handler_id,
                    "imports": sorted(forbidden_imports),
                },
            )


def _workflow_handlers_parse_file_sets(
    value: object, *, manifest_path: str
) -> dict[str, ImplementationFileSet]:
    raw_sets = _workflow_handlers_require_object(
        value, path=f"{manifest_path}/implementation_file_sets"
    )
    result: dict[str, ImplementationFileSet] = {}
    for name, raw_file_set in raw_sets.items():
        if not _workflow_handlers_file_set_re.fullmatch(name):
            raise WorkflowHandlerAuditError(
                "HANDLER_FILE_SET_NAME_INVALID",
                "implementation file-set name is not portable",
                details={"manifest": manifest_path, "name": name},
            )
        semantic_roots: Tuple[str, ...] = ()
        if isinstance(raw_file_set, Mapping):
            file_set_path = (
                f"{manifest_path}/implementation_file_sets/{name}"
            )
            file_set = _workflow_handlers_require_object(
                raw_file_set, path=file_set_path
            )
            _workflow_handlers_require_exact_fields(
                file_set,
                frozenset({"files", "semantic_roots"}),
                path=file_set_path,
            )
            raw_files = file_set["files"]
            semantic_roots = _workflow_handlers_sorted_unique_strings(
                file_set["semantic_roots"],
                path=f"{file_set_path}/semantic_roots",
                pattern=_workflow_handlers_symbol_re,
            )
            if not semantic_roots:
                raise WorkflowHandlerAuditError(
                    "HANDLER_SEMANTIC_ROOTS_EMPTY",
                    "structured implementation file sets require semantic roots",
                    details={
                        "manifest": manifest_path,
                        "file_set": name,
                    },
                )
        else:
            raw_files = raw_file_set
        declarations: list[ImplementationFileDeclaration] = []
        for index, raw_file in enumerate(
            _workflow_handlers_require_array(
                raw_files,
                path=(
                    f"{manifest_path}/implementation_file_sets/{name}"
                ),
            )
        ):
            item_path = (
                f"{manifest_path}/implementation_file_sets/{name}/{index}"
            )
            item = _workflow_handlers_require_object(
                raw_file, path=item_path
            )
            _workflow_handlers_require_exact_fields(
                item,
                _workflow_handlers_implementation_file_fields,
                path=item_path,
            )
            relative = _workflow_handlers_portable_path(
                _workflow_handlers_require_string(
                    item["path"], path=f"{item_path}/path"
                ),
                path=f"{item_path}/path",
            )
            kind = _workflow_handlers_require_string(
                item["kind"], path=f"{item_path}/kind"
            )
            if kind not in _workflow_handlers_file_kinds:
                raise WorkflowHandlerAuditError(
                    "HANDLER_IMPLEMENTATION_KIND_INVALID",
                    "implementation file kind must be J, T, or B",
                    details={"path": item_path, "kind": kind},
                )
            if relative.endswith(".py") and kind != "T":
                raise WorkflowHandlerAuditError(
                    "HANDLER_IMPLEMENTATION_KIND_INVALID",
                    "Python implementation files must be explicitly text",
                    details={"path": relative, "kind": kind},
                )
            declarations.append(
                ImplementationFileDeclaration(relative, kind)
            )
        if not declarations:
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPLEMENTATION_SET_EMPTY",
                "declared implementation file sets must be non-empty",
                details={"manifest": manifest_path, "file_set": name},
            )
        expected = sorted(
            {(item.path, item.kind) for item in declarations},
            key=lambda item: item[0].encode("utf-8"),
        )
        observed = [(item.path, item.kind) for item in declarations]
        if observed != expected or len(observed) != len({item[0] for item in observed}):
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPLEMENTATION_SET_INVALID",
                "implementation files must be unique and sorted by UTF-8 path",
                details={"manifest": manifest_path, "file_set": name},
            )
        portable: dict[str, str] = {}
        for declaration in declarations:
            identity = unicodedata.normalize(
                "NFC", declaration.path
            ).casefold()
            previous = portable.get(identity)
            if previous is not None:
                raise WorkflowHandlerAuditError(
                    "HANDLER_IMPLEMENTATION_PATH_COLLISION",
                    "implementation paths collide under portable identity",
                    details={
                        "manifest": manifest_path,
                        "file_set": name,
                        "first": previous,
                        "second": declaration.path,
                    },
                )
            portable[identity] = declaration.path
        result[name] = ImplementationFileSet(
            files=tuple(declarations),
            semantic_roots=semantic_roots,
        )
    return result


def _workflow_handlers_parse_symbols(
    value: object, *, registry_kind: str, path: str
) -> Mapping[str, str]:
    symbols = _workflow_handlers_require_object(value, path=path)
    expected = frozenset(
        _workflow_handlers_symbol_roles[registry_kind]
    )
    _workflow_handlers_require_exact_fields(
        symbols, expected, path=path
    )
    parsed: dict[str, str] = {}
    for role in sorted(expected):
        symbol = _workflow_handlers_require_string(
            symbols[role], path=f"{path}/{role}"
        )
        if not _workflow_handlers_symbol_re.fullmatch(symbol):
            raise WorkflowHandlerAuditError(
                "HANDLER_SYMBOL_INVALID",
                "bindings must name one shared-runtime global, not a module path",
                details={"path": f"{path}/{role}", "symbol": symbol},
            )
        parsed[role] = symbol
    return MappingProxyType(parsed)


def _workflow_handlers_parse_audit(
    value: object, *, registry_kind: str, path: str
) -> Tuple[str, Tuple[str, ...], Tuple[str, ...]]:
    audit = _workflow_handlers_require_object(value, path=path)
    _workflow_handlers_require_exact_fields(
        audit, _workflow_handlers_audit_fields, path=path
    )
    profile = _workflow_handlers_require_string(
        audit["profile"], path=f"{path}/profile"
    )
    if (
        profile
        not in _workflow_handlers_audit_profiles_by_kind[registry_kind]
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_AUDIT_PROFILE_INVALID",
            "audit profile is not permitted for this registry kind",
            details={
                "path": f"{path}/profile",
                "profile": profile,
                "registry": registry_kind,
            },
        )
    globals_value = _workflow_handlers_sorted_unique_strings(
        audit["allowed_globals"],
        path=f"{path}/allowed_globals",
        pattern=_workflow_handlers_symbol_re,
    )
    imports_value = _workflow_handlers_sorted_unique_strings(
        audit["allowed_imports"],
        path=f"{path}/allowed_imports",
        pattern=_workflow_handlers_capability_re,
    )
    return profile, globals_value, imports_value


def _workflow_handlers_parse_entry(
    raw: object,
    *,
    registry_kind: str,
    index: int,
    manifest_path: str,
    file_sets: Mapping[
        str, ImplementationFileSet
    ],
    package_root: Path,
    namespace: Mapping[str, object],
    schema_refs: frozenset[str],
    source_cache: MutableMapping[str, bytes],
    payload_cache: MutableMapping[Tuple[str, str], bytes],
    tree_cache: MutableMapping[str, ast.Module],
) -> HandlerRegistrationSpec:
    entry_path = f"{manifest_path}/entries/{index}"
    entry = _workflow_handlers_require_object(raw, path=entry_path)
    expected_fields = (
        _workflow_handlers_common_entry_fields
        | _workflow_handlers_kind_entry_fields[registry_kind]
    )
    _workflow_handlers_require_exact_fields(
        entry, expected_fields, path=entry_path
    )

    handler_id = _workflow_handlers_require_string(
        entry["id"], path=f"{entry_path}/id"
    )
    match = _workflow_handlers_handler_id_re.fullmatch(handler_id)
    if match is None:
        raise WorkflowHandlerAuditError(
            "HANDLER_ID_INVALID",
            "handler IDs must contain one stable /vN contract version",
            details={"path": f"{entry_path}/id", "id": handler_id},
        )
    # The full versioned ID is the registry identifier. ``version`` remains a
    # separate, explicit contract key and must agree with the ID suffix.
    identifier = handler_id
    contract_version = match.group("version")
    contract_id = _workflow_handlers_require_string(
        entry["contract_id"], path=f"{entry_path}/contract_id"
    )
    if (
        not _workflow_handlers_contract_id_re.fullmatch(contract_id)
        or contract_id
        != _workflow_handlers_contract_ids[registry_kind]
    ):
        raise WorkflowHandlerAuditError(
            "HANDLER_CONTRACT_ID_INVALID",
            "handler contract ID does not match its registry kind",
            details={
                "handler_id": handler_id,
                "contract_id": contract_id,
                "expected": _workflow_handlers_contract_ids[
                    registry_kind
                ],
            },
        )
    authority = _workflow_handlers_sorted_unique_strings(
        entry["authority"], path=f"{entry_path}/authority"
    )
    if not authority:
        raise WorkflowHandlerAuditError(
            "HANDLER_AUTHORITY_MISSING",
            "every handler must declare non-empty authority",
            details={"handler_id": handler_id},
        )
    capabilities = _workflow_handlers_sorted_unique_strings(
        entry["capabilities"],
        path=f"{entry_path}/capabilities",
        pattern=_workflow_handlers_capability_re,
    )
    if registry_kind == "guards":
        if authority != ("read-only",):
            raise WorkflowHandlerAuditError(
                "HANDLER_AUTHORITY_FORBIDDEN",
                "in-process guards may declare only read-only authority",
                details={"handler_id": handler_id},
            )
        forbidden = (
            set(capabilities)
            - _workflow_handlers_allowed_guard_capabilities
        )
        if forbidden:
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_FORBIDDEN",
                "guard requests a non-read-only kernel capability",
                details={
                    "handler_id": handler_id,
                    "capabilities": sorted(forbidden),
                },
            )
    if registry_kind == "reducers":
        if authority != ("state-delta",) or capabilities:
            raise WorkflowHandlerAuditError(
                "HANDLER_CAPABILITY_FORBIDDEN",
                "reducers may declare state-delta authority and no capabilities",
                details={
                    "handler_id": handler_id,
                    "authority": list(authority),
                    "capabilities": list(capabilities),
                },
            )
    if registry_kind == "gates" and authority != ("approval-build",):
        raise WorkflowHandlerAuditError(
            "HANDLER_AUTHORITY_FORBIDDEN",
            "gate builders may declare only approval-build authority",
            details={"handler_id": handler_id},
        )

    input_schema_ref = _workflow_handlers_require_string(
        entry["input_schema_ref"],
        path=f"{entry_path}/input_schema_ref",
    )
    output_schema_ref = _workflow_handlers_require_string(
        entry["output_schema_ref"],
        path=f"{entry_path}/output_schema_ref",
    )
    for role, reference in (
        ("input", input_schema_ref),
        ("output", output_schema_ref),
    ):
        if (
            not _workflow_handlers_schema_ref_re.fullmatch(reference)
            or reference not in schema_refs
        ):
            raise WorkflowHandlerAuditError(
                "HANDLER_SCHEMA_REFERENCE_UNKNOWN",
                "handler typed schema reference is not package-declared",
                details={
                    "handler_id": handler_id,
                    "role": role,
                    "schema_ref": reference,
                },
            )
    file_set_name = _workflow_handlers_require_string(
        entry["implementation_file_set"],
        path=f"{entry_path}/implementation_file_set",
    )
    try:
        implementation_file_set = file_sets[file_set_name]
    except KeyError as exc:
        raise WorkflowHandlerAuditError(
            "HANDLER_IMPLEMENTATION_SET_UNKNOWN",
            "handler references an unknown exact implementation file set",
            details={
                "handler_id": handler_id,
                "file_set": file_set_name,
            },
        ) from exc
    implementation_files = implementation_file_set.files
    symbols = _workflow_handlers_parse_symbols(
        entry["symbols"],
        registry_kind=registry_kind,
        path=f"{entry_path}/symbols",
    )
    audit_profile, allowed_globals, allowed_imports = (
        _workflow_handlers_parse_audit(
        entry["audit"],
        registry_kind=registry_kind,
        path=f"{entry_path}/audit",
        )
    )

    files_with_payload: list[
        Tuple[ImplementationFileDeclaration, bytes]
    ] = []
    trees: dict[str, ast.Module] = {}
    for declaration in implementation_files:
        if declaration.path not in source_cache:
            source_cache[declaration.path] = (
                _workflow_handlers_contained_regular_file(
                    package_root, declaration.path
                ).read_bytes()
            )
        cache_key = (declaration.path, declaration.kind)
        if cache_key not in payload_cache:
            payload_cache[cache_key] = (
                _workflow_handlers_canonical_payload(
                source_cache[declaration.path],
                declaration.kind,
                path=declaration.path,
                )
            )
        payload = payload_cache[cache_key]
        files_with_payload.append((declaration, payload))
        if declaration.path.endswith(".py"):
            if declaration.path not in tree_cache:
                try:
                    tree_cache[declaration.path] = ast.parse(
                        payload.decode("utf-8"),
                        filename=declaration.path,
                    )
                except SyntaxError as exc:
                    raise WorkflowHandlerAuditError(
                        "HANDLER_IMPLEMENTATION_SYNTAX_INVALID",
                        "Python handler implementation does not parse",
                        details={
                            "path": declaration.path,
                            "line": exc.lineno,
                            "column": exc.offset,
                        },
                    ) from exc
            trees[declaration.path] = tree_cache[declaration.path]

    command: Optional[str] = None
    action_id: Optional[str] = None
    parser_order: Optional[int] = None
    effect_classification: Optional[str] = None
    if registry_kind == "commands":
        command = _workflow_handlers_require_string(
            entry["command"], path=f"{entry_path}/command"
        )
        if any(character.isspace() for character in command):
            raise WorkflowHandlerAuditError(
                "HANDLER_COMMAND_INVALID",
                "command spelling must be one exact token",
                details={"handler_id": handler_id, "command": command},
            )
        action_id = _workflow_handlers_require_string(
            entry["action_id"], path=f"{entry_path}/action_id"
        )
        if not _workflow_handlers_capability_re.fullmatch(action_id):
            raise WorkflowHandlerAuditError(
                "HANDLER_ACTION_ID_INVALID",
                "command action ID is not portable",
                details={"handler_id": handler_id, "action_id": action_id},
            )
        parser_order = entry["parser_order"]
        if (
            isinstance(parser_order, bool)
            or not isinstance(parser_order, int)
            or parser_order < 0
        ):
            raise WorkflowHandlerAuditError(
                "HANDLER_PARSER_ORDER_INVALID",
                "command parser order must be a non-negative integer",
                details={
                    "handler_id": handler_id,
                    "parser_order": parser_order,
                },
            )
    elif registry_kind == "executors":
        effect_classification = _workflow_handlers_require_string(
            entry["effect_classification"],
            path=f"{entry_path}/effect_classification",
        )
        if (
            effect_classification
            not in _workflow_handlers_effect_classifications
        ):
            raise WorkflowHandlerAuditError(
                "HANDLER_EFFECT_CLASSIFICATION_INVALID",
                "executor effect classification is unsupported",
                details={
                    "handler_id": handler_id,
                    "effect_classification": effect_classification,
                },
            )

    spec = HandlerRegistrationSpec(
        registry_kind=registry_kind,
        handler_id=handler_id,
        identifier=identifier,
        contract_version=contract_version,
        contract_id=contract_id,
        authority=authority,
        capabilities=capabilities,
        input_schema_ref=input_schema_ref,
        output_schema_ref=output_schema_ref,
        implementation_files=implementation_files,
        implementation_sha256=_workflow_handlers_implementation_digest(
            handler_id, contract_id, files_with_payload
        ),
        symbols=symbols,
        semantic_roots=implementation_file_set.semantic_roots,
        audit_profile=audit_profile,
        allowed_globals=allowed_globals,
        allowed_imports=allowed_imports,
        command=command,
        action_id=action_id,
        parser_order=parser_order,
        effect_classification=effect_classification,
    )
    _workflow_handlers_audit_symbols(
        spec,
        namespace=namespace,
        trees=trees,
        package_root=package_root,
    )
    return spec


def _workflow_handlers_default_package_root() -> Path:
    runtime_file = Path(__file__).resolve()
    if runtime_file.name == "dev_flow.py":
        return runtime_file.parent.parent
    return runtime_file.parents[2]


def load_package_handler_manifests(
    *,
    package_root: Optional[os.PathLike[str]] = None,
    namespace: Optional[Mapping[str, object]] = None,
    schema_registry: Optional[Mapping[str, object]] = None,
) -> Tuple[HandlerRegistrationManifest, ...]:
    """Load and audit exactly the five package-owned registration manifests."""

    root = (
        _workflow_handlers_default_package_root()
        if package_root is None
        else Path(package_root)
    ).resolve()
    if not root.is_dir():
        raise WorkflowHandlerAuditError(
            "HANDLER_PACKAGE_ROOT_INVALID",
            "handler package root must be an existing directory",
            details={"package_root": str(root)},
        )
    bindings = globals() if namespace is None else namespace
    schema_refs = frozenset(
        _workflow_handlers_schema_refs
        if schema_registry is None
        else schema_registry.keys()
    )
    source_cache: dict[str, bytes] = {}
    payload_cache: dict[Tuple[str, str], bytes] = {}
    tree_cache: dict[str, ast.Module] = {}
    manifests: list[HandlerRegistrationManifest] = []
    observed_ids: set[str] = set()

    for (
        registry_kind,
        manifest_path,
    ) in _workflow_handlers_manifest_paths.items():
        manifest_file = _workflow_handlers_contained_regular_file(
            root, manifest_path
        )
        document = _workflow_handlers_require_object(
            _workflow_handlers_strict_json(
                manifest_file.read_bytes(), path=manifest_path
            ),
            path=manifest_path,
        )
        _workflow_handlers_require_exact_fields(
            document,
            _workflow_handlers_top_level_fields,
            path=manifest_path,
        )
        if document["manifest_version"] != HANDLER_MANIFEST_VERSION:
            raise WorkflowHandlerAuditError(
                "HANDLER_MANIFEST_VERSION_UNSUPPORTED",
                "handler registration manifest version is unsupported",
                details={
                    "path": manifest_path,
                    "manifest_version": document["manifest_version"],
                },
            )
        if document["audit_policy"] != HANDLER_AUDIT_POLICY:
            raise WorkflowHandlerAuditError(
                "HANDLER_AUDIT_POLICY_UNSUPPORTED",
                "handler audit policy version is unsupported",
                details={
                    "path": manifest_path,
                    "audit_policy": document["audit_policy"],
                },
            )
        if document["registry"] != registry_kind:
            raise WorkflowHandlerAuditError(
                "HANDLER_MANIFEST_REGISTRY_MISMATCH",
                "fixed manifest path declares the wrong registry kind",
                details={
                    "path": manifest_path,
                    "expected": registry_kind,
                    "received": document["registry"],
                },
            )
        file_sets = _workflow_handlers_parse_file_sets(
            document["implementation_file_sets"],
            manifest_path=manifest_path,
        )
        entries: list[HandlerRegistrationSpec] = []
        for index, raw_entry in enumerate(
            _workflow_handlers_require_array(
                document["entries"], path=f"{manifest_path}/entries"
            )
        ):
            spec = _workflow_handlers_parse_entry(
                raw_entry,
                registry_kind=registry_kind,
                index=index,
                manifest_path=manifest_path,
                file_sets=file_sets,
                package_root=root,
                namespace=bindings,
                schema_refs=schema_refs,
                source_cache=source_cache,
                payload_cache=payload_cache,
                tree_cache=tree_cache,
            )
            if spec.handler_id in observed_ids:
                raise WorkflowHandlerAuditError(
                    "HANDLER_ID_DUPLICATE",
                    "handler IDs are globally unique across all registries",
                    details={"handler_id": spec.handler_id},
                )
            observed_ids.add(spec.handler_id)
            entries.append(spec)
        if registry_kind == "commands":
            _workflow_handlers_validate_command_parser_registrations(
                entries
            )
        ordered = sorted(
            entries, key=lambda item: item.handler_id.encode("utf-8")
        )
        if entries != ordered:
            raise WorkflowHandlerAuditError(
                "HANDLER_MANIFEST_ORDER_INVALID",
                "handler entries must be sorted by UTF-8 handler ID",
                details={"path": manifest_path},
            )
        used_file_sets = {
            _workflow_handlers_require_string(
                _workflow_handlers_require_object(raw, path="entry")[
                    "implementation_file_set"
                ],
                path="entry/implementation_file_set",
            )
            for raw in document["entries"]
        }
        unused_file_sets = set(file_sets) - used_file_sets
        if unused_file_sets:
            raise WorkflowHandlerAuditError(
                "HANDLER_IMPLEMENTATION_SET_UNUSED",
                "manifest contains an unused implementation file set",
                details={
                    "path": manifest_path,
                    "file_sets": sorted(unused_file_sets),
                },
            )
        manifests.append(
            HandlerRegistrationManifest(
                registry_kind=registry_kind,
                path=manifest_path,
                entries=tuple(entries),
            )
        )
    return tuple(manifests)


def _workflow_handlers_schema_contract(
    reference: str,
    schema_registry: Optional[Mapping[str, object]],
) -> Mapping[str, object]:
    if schema_registry is None:
        return {"$ref": reference}
    value = schema_registry[reference]
    if not isinstance(value, Mapping):
        raise WorkflowHandlerAuditError(
            "HANDLER_SCHEMA_CONTRACT_INVALID",
            "resolved typed handler schemas must be JSON objects",
            details={"schema_ref": reference},
        )
    return value


def initialize_package_handler_registries(
    *,
    registries: object,
    namespace: Mapping[str, object],
    package_root: Optional[os.PathLike[str]] = None,
    schema_registry: Optional[Mapping[str, object]] = None,
) -> Tuple[HandlerRegistrationManifest, ...]:
    """Audit, register, and permanently seal one fresh runtime registry set."""

    if bool(getattr(registries, "sealed", False)):
        raise WorkflowHandlerAuditError(
            "HANDLER_REGISTRY_NOT_FRESH",
            "package handlers require a fresh unsealed registry set",
        )
    targets: dict[str, object] = {}
    for kind in _workflow_handlers_manifest_paths:
        target = getattr(registries, kind, None)
        if target is None or not callable(getattr(target, "register", None)):
            raise WorkflowHandlerAuditError(
                "HANDLER_REGISTRY_INTERFACE_INVALID",
                "registry set does not expose the required typed registry",
                details={"registry": kind},
            )
        entries = getattr(target, "entries", None)
        if entries is None or len(entries) != 0:
            raise WorkflowHandlerAuditError(
                "HANDLER_REGISTRY_NOT_FRESH",
                "package initialization refuses pre-populated registries",
                details={"registry": kind},
            )
        targets[kind] = target
    seal = getattr(registries, "seal", None)
    if not callable(seal):
        raise WorkflowHandlerAuditError(
            "HANDLER_REGISTRY_INTERFACE_INVALID",
            "registry set does not expose permanent sealing",
        )

    manifests = load_package_handler_manifests(
        package_root=package_root,
        namespace=namespace,
        schema_registry=schema_registry,
    )
    prepared: list[Tuple[object, object]] = []
    for manifest in manifests:
        class_name = _workflow_handlers_registration_type_names[
            manifest.registry_kind
        ]
        registration_type = namespace.get(class_name)
        if not callable(registration_type):
            raise WorkflowHandlerAuditError(
                "HANDLER_REGISTRATION_TYPE_MISSING",
                "shared namespace lacks a typed registration constructor",
                details={
                    "registry": manifest.registry_kind,
                    "symbol": class_name,
                },
            )
        for spec in manifest.entries:
            common: dict[str, object] = {
                "identifier": spec.identifier,
                "contract_version": spec.contract_version,
                "implementation_sha256": spec.implementation_sha256,
                "authority": spec.authority,
                "capabilities": spec.capabilities,
                "input_schema": _workflow_handlers_schema_contract(
                    spec.input_schema_ref, schema_registry
                ),
                "output_schema": _workflow_handlers_schema_contract(
                    spec.output_schema_ref, schema_registry
                ),
                "implementation_files": tuple(
                    item.path for item in spec.implementation_files
                ),
            }
            if spec.registry_kind == "commands":
                common.update(
                    {
                        "command": spec.command,
                        "action_id": spec.action_id,
                        "parser_order": spec.parser_order,
                        "parser_factory_symbol": spec.symbols[
                            "parser_factory"
                        ],
                        "handler_symbol": spec.symbols["handler"],
                    }
                )
            elif spec.registry_kind == "guards":
                common["evaluator_symbol"] = spec.symbols["evaluator"]
            elif spec.registry_kind == "reducers":
                common["reducer_symbol"] = spec.symbols["reducer"]
            elif spec.registry_kind == "gates":
                common["builder_symbol"] = spec.symbols["builder"]
            else:
                common.update(
                    {
                        "dispatcher_symbol": spec.symbols["dispatcher"],
                        "effect_classification": (
                            spec.effect_classification
                        ),
                    }
                )
            prepared.append(
                (
                    targets[spec.registry_kind],
                    registration_type(**common),
                )
            )
    for target, registration in prepared:
        target.register(registration)
    seal(namespace)
    return manifests
