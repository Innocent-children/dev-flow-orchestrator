# Loaded by scripts/dev_flow.py into its shared module namespace.
# Responsibility: parse and seal the two package-owned V4 workflow bundles.
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence
import unicodedata


CATALOG_SCHEMA = "dev-flow-workflow-catalog/v1"
ACTIVATION_SCHEMA = "dev-flow-workflow-activation/v1"
WORKFLOW_SCHEMA = "dev-flow-workflow/v1"
BUNDLE_IDENTITY_CONTRACT = "dev-flow-bundle-identity/v1"
SUPPORTED_BUNDLE_SCHEMA_VERSIONS = frozenset({1})
SUPPORTED_CONTRACT_REGISTRIES = frozenset(
    {"executors", "gates", "guards", "reducers"}
)
V4_HANDLER_CLOSURE_ROLES = (
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
)
_workflow_catalog_v4_handler_closure_roles = (
    V4_HANDLER_CLOSURE_ROLES
)
_workflow_catalog_supported_node_contracts = MappingProxyType(
    {
        "generic": frozenset({"v1"}),
        "state": frozenset({"v1"}),
    }
)
_workflow_catalog_supported_node_recovery_modes = frozenset(
    {"manual", "restart"}
)
_workflow_catalog_supported_node_uncertain_outcomes = frozenset(
    {"block", "quarantine"}
)
_workflow_catalog_sha256_re = re.compile(r"^[0-9a-f]{64}$")
V4_PROFILE_SUITES = MappingProxyType(
    {
        ("full", "single-repository"): (
            "v4-static-closure",
            "v4-core-runtime",
            "v4-effect-recovery",
            "v4-external-tools",
        ),
        ("full", "multi-repository"): (
            "v4-static-closure",
            "v4-core-runtime",
            "v4-effect-recovery",
            "v4-external-tools",
            "v4-multi-repository",
        ),
        ("lite", "single-repository"): (
            "v4-static-closure",
            "v4-core-runtime",
            "v4-effect-recovery",
        ),
    }
)


def _load_v4_repository_semantic_identities(
) -> Mapping[str, Mapping[str, object]]:
    runtime_path = Path(__file__).resolve()
    repository_root = (
        runtime_path.parent.parent
        if runtime_path.parent.name == "scripts"
        else runtime_path.parents[2]
    )
    graph_path = (
        repository_root
        / "workflows"
        / "bundles"
        / "full-v4"
        / "workflow.json"
    )
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "full@4 repository orchestration contract is unavailable"
        ) from exc
    orchestration = graph.get("repository_orchestration")
    matrix = (
        orchestration.get("operation_matrix")
        if isinstance(orchestration, Mapping)
        else None
    )
    if not isinstance(matrix, list) or not matrix:
        raise RuntimeError(
            "full@4 repository operation matrix is unavailable"
        )
    identities: dict[str, Mapping[str, object]] = {}
    for item in matrix:
        if not isinstance(item, Mapping):
            raise RuntimeError(
                "full@4 repository operation identity is invalid"
            )
        operation_id = item.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise RuntimeError(
                "full@4 repository operation identity is invalid"
            )
        identity = dict(item)
        effect_ids = identity.get("effect_ids")
        if isinstance(effect_ids, list):
            identity["effect_ids"] = tuple(effect_ids)
        identities[operation_id] = MappingProxyType(identity)
    return MappingProxyType(identities)


_V4_REPOSITORY_SEMANTIC_IDENTITIES = (
    _load_v4_repository_semantic_identities()
)
_workflow_catalog_repository_required_operation_ids = frozenset(
    _V4_REPOSITORY_SEMANTIC_IDENTITIES
)


def _load_v4_repository_operation_write_sets(
) -> Mapping[str, tuple[str, ...]]:
    runtime_path = Path(__file__).resolve()
    repository_root = (
        runtime_path.parent.parent
        if runtime_path.parent.name == "scripts"
        else runtime_path.parents[2]
    )
    graph_path = (
        repository_root
        / "workflows"
        / "bundles"
        / "full-v4"
        / "workflow.json"
    )
    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "full@4 repository write contract is unavailable"
        ) from exc
    shared_actions = graph.get("shared_actions")
    if not isinstance(shared_actions, list):
        raise RuntimeError(
            "full@4 repository action inventory is unavailable"
        )
    by_action: dict[str, tuple[str, ...]] = {}
    for item in shared_actions:
        action = item.get("action") if isinstance(item, Mapping) else None
        if not isinstance(action, Mapping):
            raise RuntimeError(
                "full@4 repository action contract is invalid"
            )
        action_id = action.get("id")
        roots = action.get("kernel_state_writes")
        if (
            not isinstance(action_id, str)
            or not isinstance(roots, list)
            or not roots
            or any(
                not isinstance(root, str) or not root.startswith("/")
                for root in roots
            )
        ):
            raise RuntimeError(
                "full@4 repository action write contract is invalid"
            )
        by_action[action_id] = tuple(roots)
    write_sets: dict[str, tuple[str, ...]] = {}
    for operation_id, identity in (
        _V4_REPOSITORY_SEMANTIC_IDENTITIES.items()
    ):
        action_id = identity.get("action_id")
        roots = by_action.get(str(action_id))
        if roots is None:
            raise RuntimeError(
                "full@4 repository operation has no action write contract"
            )
        write_sets[operation_id] = roots
    return MappingProxyType(write_sets)


