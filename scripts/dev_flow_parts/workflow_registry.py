# Loaded by scripts/dev_flow.py into its shared module namespace after the
# compatibility catalog is enabled.  Until then tests may load this fragment
# directly.  Keep it standard-library only and free of controller globals.
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Generic,
    Mapping,
    MutableMapping,
    Type,
    TypeVar,
)


_workflow_registry_contract_id_re = re.compile(
    r"^[a-z][a-z0-9._-]*(?:/[a-z][a-z0-9._-]*)*$"
)
_workflow_registry_contract_version_re = re.compile(r"^v[1-9][0-9]*$")
_workflow_registry_sha256_re = re.compile(r"^[0-9a-f]{64}$")
_workflow_registry_capability_re = re.compile(
    r"^[a-z][a-z0-9._-]*(?:/[a-z][a-z0-9._-]*)*$"
)
_PORTABLE_PART_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_workflow_registry_symbol_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class WorkflowRegistryError(Exception):
    """Stable structured failure raised before a workflow can be activated."""

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


def _freeze_json_value(value: object, path: str = "$") -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_CONTRACT",
            "typed contracts must not contain floating-point values",
            details={"path": path},
        )
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise WorkflowRegistryError(
                    "REGISTRY_INVALID_CONTRACT",
                    "typed contract object keys must be strings",
                    details={"path": path},
                )
            frozen[key] = _freeze_json_value(item, f"{path}/{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json_value(item, f"{path}/{index}")
            for index, item in enumerate(value)
        )
    raise WorkflowRegistryError(
        "REGISTRY_INVALID_CONTRACT",
        "typed contracts must contain only JSON-compatible values",
        details={"path": path, "type": type(value).__name__},
    )


def _portable_implementation_file(value: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or "\x00" in value
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_IMPLEMENTATION_FILE",
            "implementation files must use portable package-relative paths",
            details={"path": value},
        )
    parts = value.split("/")
    if any(
        part in {"", ".", ".."} or not _PORTABLE_PART_RE.fullmatch(part)
        for part in parts
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_IMPLEMENTATION_FILE",
            "implementation files must use portable package-relative paths",
            details={"path": value},
        )
    return "/".join(parts)


def _validate_registration_common(entry: "Registration") -> None:
    if not _workflow_registry_contract_id_re.fullmatch(entry.identifier):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_ID",
            "registration identifier is not a stable portable contract ID",
            details={"identifier": entry.identifier},
        )
    if not _workflow_registry_contract_version_re.fullmatch(
        entry.contract_version
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_VERSION",
            "contract version must use the form vN",
            details={"contract_version": entry.contract_version},
        )
    if not _workflow_registry_sha256_re.fullmatch(
        entry.implementation_sha256
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_DIGEST",
            "implementation digest must be a lowercase SHA-256 value",
            details={"implementation_sha256": entry.implementation_sha256},
        )
    if not entry.authority:
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_AUTHORITY",
            "registration authority must be declared",
            details={"identifier": entry.identifier},
        )
    if any(
        not isinstance(item, str) or not item
        for item in entry.authority
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_AUTHORITY",
            "registration authority values must be non-empty strings",
            details={"identifier": entry.identifier},
        )
    capabilities = tuple(entry.capabilities)
    if any(
        not isinstance(item, str)
        or not _workflow_registry_capability_re.fullmatch(item)
        for item in capabilities
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_CAPABILITY",
            "registration capabilities must be stable portable IDs",
            details={"identifier": entry.identifier},
        )
    if capabilities != tuple(
        sorted(set(capabilities), key=lambda item: item.encode("utf-8"))
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_CAPABILITY_SET",
            "registration capabilities must be unique and UTF-8 sorted",
            details={"identifier": entry.identifier},
        )
    if not entry.implementation_files:
        raise WorkflowRegistryError(
            "REGISTRY_INCOMPLETE_METADATA",
            "at least one exact implementation file is required",
            details={"identifier": entry.identifier},
        )
    normalized = tuple(
        _portable_implementation_file(item)
        for item in entry.implementation_files
    )
    if normalized != tuple(sorted(set(normalized), key=lambda item: item.encode("utf-8"))):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_IMPLEMENTATION_FILE_SET",
            "implementation files must be unique and sorted by UTF-8 path bytes",
            details={"identifier": entry.identifier},
        )