_workflow_catalog_repository_operation_write_sets = (
    _load_v4_repository_operation_write_sets()
)


def _workflow_catalog_repository_semantic_identities(
    operation_id: str,
) -> Mapping[str, object]:
    try:
        return _V4_REPOSITORY_SEMANTIC_IDENTITIES[operation_id]
    except KeyError as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_REPOSITORY_OPERATION_UNKNOWN",
            "repository operation is outside the full@4 contract",
            details={"operation_id": operation_id},
        ) from exc
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$")
_VERSION_RE = re.compile(r"^v[1-9][0-9]*$")


class WorkflowCatalogError(Exception):
    """Stable structured failure raised while sealing the V4 catalog."""

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


def _workflow_catalog_v4_error(
    code: str,
    message: str,
    *,
    pointer: str,
    **details: object,
) -> WorkflowCatalogError:
    return WorkflowCatalogError(
        code, message, details={"pointer": pointer, **details}
    )


def _workflow_catalog_v4_object(value: object, pointer: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in value
    ):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_DOCUMENT_INVALID",
            "workflow value must be an object with string keys",
            pointer=pointer,
        )
    return value


def _workflow_catalog_v4_array(value: object, pointer: str) -> list[object]:
    if not isinstance(value, list):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_DOCUMENT_INVALID",
            "workflow value must be an array",
            pointer=pointer,
        )
    return value


def _workflow_catalog_v4_text(value: object, pointer: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_DOCUMENT_INVALID",
            "workflow text must be non-empty NFC text",
            pointer=pointer,
        )
    return value


def _workflow_catalog_v4_integer(value: object, pointer: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_DOCUMENT_INVALID",
            "workflow value must be an integer",
            pointer=pointer,
        )
    return value


def _workflow_catalog_v4_exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    pointer: str,
) -> None:
    if set(value) != set(expected):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_DOCUMENT_FIELDS_INVALID",
            "workflow object fields differ from the V4 contract",
            pointer=pointer,
            missing=sorted(set(expected) - set(value)),
            unknown=sorted(set(value) - set(expected)),
        )


def _workflow_catalog_v4_reject_float(_value: str) -> object:
    raise ValueError("floating-point JSON values are not allowed")


def _workflow_catalog_v4_reject_constant(_value: str) -> object:
    raise ValueError("non-finite JSON values are not allowed")


def _workflow_catalog_v4_unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        if unicodedata.normalize("NFC", key) != key:
            raise ValueError("JSON keys must be NFC")
        result[key] = value
    return result


def _workflow_catalog_v4_parse_json(path: Path, relative: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError("BOM is not allowed")
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_workflow_catalog_v4_unique_object,
            parse_float=_workflow_catalog_v4_reject_float,
            parse_constant=_workflow_catalog_v4_reject_constant,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_JSON_INVALID",
            "workflow JSON is not canonicalizable",
            details={"path": relative, "error": str(exc)},
        ) from exc
    return _workflow_catalog_v4_object(value, "/")


def _workflow_catalog_v4_regular_file(root: Path, relative: str) -> Path:
    if (
        not relative
        or "\\" in relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or unicodedata.normalize("NFC", relative) != relative
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_PATH_INVALID",
            "workflow path is not a portable package-relative path",
            details={"path": relative},
        )
    candidate = root.joinpath(*relative.split("/"))
    try:
        if candidate.is_symlink() or not candidate.is_file():
            raise OSError("path is not one regular file")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_PATH_INVALID",
            "workflow path does not resolve to one contained regular file",
            details={"path": relative},
        ) from exc
    return candidate


@dataclass(frozen=True, order=True)
class ContractReference:
    registry: str
    identifier: str
    version: str


def _workflow_catalog_v4_contract(value: object, pointer: str) -> ContractReference:
    item = _workflow_catalog_v4_object(value, pointer)
    _workflow_catalog_v4_exact_fields(item, frozenset({"registry", "id", "version"}), pointer)
    registry = _workflow_catalog_v4_text(item["registry"], f"{pointer}/registry")
    identifier = _workflow_catalog_v4_text(item["id"], f"{pointer}/id")
    version = _workflow_catalog_v4_text(item["version"], f"{pointer}/version")
    if (
        registry not in SUPPORTED_CONTRACT_REGISTRIES
        or not _ID_RE.fullmatch(identifier)
        or not _VERSION_RE.fullmatch(version)
        or not identifier.endswith(f"/{version}")
    ):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_INVALID_CONTRACT",
            "workflow contract reference is not a supported versioned ID",
            pointer=pointer,
        )
    return ContractReference(registry, identifier, version)


class StaticContractResolver:
    """Sealed resolver useful for isolated catalog validation."""

    def __init__(
        self, references: Iterable[ContractReference | tuple[str, str, str]]
    ) -> None:
        self._workflow_catalog_v4_references = frozenset(
            item if isinstance(item, ContractReference) else ContractReference(*item)
            for item in references
        )
        self.sealed = True

    @property
    def references(self) -> frozenset[ContractReference]:
        return self._workflow_catalog_v4_references

    def resolve(
        self, registry: str, identifier: str, version: str
    ) -> ContractReference:
        reference = ContractReference(registry, identifier, version)
        if reference not in self._workflow_catalog_v4_references:
            raise KeyError(reference)
        return reference

    def identity_handlers(
        self, _workflow_catalog_v4_references: Sequence[ContractReference]
    ) -> tuple[object, ...]:
        return ()


def _workflow_catalog_v4_resolve_contract(
    resolver: object, reference: ContractReference
) -> object:
    if getattr(resolver, "sealed", False) is not True:
        raise WorkflowCatalogError(
            "WORKFLOW_REGISTRY_UNSEALED",
            "workflow contracts require a sealed resolver",
        )
    try:
        return resolver.resolve(
            reference.registry, reference.identifier, reference.version
        )
    except Exception as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_CONTRACT_UNKNOWN",
            "workflow references an unregistered V4 contract",
            details={
                "registry": reference.registry,
                "id": reference.identifier,
                "version": reference.version,
            },
        ) from exc


def _workflow_catalog_v4_freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _workflow_catalog_v4_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_workflow_catalog_v4_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class WorkflowBundle:
    workflow_id: str
    workflow_version: int
    bundle_schema_version: int
    graph_sha256: str
    bundle_sha256: str
    root: Path
    graph: Mapping[str, object]
    resources: Mapping[str, tuple[str, bytes]]
    nodes: Mapping[str, Mapping[str, object]]
    edges: tuple[Mapping[str, object], ...]
    action_edges: tuple[Mapping[str, object], ...]
    contracts: tuple[ContractReference, ...]
    execution_profiles: tuple[str, ...]
    repository_orchestration: Mapping[str, object] | None
    active_profiles: tuple[str, ...]

    @property
    def key(self) -> tuple[str, int]:
        return (self.workflow_id, self.workflow_version)

    @property
    def movement_edges(self) -> tuple[Mapping[str, object], ...]:
        return self.edges

    @property
    def tool_capabilities(self) -> tuple[Mapping[str, object], ...]:
        value = self.graph.get("tool_capabilities", ())
        return tuple(value) if isinstance(value, tuple) else ()

    def node(self, node_id: str) -> Mapping[str, object]:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_NODE_UNKNOWN",
                "workflow node is not defined",
                details={"node_id": node_id},
            ) from exc

    def tool_capability(self, capability_id: str) -> Mapping[str, object]:
        matches = tuple(
            item
            for item in self.tool_capabilities
            if item.get("capability_id") == capability_id
        )
        if len(matches) != 1:
            raise WorkflowCatalogError(
                "WORKFLOW_TOOL_CAPABILITY_UNKNOWN",
                "tool capability is not declared exactly once",
                details={"capability_id": capability_id},
            )
        return matches[0]

    def legal_movement_edges(
        self, source: str
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(edge for edge in self.edges if edge["source"] == source)

    def legal_action_edges(
        self, source: str
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(
            edge for edge in self.action_edges if edge["source"] == source
        )

    def legal_edges(self, source: str) -> tuple[Mapping[str, object], ...]:
        return tuple(
            sorted(
                (
                    *self.legal_movement_edges(source),
                    *self.legal_action_edges(source),
                ),
                key=lambda item: str(item["id"]).encode("utf-8"),
            )
        )

    def resolve_action_handler(
        self,
        action_id: str,
        role: str,
        *,
        call_target: ContractReference | None = None,
    ) -> ContractReference:
        if role not in V4_HANDLER_CLOSURE_ROLES:
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CLOSURE_INVALID",
                "V4 handler role is unsupported",
                details={"action_id": action_id, "role": role},
            )
        matches: set[ContractReference] = set()
        for edge in self.action_edges:
            trigger = edge.get("trigger")
            if not isinstance(trigger, Mapping) or trigger.get("id") != action_id:
                continue
            for item in edge.get("handler_closure", ()):
                if not isinstance(item, Mapping) or item.get("role") != role:
                    continue
                handler = item.get("handler")
                if isinstance(handler, Mapping):
                    matches.add(
                        ContractReference(
                            str(handler.get("registry")),
                            str(handler.get("id")),
                            str(handler.get("version")),
                        )
                    )
        if len(matches) != 1:
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CLOSURE_UNKNOWN",
                "action does not resolve to one V4 handler",
                details={"action_id": action_id, "role": role},
            )
        resolved = next(iter(matches))
        if call_target is not None and (
            not isinstance(call_target, ContractReference)
            or call_target != resolved
        ):
            raise WorkflowCatalogError(
                "WORKFLOW_HANDLER_CALL_TARGET_UNPINNED",
                "handler call target differs from the bundle identity",
                details={"action_id": action_id, "role": role},
            )
        return resolved

    def resolve_public_action(
        self,
        source: str,
        command: str,
        *,
        selector: str | None = None,
    ) -> Mapping[str, object]:
        command_matches: list[Mapping[str, object]] = []
        selector_matches: list[Mapping[str, object]] = []
        for edge in self.legal_action_edges(source):
            public = edge.get("public_command")
            if not isinstance(public, Mapping) or public.get("id") != command:
                continue
            command_matches.append(edge)
            values = public.get("values")
            if isinstance(values, (list, tuple)) and (
                (not values and selector is None) or selector in values
            ):
                selector_matches.append(edge)
        if len(selector_matches) == 1:
            return selector_matches[0]
        if len(selector_matches) > 1:
            raise WorkflowCatalogError(
                "WORKFLOW_ACTION_SELECTION_AMBIGUOUS",
                "public action resolves more than once",
                details={"source": source, "command": command, "selector": selector},
            )
        raise WorkflowCatalogError(
            (
                "WORKFLOW_ACTION_SELECTOR_UNDECLARED"
                if command_matches
                else "WORKFLOW_ACTION_PLACEMENT_INVALID"
            ),
            "public action is not declared at the current node",
            details={"source": source, "command": command, "selector": selector},
        )