def _validate_symbol(value: str, *, role: str, identifier: str) -> None:
    if not isinstance(value, str) or not _workflow_registry_symbol_re.fullmatch(
        value
    ):
        raise WorkflowRegistryError(
            "REGISTRY_INVALID_SYMBOL",
            (
                "implementation bindings must name one shared-runtime global "
                "without a module or dotted import path"
            ),
            details={
                "identifier": identifier,
                "role": role,
                "symbol": value if isinstance(value, str) else None,
            },
        )


@dataclass(frozen=True)
class Registration:
    """Immutable common metadata for one executable contract binding."""

    identifier: str
    contract_version: str
    implementation_sha256: str
    authority: tuple[str, ...]
    capabilities: tuple[str, ...]
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object]
    implementation_files: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority", tuple(self.authority))
        object.__setattr__(
            self, "capabilities", tuple(self.capabilities)
        )
        object.__setattr__(
            self, "implementation_files", tuple(self.implementation_files)
        )
        object.__setattr__(
            self,
            "input_schema",
            _freeze_json_value(dict(self.input_schema), "$input_schema"),
        )
        object.__setattr__(
            self,
            "output_schema",
            _freeze_json_value(dict(self.output_schema), "$output_schema"),
        )
        _validate_registration_common(self)

    @property
    def key(self) -> tuple[str, str]:
        return (self.identifier, self.contract_version)

    def binding_symbols(self) -> Mapping[str, str]:
        return MappingProxyType({})

    def bind(
        self, role: str, namespace: Mapping[str, object]
    ) -> object:
        symbol = self.binding_symbols().get(role)
        if symbol is None:
            raise WorkflowRegistryError(
                "REGISTRY_UNKNOWN_BINDING_ROLE",
                "registration has no implementation binding for this role",
                details={"identifier": self.identifier, "role": role},
            )
        implementation = namespace.get(symbol)
        if not callable(implementation):
            raise WorkflowRegistryError(
                "REGISTRY_SYMBOL_UNAVAILABLE",
                "registered shared-runtime symbol is missing or not callable",
                details={
                    "identifier": self.identifier,
                    "role": role,
                    "symbol": symbol,
                },
            )
        return implementation

    def public_metadata(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "contract_version": self.contract_version,
            "implementation_sha256": self.implementation_sha256,
            "authority": list(self.authority),
            "capabilities": list(self.capabilities),
            "implementation_files": list(self.implementation_files),
            "symbols": dict(self.binding_symbols()),
        }


@dataclass(frozen=True)
class CommandRegistration(Registration):
    command: str
    action_id: str
    parser_order: int
    parser_factory_symbol: str
    handler_symbol: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.command or any(char.isspace() for char in self.command):
            raise WorkflowRegistryError(
                "REGISTRY_INVALID_COMMAND",
                "command spelling must be one non-empty token",
                details={"command": self.command},
            )
        if not _workflow_registry_contract_id_re.fullmatch(self.action_id):
            raise WorkflowRegistryError(
                "REGISTRY_INVALID_ACTION_ID",
                "command action ID is not portable",
                details={"action_id": self.action_id},
            )
        if (
            isinstance(self.parser_order, bool)
            or not isinstance(self.parser_order, int)
            or self.parser_order < 0
        ):
            raise WorkflowRegistryError(
                "REGISTRY_INVALID_PARSER_ORDER",
                "command parser order must be a non-negative integer",
                details={"parser_order": self.parser_order},
            )
        _validate_symbol(
            self.parser_factory_symbol,
            role="parser_factory",
            identifier=self.identifier,
        )
        _validate_symbol(
            self.handler_symbol,
            role="handler",
            identifier=self.identifier,
        )

    def binding_symbols(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "parser_factory": self.parser_factory_symbol,
                "handler": self.handler_symbol,
            }
        )

    def public_metadata(self) -> dict[str, object]:
        return {
            **super().public_metadata(),
            "command": self.command,
            "action_id": self.action_id,
            "parser_order": self.parser_order,
        }


@dataclass(frozen=True)
class GuardRegistration(Registration):
    evaluator_symbol: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if tuple(self.authority) != ("read-only",):
            raise WorkflowRegistryError(
                "REGISTRY_FORBIDDEN_AUTHORITY",
                "in-process guards may declare only read-only authority",
                details={"identifier": self.identifier},
            )
        _validate_symbol(
            self.evaluator_symbol,
            role="evaluator",
            identifier=self.identifier,
        )

    def binding_symbols(self) -> Mapping[str, str]:
        return MappingProxyType({"evaluator": self.evaluator_symbol})


@dataclass(frozen=True)
class ReducerRegistration(Registration):
    reducer_symbol: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if tuple(self.authority) != ("state-delta",):
            raise WorkflowRegistryError(
                "REGISTRY_FORBIDDEN_AUTHORITY",
                "in-process reducers may declare only state-delta authority",
                details={"identifier": self.identifier},
            )
        _validate_symbol(
            self.reducer_symbol,
            role="reducer",
            identifier=self.identifier,
        )

    def binding_symbols(self) -> Mapping[str, str]:
        return MappingProxyType({"reducer": self.reducer_symbol})


@dataclass(frozen=True)
class GateRegistration(Registration):
    builder_symbol: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if tuple(self.authority) != ("approval-build",):
            raise WorkflowRegistryError(
                "REGISTRY_FORBIDDEN_AUTHORITY",
                "gate builders may declare only approval-build authority",
                details={"identifier": self.identifier},
            )
        _validate_symbol(
            self.builder_symbol,
            role="builder",
            identifier=self.identifier,
        )

    def binding_symbols(self) -> Mapping[str, str]:
        return MappingProxyType({"builder": self.builder_symbol})


@dataclass(frozen=True)
class ExecutorRegistration(Registration):
    dispatcher_symbol: str
    effect_classification: str = "external"

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_symbol(
            self.dispatcher_symbol,
            role="dispatcher",
            identifier=self.identifier,
        )
        if self.effect_classification not in {
            "deterministic",
            "read-only",
            "workspace-write",
            "external",
            "human",
            "barrier",
        }:
            raise WorkflowRegistryError(
                "REGISTRY_INVALID_EFFECT_CLASSIFICATION",
                "executor effect classification is unsupported",
                details={
                    "identifier": self.identifier,
                    "effect_classification": self.effect_classification,
                },
            )

    def binding_symbols(self) -> Mapping[str, str]:
        return MappingProxyType({"dispatcher": self.dispatcher_symbol})


_RegistrationT = TypeVar("_RegistrationT", bound=Registration)