@dataclass(frozen=True)
class WorkflowCatalog:
    bundles: Mapping[tuple[str, int], WorkflowBundle]
    bundles_by_identity: Mapping[str, WorkflowBundle]
    activations: tuple[Mapping[str, object], ...]
    sealed: bool = True

    def resolve(
        self, workflow_id: str, workflow_version: int
    ) -> WorkflowBundle:
        try:
            return self.bundles[(workflow_id, workflow_version)]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_BUNDLE_UNKNOWN",
                "V4 workflow bundle is absent",
                details={
                    "workflow_id": workflow_id,
                    "workflow_version": workflow_version,
                },
            ) from exc

    def resolve_identity(self, bundle_sha256: str) -> WorkflowBundle:
        try:
            return self.bundles_by_identity[bundle_sha256]
        except KeyError as exc:
            raise WorkflowCatalogError(
                "WORKFLOW_BUNDLE_UNKNOWN",
                "V4 bundle identity is absent",
                details={"bundle_sha256": bundle_sha256},
            ) from exc


def _workflow_catalog_v4_references(
    graph: Mapping[str, object], resolver: object
) -> tuple[ContractReference, ...]:
    values = _workflow_catalog_v4_array(graph.get("contracts"), "/contracts")
    result = tuple(
        _workflow_catalog_v4_contract(item, f"/contracts/{index}")
        for index, item in enumerate(values)
    )
    if len(result) != len(set(result)):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_CONTRACT_DUPLICATE",
            "workflow contracts must be unique",
            pointer="/contracts",
        )
    for reference in result:
        _workflow_catalog_v4_resolve_contract(resolver, reference)
    return tuple(sorted(result))


def _workflow_catalog_v4_validate_handler_closure(
    action: Mapping[str, object],
    pointer: str,
    declared: frozenset[ContractReference],
) -> None:
    values = _workflow_catalog_v4_array(action.get("handler_closure"), f"{pointer}/handler_closure")
    if len(values) != len(V4_HANDLER_CLOSURE_ROLES):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID",
            "V4 action closure must contain every role exactly once",
            pointer=f"{pointer}/handler_closure",
        )
    roles: list[str] = []
    for index, raw in enumerate(values):
        item = _workflow_catalog_v4_object(raw, f"{pointer}/handler_closure/{index}")
        _workflow_catalog_v4_exact_fields(
            item,
            frozenset({"role", "handler"}),
            f"{pointer}/handler_closure/{index}",
        )
        role = _workflow_catalog_v4_text(item["role"], f"{pointer}/handler_closure/{index}/role")
        handler = _workflow_catalog_v4_contract(
            item["handler"], f"{pointer}/handler_closure/{index}/handler"
        )
        expected = ContractReference(
            "executors", f"executor.v4-{role}/v2", "v2"
        )
        if handler != expected or handler not in declared:
            raise _workflow_catalog_v4_error(
                "WORKFLOW_HANDLER_CLOSURE_INVALID",
                "V4 action closure handler is not direct and identity-covered",
                pointer=f"{pointer}/handler_closure/{index}",
            )
        roles.append(role)
    if tuple(roles) != V4_HANDLER_CLOSURE_ROLES:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID",
            "V4 action closure roles are not canonical",
            pointer=f"{pointer}/handler_closure",
        )


def _workflow_catalog_v4_compile_action(
    raw: object,
    *,
    source: str,
    edge_id: str | None,
    pointer: str,
    declared: frozenset[ContractReference],
) -> dict[str, object]:
    action = dict(_workflow_catalog_v4_object(raw, pointer))
    action_id = _workflow_catalog_v4_text(action.get("id"), f"{pointer}/id")
    actual_edge_id = edge_id or _workflow_catalog_v4_text(
        action.get("edge_id"), f"{pointer}/edge_id"
    )
    if edge_id is not None and "edge_id" in action:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_ACTION_INVALID",
            "shared action must take its edge ID from its placement",
            pointer=pointer,
        )
    _workflow_catalog_v4_validate_handler_closure(action, pointer, declared)
    for field in ("handler", "guards", "reducers"):
        values = (
            [action[field]]
            if field == "handler"
            else _workflow_catalog_v4_array(action.get(field), f"{pointer}/{field}")
        )
        for index, value in enumerate(values):
            reference = _workflow_catalog_v4_contract(value, f"{pointer}/{field}/{index}")
            if reference not in declared:
                raise _workflow_catalog_v4_error(
                    "WORKFLOW_CONTRACT_UNDECLARED",
                    "action references an undeclared contract",
                    pointer=f"{pointer}/{field}/{index}",
                )
    gate = action.get("gate")
    if gate is not None and _workflow_catalog_v4_contract(gate, f"{pointer}/gate") not in declared:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_CONTRACT_UNDECLARED",
            "action gate is undeclared",
            pointer=f"{pointer}/gate",
        )
    action.pop("edge_id", None)
    action.update(
        {
            "id": actual_edge_id,
            "source": source,
            "target": source,
            "class": "action",
            "automatic": False,
            "policy": "node-action",
            "priority": 100,
            "tool_capabilities": tuple(
                action.get("tool_policy", {}).get("capabilities", ())
                if isinstance(action.get("tool_policy"), Mapping)
                else ()
            ),
        }
    )
    trigger = action.get("trigger")
    if (
        not isinstance(trigger, dict)
        or trigger.get("kind") != "action"
        or trigger.get("id") != action_id
    ):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_ACTION_INVALID",
            "action trigger must bind the action identity",
            pointer=f"{pointer}/trigger",
        )
    return action