class _TypedRegistry(Generic[_RegistrationT]):
    """One typed registry with deterministic duplicate and seal behavior."""

    def __init__(
        self,
        name: str,
        entry_type: Type[_RegistrationT],
        before_register: Callable[[str, Registration], None] | None = None,
        after_remove: Callable[[str, Registration], None] | None = None,
    ) -> None:
        self.name = name
        self.entry_type = entry_type
        self._entries: MutableMapping[
            tuple[str, str], _RegistrationT
        ] = {}
        self._bindings: Mapping[
            tuple[str, str, str], Callable[..., object]
        ] = MappingProxyType({})
        self._sealed = False
        self._before_register = before_register
        self._after_remove = after_remove

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def entries(self) -> Mapping[tuple[str, str], _RegistrationT]:
        return MappingProxyType(dict(self._entries))

    def register(self, entry: _RegistrationT) -> _RegistrationT:
        if self._sealed:
            raise WorkflowRegistryError(
                "REGISTRY_SEALED",
                "registration is not permitted after registry sealing",
                details={"registry": self.name},
            )
        if not isinstance(entry, self.entry_type):
            raise WorkflowRegistryError(
                "REGISTRY_TYPE_MISMATCH",
                "registration type does not match the target registry",
                details={
                    "registry": self.name,
                    "expected": self.entry_type.__name__,
                    "received": type(entry).__name__,
                },
            )
        if entry.key in self._entries:
            existing = self._entries[entry.key]
            raise WorkflowRegistryError(
                "REGISTRY_DUPLICATE",
                "duplicate identifier-version registration",
                details={
                    "registry": self.name,
                    "identifier": entry.identifier,
                    "contract_version": entry.contract_version,
                    "existing_implementation_sha256": (
                        existing.implementation_sha256
                    ),
                    "received_implementation_sha256": (
                        entry.implementation_sha256
                    ),
                },
            )
        if self._before_register is not None:
            self._before_register(self.name, entry)
        self._entries[entry.key] = entry
        return entry

    def resolve(
        self, identifier: str, contract_version: str
    ) -> _RegistrationT:
        try:
            return self._entries[(identifier, contract_version)]
        except KeyError as exc:
            raise WorkflowRegistryError(
                "REGISTRY_UNKNOWN_REFERENCE",
                "the requested executable contract is not registered",
                details={
                    "registry": self.name,
                    "identifier": identifier,
                    "contract_version": contract_version,
                },
            ) from exc

    def remove(
        self, identifier: str, contract_version: str
    ) -> _RegistrationT:
        if self._sealed:
            raise WorkflowRegistryError(
                "REGISTRY_SEALED",
                "removal is not permitted after registry sealing",
                details={"registry": self.name},
            )
        entry = self.resolve(identifier, contract_version)
        del self._entries[entry.key]
        if self._after_remove is not None:
            self._after_remove(self.name, entry)
        return entry

    def replace(self, entry: _RegistrationT) -> _RegistrationT:
        if self._sealed:
            raise WorkflowRegistryError(
                "REGISTRY_SEALED",
                "replacement is not permitted after registry sealing",
                details={"registry": self.name},
            )
        if not isinstance(entry, self.entry_type):
            raise WorkflowRegistryError(
                "REGISTRY_TYPE_MISMATCH",
                "replacement type does not match the target registry",
                details={"registry": self.name},
            )
        existing = self.resolve(*entry.key)
        if self._after_remove is not None:
            self._after_remove(self.name, existing)
        try:
            if self._before_register is not None:
                self._before_register(self.name, entry)
        except Exception:
            if self._before_register is not None:
                self._before_register(self.name, existing)
            raise
        self._entries[entry.key] = entry
        return existing

    def _prepare_bindings(
        self, namespace: Mapping[str, object]
    ) -> dict[tuple[str, str, str], Callable[..., object]]:
        prepared: dict[
            tuple[str, str, str], Callable[..., object]
        ] = {}
        for key, entry in sorted(
            self._entries.items(),
            key=lambda item: (
                item[0][0].encode("utf-8"),
                item[0][1].encode("utf-8"),
            ),
        ):
            for role in sorted(entry.binding_symbols()):
                implementation = entry.bind(role, namespace)
                prepared[(key[0], key[1], role)] = implementation
        return prepared

    def _commit_seal(
        self,
        bindings: Mapping[
            tuple[str, str, str], Callable[..., object]
        ],
    ) -> None:
        self._bindings = MappingProxyType(dict(bindings))
        self._sealed = True

    def seal(
        self, namespace: Mapping[str, object] | None = None
    ) -> None:
        if self._sealed:
            raise WorkflowRegistryError(
                "REGISTRY_SEALED",
                "registry sealing cannot be repeated or rebound",
                details={"registry": self.name},
            )
        prepared = (
            {}
            if namespace is None
            else self._prepare_bindings(namespace)
        )
        self._commit_seal(prepared)

    def resolve_callable(
        self,
        identifier: str,
        contract_version: str,
        role: str,
    ) -> Callable[..., object]:
        if not self._sealed:
            raise WorkflowRegistryError(
                "REGISTRY_UNSEALED",
                "executable bindings are unavailable before sealing",
                details={"registry": self.name},
            )
        entry = self.resolve(identifier, contract_version)
        if role not in entry.binding_symbols():
            raise WorkflowRegistryError(
                "REGISTRY_UNKNOWN_BINDING_ROLE",
                "registration has no implementation binding for this role",
                details={
                    "registry": self.name,
                    "identifier": identifier,
                    "role": role,
                },
            )
        try:
            return self._bindings[
                (identifier, contract_version, role)
            ]
        except KeyError as exc:
            raise WorkflowRegistryError(
                "REGISTRY_BINDINGS_UNAVAILABLE",
                "registry was sealed without executable bindings",
                details={
                    "registry": self.name,
                    "identifier": identifier,
                    "contract_version": contract_version,
                    "role": role,
                },
            ) from exc

    def manifest(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "registry": self.name,
                **entry.public_metadata(),
            }
            for _, entry in sorted(
                self._entries.items(),
                key=lambda item: (
                    item[0][0].encode("utf-8"),
                    item[0][1].encode("utf-8"),
                ),
            )
        )


class CommandRegistry(_TypedRegistry[CommandRegistration]):
    def __init__(
        self,
        before_register: Callable[[str, Registration], None] | None = None,
        after_remove: Callable[[str, Registration], None] | None = None,
    ) -> None:
        super().__init__(
            "commands",
            CommandRegistration,
            before_register,
            after_remove,
        )


class GuardRegistry(_TypedRegistry[GuardRegistration]):
    def __init__(
        self,
        before_register: Callable[[str, Registration], None] | None = None,
        after_remove: Callable[[str, Registration], None] | None = None,
    ) -> None:
        super().__init__(
            "guards",
            GuardRegistration,
            before_register,
            after_remove,
        )


class ReducerRegistry(_TypedRegistry[ReducerRegistration]):
    def __init__(
        self,
        before_register: Callable[[str, Registration], None] | None = None,
        after_remove: Callable[[str, Registration], None] | None = None,
    ) -> None:
        super().__init__(
            "reducers",
            ReducerRegistration,
            before_register,
            after_remove,
        )


class GateRegistry(_TypedRegistry[GateRegistration]):
    def __init__(
        self,
        before_register: Callable[[str, Registration], None] | None = None,
        after_remove: Callable[[str, Registration], None] | None = None,
    ) -> None:
        super().__init__(
            "gates",
            GateRegistration,
            before_register,
            after_remove,
        )


class ExecutorRegistry(_TypedRegistry[ExecutorRegistration]):
    def __init__(
        self,
        before_register: Callable[[str, Registration], None] | None = None,
        after_remove: Callable[[str, Registration], None] | None = None,
    ) -> None:
        super().__init__(
            "executors",
            ExecutorRegistration,
            before_register,
            after_remove,
        )


class RuntimeRegistries:
    """Own the five registries and enforce process-wide contract identity."""

    def __init__(self) -> None:
        self._sealed = False
        self._global: dict[tuple[str, str], str] = {}
        self.commands = CommandRegistry(
            self._reserve_identity, self._release_identity
        )
        self.guards = GuardRegistry(
            self._reserve_identity, self._release_identity
        )
        self.reducers = ReducerRegistry(
            self._reserve_identity, self._release_identity
        )
        self.gates = GateRegistry(
            self._reserve_identity, self._release_identity
        )
        self.executors = ExecutorRegistry(
            self._reserve_identity, self._release_identity
        )

    @property
    def sealed(self) -> bool:
        return self._sealed

    def _reserve_identity(
        self, registry_name: str, entry: Registration
    ) -> None:
        if self._sealed:
            raise WorkflowRegistryError(
                "REGISTRY_SET_SEALED",
                "runtime registries are already sealed",
            )
        owner = self._global.get(entry.key)
        if owner is not None:
            raise WorkflowRegistryError(
                "REGISTRY_GLOBAL_DUPLICATE",
                "contract identity is already owned by another registry",
                details={
                    "identifier": entry.identifier,
                    "contract_version": entry.contract_version,
                    "existing_registry": owner,
                    "received_registry": registry_name,
                },
            )
        self._global[entry.key] = registry_name

    def _release_identity(
        self, registry_name: str, entry: Registration
    ) -> None:
        if self._global.get(entry.key) == registry_name:
            del self._global[entry.key]

    def all(self) -> tuple[_TypedRegistry[Any], ...]:
        return (
            self.commands,
            self.guards,
            self.reducers,
            self.gates,
            self.executors,
        )

    def seal(
        self, namespace: Mapping[str, object] | None = None
    ) -> None:
        if self._sealed:
            raise WorkflowRegistryError(
                "REGISTRY_SET_SEALED",
                "runtime registry sealing cannot be repeated or rebound",
            )
        prepared = tuple(
            (
                registry,
                (
                    {}
                    if namespace is None
                    else registry._prepare_bindings(namespace)
                ),
            )
            for registry in self.all()
        )
        for registry, bindings in prepared:
            registry._commit_seal(bindings)
        self._sealed = True

    def manifest(self) -> tuple[dict[str, object], ...]:
        entries = [
            item
            for registry in self.all()
            for item in registry.manifest()
        ]
        return tuple(
            sorted(
                entries,
                key=lambda item: (
                    str(item["identifier"]).encode("utf-8"),
                    str(item["contract_version"]).encode("utf-8"),
                    str(item["registry"]).encode("utf-8"),
                ),
            )
        )