def _workflow_catalog_v4_compile_graph(
    graph: dict[str, object],
    resolver: object,
) -> tuple[
    Mapping[str, object],
    Mapping[str, Mapping[str, object]],
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
    tuple[ContractReference, ...],
    tuple[str, ...],
]:
    if graph.get("schema") != WORKFLOW_SCHEMA:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_SCHEMA_UNSUPPORTED",
            "bundle must use the current workflow schema",
            pointer="/schema",
        )
    if (
        _workflow_catalog_v4_integer(graph.get("workflow_version"), "/workflow_version") != 4
        or graph.get("task_schema_versions") != [4]
    ):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_V4_IDENTITY_INVALID",
            "bundle must directly declare workflow 4 and task schema 4",
            pointer="/",
        )
    flow = _workflow_catalog_v4_text(graph.get("flow"), "/flow")
    if flow not in {"full", "lite"} or graph.get("workflow_id") != flow:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_V4_IDENTITY_INVALID",
            "workflow ID and flow must be full or lite and equal",
            pointer="/workflow_id",
        )
    expected_profiles = (
        ["single-repository", "multi-repository"]
        if flow == "full"
        else ["single-repository"]
    )
    if graph.get("execution_profiles") != expected_profiles:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_PROFILE_INVALID",
            "workflow profiles differ from the V4 product contract",
            pointer="/execution_profiles",
        )
    contracts = _workflow_catalog_v4_references(graph, resolver)
    declared = frozenset(contracts)
    raw_nodes = _workflow_catalog_v4_array(graph.get("nodes"), "/nodes")
    nodes: dict[str, Mapping[str, object]] = {}
    actions: list[Mapping[str, object]] = []
    for index, raw_node in enumerate(raw_nodes):
        node = dict(_workflow_catalog_v4_object(raw_node, f"/nodes/{index}"))
        node_id = _workflow_catalog_v4_text(node.get("id"), f"/nodes/{index}/id")
        if node_id in nodes:
            raise _workflow_catalog_v4_error(
                "WORKFLOW_NODE_DUPLICATE",
                "node IDs must be unique",
                pointer=f"/nodes/{index}/id",
            )
        for action_index, raw_action in enumerate(
            _workflow_catalog_v4_array(node.get("actions"), f"/nodes/{index}/actions")
        ):
            actions.append(
                _workflow_catalog_v4_freeze(
                    _workflow_catalog_v4_compile_action(
                        raw_action,
                        source=node_id,
                        edge_id=None,
                        pointer=f"/nodes/{index}/actions/{action_index}",
                        declared=declared,
                    )
                )
            )
        nodes[node_id] = _workflow_catalog_v4_freeze(node)  # type: ignore[assignment]
    policies: dict[str, dict[str, object]] = {}
    for index, raw_policy in enumerate(
        _workflow_catalog_v4_array(graph.get("edge_policies"), "/edge_policies")
    ):
        policy = dict(_workflow_catalog_v4_object(raw_policy, f"/edge_policies/{index}"))
        policy_id = _workflow_catalog_v4_text(policy.pop("id", None), f"/edge_policies/{index}/id")
        if policy_id in policies:
            raise _workflow_catalog_v4_error(
                "WORKFLOW_EDGE_POLICY_DUPLICATE",
                "edge policy IDs must be unique",
                pointer=f"/edge_policies/{index}/id",
            )
        policies[policy_id] = policy
    movements: list[Mapping[str, object]] = []
    raw_edges = list(_workflow_catalog_v4_array(graph.get("edges"), "/edges"))
    for family_index, raw_family in enumerate(
        _workflow_catalog_v4_array(graph.get("edge_families"), "/edge_families")
    ):
        family = _workflow_catalog_v4_object(raw_family, f"/edge_families/{family_index}")
        prefix = _workflow_catalog_v4_text(
            family.get("id_prefix"), f"/edge_families/{family_index}/id_prefix"
        )
        sources = _workflow_catalog_v4_array(
            family.get("sources"), f"/edge_families/{family_index}/sources"
        )
        targets = _workflow_catalog_v4_array(
            family.get("targets"), f"/edge_families/{family_index}/targets"
        )
        policy_id = _workflow_catalog_v4_text(
            family.get("policy"), f"/edge_families/{family_index}/policy"
        )
        for source in sources:
            for target in targets:
                raw_edges.append(
                    {
                        "id": (
                            f"{prefix}.{str(source).lower().replace('_', '-')}"
                            f".{str(target).lower().replace('_', '-')}"
                        ),
                        "source": source,
                        "target": target,
                        "policy": policy_id,
                    }
                )
    edge_ids: set[str] = set()
    for index, raw_edge in enumerate(raw_edges):
        edge = dict(_workflow_catalog_v4_object(raw_edge, f"/edges/{index}"))
        edge_id = _workflow_catalog_v4_text(edge.get("id"), f"/edges/{index}/id")
        source = _workflow_catalog_v4_text(edge.get("source"), f"/edges/{index}/source")
        target = _workflow_catalog_v4_text(edge.get("target"), f"/edges/{index}/target")
        policy_id = _workflow_catalog_v4_text(edge.get("policy"), f"/edges/{index}/policy")
        if (
            edge_id in edge_ids
            or source not in nodes
            or target not in nodes
            or policy_id not in policies
        ):
            raise _workflow_catalog_v4_error(
                "WORKFLOW_EDGE_INVALID",
                "movement edge is duplicate or unresolved",
                pointer=f"/edges/{index}",
            )
        edge_ids.add(edge_id)
        compiled = {**policies[policy_id], **edge}
        movements.append(_workflow_catalog_v4_freeze(compiled))  # type: ignore[arg-type]
    for family_index, raw_family in enumerate(
        _workflow_catalog_v4_array(graph.get("shared_actions"), "/shared_actions")
    ):
        family = _workflow_catalog_v4_object(raw_family, f"/shared_actions/{family_index}")
        raw_action = family.get("action")
        for placement_index, raw_placement in enumerate(
            _workflow_catalog_v4_array(
                family.get("placements"),
                f"/shared_actions/{family_index}/placements",
            )
        ):
            placement = _workflow_catalog_v4_object(
                raw_placement,
                f"/shared_actions/{family_index}/placements/{placement_index}",
            )
            source = _workflow_catalog_v4_text(
                placement.get("node"),
                f"/shared_actions/{family_index}/placements/{placement_index}/node",
            )
            edge_id = _workflow_catalog_v4_text(
                placement.get("edge_id"),
                f"/shared_actions/{family_index}/placements/{placement_index}/edge_id",
            )
            if source not in nodes:
                raise _workflow_catalog_v4_error(
                    "WORKFLOW_ACTION_PLACEMENT_INVALID",
                    "shared action placement references an unknown node",
                    pointer=f"/shared_actions/{family_index}/placements/{placement_index}",
                )
            actions.append(
                _workflow_catalog_v4_freeze(
                    _workflow_catalog_v4_compile_action(
                        raw_action,
                        source=source,
                        edge_id=edge_id,
                        pointer=f"/shared_actions/{family_index}/action",
                        declared=declared,
                    )
                )
            )
    action_ids = [str(action["id"]) for action in actions]
    if len(action_ids) != len(set(action_ids)):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_ACTION_DUPLICATE",
            "action edge IDs must be unique",
            pointer="/",
        )
    orchestration = graph.get("repository_orchestration")
    if flow == "full":
        metadata = _workflow_catalog_v4_object(orchestration, "/repository_orchestration")
    elif orchestration is not None:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_ORCHESTRATION_INVALID",
            "lite workflow cannot carry multi-repository metadata",
            pointer="/repository_orchestration",
        )
    return (
        _workflow_catalog_v4_freeze(graph),  # type: ignore[return-value]
        MappingProxyType(nodes),
        tuple(sorted(movements, key=lambda item: str(item["id"]).encode("utf-8"))),
        tuple(sorted(actions, key=lambda item: str(item["id"]).encode("utf-8"))),
        contracts,
        tuple(expected_profiles),
    )


def _workflow_catalog_v4_identity(
    identity_api: object,
    *,
    graph_source: bytes,
    files: Sequence[tuple[str, str, bytes]],
    contracts: Sequence[ContractReference],
    resolver: object,
) -> tuple[str, str]:
    try:
        file_type = identity_api.BundleFile
        handlers = tuple(resolver.identity_handlers(tuple(contracts)))
        result = identity_api.compute_workflow_bundle_identity(
            graph_source,
            tuple(file_type(path, kind, source) for path, kind, source in files),
            handlers,
        )
        graph_sha256 = str(result.graph_sha256)
        bundle_sha256 = str(result.bundle_sha256)
    except Exception as exc:
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_FAILED",
            "V4 bundle identity could not be computed",
            details={"error_type": type(exc).__name__},
        ) from exc
    if not _SHA256_RE.fullmatch(graph_sha256) or not _SHA256_RE.fullmatch(
        bundle_sha256
    ):
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_FAILED",
            "identity implementation returned malformed digests",
        )
    return graph_sha256, bundle_sha256


def _workflow_catalog_v4_load(
    workflows_root: Path | str,
    *,
    contract_resolver: object,
    identity_api: object,
    verify_stored_digests: bool,
) -> WorkflowCatalog:
    root = Path(workflows_root).resolve()
    catalog = _workflow_catalog_v4_parse_json(_workflow_catalog_v4_regular_file(root, "catalog.json"), "catalog.json")
    _workflow_catalog_v4_exact_fields(
        catalog,
        frozenset({"schema", "identity_contract", "activation", "bundles"}),
        "/",
    )
    if (
        catalog.get("schema") != CATALOG_SCHEMA
        or catalog.get("identity_contract") != BUNDLE_IDENTITY_CONTRACT
        or catalog.get("activation") != "activation.json"
    ):
        raise _workflow_catalog_v4_error(
            "WORKFLOW_CATALOG_SCHEMA_UNSUPPORTED",
            "catalog header differs from the V4 contract",
            pointer="/",
        )
    entries = _workflow_catalog_v4_array(catalog.get("bundles"), "/bundles")
    if len(entries) != 2:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_CATALOG_INVENTORY_INVALID",
            "catalog must contain exactly two V4 bundles",
            pointer="/bundles",
        )
    bundles: dict[tuple[str, int], WorkflowBundle] = {}
    for index, raw_entry in enumerate(entries):
        pointer = f"/bundles/{index}"
        entry = _workflow_catalog_v4_object(raw_entry, pointer)
        _workflow_catalog_v4_exact_fields(
            entry,
            frozenset(
                {
                    "workflow_id",
                    "workflow_version",
                    "bundle_schema_version",
                    "root",
                    "graph",
                    "files",
                    "graph_sha256",
                    "bundle_sha256",
                }
            ),
            pointer,
        )
        workflow_id = _workflow_catalog_v4_text(entry["workflow_id"], f"{pointer}/workflow_id")
        workflow_version = _workflow_catalog_v4_integer(
            entry["workflow_version"], f"{pointer}/workflow_version"
        )
        if (workflow_id, workflow_version) not in {
            ("full", 4),
            ("lite", 4),
        }:
            raise _workflow_catalog_v4_error(
                "WORKFLOW_CATALOG_INVENTORY_INVALID",
                "catalog entry is not full@4 or lite@4",
                pointer=pointer,
            )
        bundle_schema = _workflow_catalog_v4_integer(
            entry["bundle_schema_version"],
            f"{pointer}/bundle_schema_version",
        )
        if bundle_schema not in SUPPORTED_BUNDLE_SCHEMA_VERSIONS:
            raise _workflow_catalog_v4_error(
                "WORKFLOW_BUNDLE_SCHEMA_UNSUPPORTED",
                "bundle schema is unsupported",
                pointer=f"{pointer}/bundle_schema_version",
            )
        relative_root = _workflow_catalog_v4_text(entry["root"], f"{pointer}/root")
        expected_root = f"bundles/{workflow_id}-v4"
        if relative_root != expected_root:
            raise _workflow_catalog_v4_error(
                "WORKFLOW_CATALOG_INVENTORY_INVALID",
                "bundle root differs from its direct V4 path",
                pointer=f"{pointer}/root",
            )
        bundle_root = root / relative_root
        graph_relative = _workflow_catalog_v4_text(entry["graph"], f"{pointer}/graph")
        file_values = _workflow_catalog_v4_array(entry["files"], f"{pointer}/files")
        declarations: list[tuple[str, str]] = []
        for file_index, raw_file in enumerate(file_values):
            file_item = _workflow_catalog_v4_object(raw_file, f"{pointer}/files/{file_index}")
            _workflow_catalog_v4_exact_fields(
                file_item,
                frozenset({"path", "kind"}),
                f"{pointer}/files/{file_index}",
            )
            declarations.append(
                (
                    _workflow_catalog_v4_text(
                        file_item["path"],
                        f"{pointer}/files/{file_index}/path",
                    ),
                    _workflow_catalog_v4_text(
                        file_item["kind"],
                        f"{pointer}/files/{file_index}/kind",
                    ),
                )
            )
        if len(declarations) != len(set(declarations)) or set(
            path for path, _kind in declarations
        ) != {
            "workflow.json",
            "schemas/contracts.json",
            "schemas/node-input.json",
            "schemas/node-result.json",
            "playbooks/workflow.md",
        }:
            raise _workflow_catalog_v4_error(
                "WORKFLOW_INVENTORY_MISMATCH",
                "bundle file inventory is not the exact V4 closure",
                pointer=f"{pointer}/files",
            )
        sources = tuple(
            (
                path,
                kind,
                _workflow_catalog_v4_regular_file(bundle_root, path).read_bytes(),
            )
            for path, kind in declarations
        )
        graph_path = _workflow_catalog_v4_regular_file(bundle_root, graph_relative)
        graph = _workflow_catalog_v4_parse_json(graph_path, f"{relative_root}/{graph_relative}")
        (
            frozen_graph,
            nodes,
            movement_edges,
            action_edges,
            contracts,
            profiles,
        ) = _workflow_catalog_v4_compile_graph(graph, contract_resolver)
        graph_sha256, bundle_sha256 = _workflow_catalog_v4_identity(
            identity_api,
            graph_source=graph_path.read_bytes(),
            files=sources,
            contracts=contracts,
            resolver=contract_resolver,
        )
        if verify_stored_digests and (
            entry["graph_sha256"] != graph_sha256
            or entry["bundle_sha256"] != bundle_sha256
        ):
            raise _workflow_catalog_v4_error(
                "WORKFLOW_IDENTITY_MISMATCH",
                "stored V4 bundle identity differs from package bytes",
                pointer=pointer,
                expected_graph_sha256=graph_sha256,
                expected_bundle_sha256=bundle_sha256,
            )
        resources = MappingProxyType(
            {path: (kind, source) for path, kind, source in sources}
        )
        repository_orchestration = frozen_graph.get(
            "repository_orchestration"
        )
        bundles[(workflow_id, 4)] = WorkflowBundle(
            workflow_id=workflow_id,
            workflow_version=4,
            bundle_schema_version=bundle_schema,
            graph_sha256=graph_sha256,
            bundle_sha256=bundle_sha256,
            root=bundle_root,
            graph=frozen_graph,
            resources=resources,
            nodes=nodes,
            edges=movement_edges,
            action_edges=action_edges,
            contracts=contracts,
            execution_profiles=profiles,
            repository_orchestration=(
                repository_orchestration
                if isinstance(repository_orchestration, Mapping)
                else None
            ),
            active_profiles=(),
        )
    if set(bundles) != {("full", 4), ("lite", 4)}:
        raise WorkflowCatalogError(
            "WORKFLOW_CATALOG_INVENTORY_INVALID",
            "catalog does not contain exact full@4 and lite@4 identities",
        )
    activation = _workflow_catalog_v4_parse_json(
        _workflow_catalog_v4_regular_file(root, "activation.json"), "activation.json"
    )
    _workflow_catalog_v4_exact_fields(activation, frozenset({"schema", "profiles"}), "/")
    if activation.get("schema") != ACTIVATION_SCHEMA:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_ACTIVATION_SCHEMA_UNSUPPORTED",
            "activation schema is unsupported",
            pointer="/schema",
        )
    raw_profiles = _workflow_catalog_v4_array(activation.get("profiles"), "/profiles")
    if len(raw_profiles) != 3:
        raise _workflow_catalog_v4_error(
            "WORKFLOW_ACTIVATION_INVALID",
            "activation must contain exactly three profiles",
            pointer="/profiles",
        )
    activations: list[Mapping[str, object]] = []
    observed: set[tuple[str, str]] = set()
    for index, raw_profile in enumerate(raw_profiles):
        pointer = f"/profiles/{index}"
        profile = _workflow_catalog_v4_object(raw_profile, pointer)
        _workflow_catalog_v4_exact_fields(
            profile,
            frozenset(
                {
                    "workflow_id",
                    "workflow_version",
                    "bundle_sha256",
                    "execution_profile",
                    "active",
                    "required_suites",
                }
            ),
            pointer,
        )
        workflow_id = _workflow_catalog_v4_text(
            profile["workflow_id"], f"{pointer}/workflow_id"
        )
        execution_profile = _workflow_catalog_v4_text(
            profile["execution_profile"], f"{pointer}/execution_profile"
        )
        key = (workflow_id, execution_profile)
        expected_suites = V4_PROFILE_SUITES.get(key)
        bundle = bundles.get((workflow_id, 4))
        if (
            expected_suites is None
            or bundle is None
            or profile.get("workflow_version") != 4
            or profile.get("bundle_sha256") != bundle.bundle_sha256
            or profile.get("active") is not True
            or profile.get("required_suites") != list(expected_suites)
            or key in observed
        ):
            raise _workflow_catalog_v4_error(
                "WORKFLOW_ACTIVATION_INVALID",
                "activation profile differs from the exact V4 contract",
                pointer=pointer,
            )
        observed.add(key)
        activations.append(_workflow_catalog_v4_freeze(profile))  # type: ignore[arg-type]
    if observed != set(V4_PROFILE_SUITES):
        raise WorkflowCatalogError(
            "WORKFLOW_ACTIVATION_INVALID",
            "activation profile set is incomplete",
        )
    for key, bundle in tuple(bundles.items()):
        active_profiles = tuple(
            profile
            for workflow_id, profile in V4_PROFILE_SUITES
            if workflow_id == bundle.workflow_id
        )
        bundles[key] = WorkflowBundle(
            **{
                **bundle.__dict__,
                "active_profiles": active_profiles,
            }
        )
    identities = {bundle.bundle_sha256: bundle for bundle in bundles.values()}
    if len(identities) != 2:
        raise WorkflowCatalogError(
            "WORKFLOW_IDENTITY_COLLISION",
            "V4 bundle identities must be unique",
        )
    return WorkflowCatalog(
        bundles=MappingProxyType(dict(bundles)),
        bundles_by_identity=MappingProxyType(identities),
        activations=tuple(activations),
    )


def expected_workflow_catalog_identities(
    workflows_root: Path | str,
    *,
    contract_resolver: object,
    identity_api: object,
) -> tuple[Mapping[str, object], ...]:
    loaded = _workflow_catalog_v4_load(
        workflows_root,
        contract_resolver=contract_resolver,
        identity_api=identity_api,
        verify_stored_digests=False,
    )
    return tuple(
        MappingProxyType(
            {
                "workflow_id": bundle.workflow_id,
                "workflow_version": bundle.workflow_version,
                "graph_sha256": bundle.graph_sha256,
                "bundle_sha256": bundle.bundle_sha256,
            }
        )
        for bundle in loaded.bundles.values()
    )


def load_workflow_catalog(
    workflows_root: Path | str,
    *,
    contract_resolver: object,
    identity_api: object,
) -> WorkflowCatalog:
    return _workflow_catalog_v4_load(
        workflows_root,
        contract_resolver=contract_resolver,
        identity_api=identity_api,
        verify_stored_digests=True,
    )


__all__ = [
    "ACTIVATION_SCHEMA",
    "BUNDLE_IDENTITY_CONTRACT",
    "CATALOG_SCHEMA",
    "ContractReference",
    "SUPPORTED_BUNDLE_SCHEMA_VERSIONS",
    "StaticContractResolver",
    "V4_HANDLER_CLOSURE_ROLES",
    "V4_PROFILE_SUITES",
    "WORKFLOW_SCHEMA",
    "WorkflowBundle",
    "WorkflowCatalog",
    "WorkflowCatalogError",
    "expected_workflow_catalog_identities",
    "load_workflow_catalog",
]
