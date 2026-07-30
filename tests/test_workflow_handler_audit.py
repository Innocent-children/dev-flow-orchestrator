from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
import uuid
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Callable, Optional
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HANDLERS_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "workflow_handlers.py"
)
BUILTIN_HANDLERS_PATH = (
    ROOT
    / "scripts"
    / "dev_flow_parts"
    / "workflow_builtin_handlers.py"
)
REGISTRY_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "workflow_registry.py"
)
IDENTITY_PATH = ROOT / "scripts" / "workflow_bundle_identity.py"
DEV_FLOW_PATH = ROOT / "scripts" / "dev_flow.py"
CATALOG_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "workflow_catalog.py"
)


def load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_shared_runtime_without_initialization(
    name: str,
) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(DEV_FLOW_PATH)
    sys.modules[name] = module
    loader_tree = ast.parse(
        DEV_FLOW_PATH.read_text(encoding="utf-8"),
        filename=str(DEV_FLOW_PATH),
    )
    assignment = next(
        node
        for node in loader_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_DEV_FLOW_PART_NAMES"
            for target in node.targets
        )
    )
    part_names = ast.literal_eval(assignment.value)
    paths = (IDENTITY_PATH,) + tuple(
        ROOT / "scripts" / "dev_flow_parts" / name
        for name in part_names
    )
    for path in paths:
        exec(
            compile(path.read_bytes(), str(path), "exec"),
            vars(module),
            vars(module),
        )
    return module


handlers = load_module("workflow_handler_audit_runtime", HANDLERS_PATH)
builtin_handlers = load_module(
    "workflow_builtin_handler_runtime", BUILTIN_HANDLERS_PATH
)
registry = load_module("workflow_handler_audit_registry", REGISTRY_PATH)
identity = load_module("workflow_handler_audit_identity", IDENTITY_PATH)
dev_flow = load_shared_runtime_without_initialization(
    "workflow_handler_audit_dev_flow"
)


EXPECTED_IDS = {
    "commands": {
        "command.action-recovery-apply/v1",
        "command.action-recovery-inspect/v1",
        "command.action-recovery-preview/v1",
        "command.approve/v1",
        "command.baseline/v1",
        "command.cancel/v1",
        "command.list/v1",
        "command.manager-authorize/v1",
        "command.manager-revoke/v1",
        "command.preflight/v1",
        "command.prepare-workspace/v1",
        "command.record-artifact/v1",
        "command.record-index/v1",
        "command.record-test/v1",
        "command.recover-atomic-write/v1",
        "command.recover-quarantine/v1",
        "command.review-snapshot/v1",
        "command.scope/v1",
        "command.set-route/v1",
        "command.show/v1",
        "command.start/v1",
        "command.transition/v1",
    },
    "guards": {
        "guard.baseline-current/v1",
        "guard.blocked-resume/v1",
        "guard.index-current/v1",
        "guard.lite-approved/v1",
        "guard.lite-risk-safe/v1",
        "guard.manager-registry-action/v1",
        "guard.multi-repository-barrier-current/v1",
        "guard.multi-repository-cancellation-quiesced/v1",
        "guard.multi-repository-integration-current/v1",
        "guard.multi-repository-review-current/v1",
        "guard.note-required/v1",
        "guard.plan-current/v1",
        "guard.preflight-current/v1",
        "guard.review-approved/v1",
        "guard.review-current/v1",
        "guard.route-approved/v1",
        "guard.test-current/v1",
        "guard.workspace-indexes-current/v1",
        "guard.workspace-ready/v1",
    },
    "reducers": {
        "reducer.action-outcome/v1",
        "reducer.block/v1",
        "reducer.cancel/v1",
        "reducer.impact-reassess/v1",
        "reducer.invalidate-plan/v1",
        "reducer.invalidate-review/v1",
        "reducer.manager-registry-action/v1",
        "reducer.resume/v1",
        "reducer.status/v1",
        "reducer.v3-cancel/v1",
        "reducer.v3-impact-reassess/v1",
        "reducer.v3-invalidate-plan/v1",
        "reducer.v3-invalidate-review/v1",
    },
    "gates": {
        "gate.baseline-fetch/v1",
        "gate.impact-degraded/v1",
        "gate.lite/v1",
        "gate.plan/v1",
        "gate.review/v1",
        "gate.route/v1",
        "gate.workspace/v1",
        "gate.baseline-fetch-outcome/v1",
        "gate.impact-degraded-outcome/v1",
        "gate.lite-outcome/v1",
        "gate.plan-outcome/v1",
        "gate.review-outcome/v1",
        "gate.route-outcome/v1",
        "gate.workspace-outcome/v1",
    },
    "executors": {
        "executor.barrier/v1",
        "executor.codex-exec/v1",
        "executor.codex-thread/v1",
        "executor.deterministic/v1",
        "executor.external-tool/v1",
        "executor.human-gate/v1",
        "executor.native-subagents/v1",
        "executor.v4-abandoned/v2",
        "executor.v4-accepted/v2",
        "executor.v4-archive/v2",
        "executor.v4-compensation/v2",
        "executor.v4-containment/v2",
        "executor.v4-control/v2",
        "executor.v4-dispatch/v2",
        "executor.v4-observation/v2",
        "executor.v4-reattachment/v2",
        "executor.v4-settlement/v2",
        "executor.v4-unblock/v2",
        "executor.v4-unresolved/v2",
    },
}


def actual_namespace() -> dict[str, object]:
    return vars(dev_flow)


def empty_manifest(kind: str) -> dict[str, object]:
    return {
        "manifest_version": (
            "dev-flow-handler-registration-manifest/v1"
        ),
        "audit_policy": "dev-flow-handler-audit/v1",
        "registry": kind,
        "implementation_file_sets": {},
        "entries": [],
    }


def synthetic_guard_entry() -> dict[str, object]:
    return {
        "id": "guard.synthetic/v1",
        "contract_id": "dev-flow-guard/v1",
        "authority": ["read-only"],
        "capabilities": [],
        "input_schema_ref": "schema.guard.projection/v1",
        "output_schema_ref": "schema.guard.result/v1",
        "implementation_file_set": "synthetic-v1",
        "symbols": {"evaluator": "guard"},
        "audit": {
            "profile": "pure-v1",
            "allowed_globals": [],
            "allowed_imports": [],
        },
    }


def write_synthetic_package(
    root: Path,
    *,
    source: str = (
        "from __future__ import annotations\n"
        "def guard(projection, capabilities):\n"
        "    return True\n"
    ),
    entry: Optional[dict[str, object]] = None,
    implementation_path: str = "scripts/guard.py",
) -> None:
    runtime = root / "workflows" / "runtime"
    runtime.mkdir(parents=True)
    source_path = root.joinpath(*implementation_path.split("/"))
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(source, encoding="utf-8")
    for kind in ("commands", "guards", "reducers", "gates", "executors"):
        document = empty_manifest(kind)
        if kind == "guards":
            document["implementation_file_sets"] = {
                "synthetic-v1": [
                    {"path": implementation_path, "kind": "T"}
                ]
            }
            document["entries"] = [
                synthetic_guard_entry() if entry is None else entry
            ]
        (runtime / f"{kind}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def synthetic_namespace(root: Path) -> dict[str, object]:
    source_path = root / "scripts" / "guard.py"
    namespace: dict[str, object] = {}
    exec(
        compile(
            source_path.read_bytes(),
            str(source_path.resolve()),
            "exec",
        ),
        namespace,
        namespace,
    )
    return namespace


class WorkflowHandlerAuditTests(unittest.TestCase):
    def test_package_symbol_audit_scans_each_ast_node_once_per_load(
        self,
    ) -> None:
        observed: dict[str, set[int]] = {
            "forbidden": set(),
            "mutation": set(),
            "references": set(),
        }

        def once(
            label: str,
            implementation: Callable[[ast.AST], object],
        ) -> Callable[[ast.AST], object]:
            def invoke(node: ast.AST) -> object:
                identity = id(node)
                self.assertNotIn(identity, observed[label])
                observed[label].add(identity)
                return implementation(node)

            return invoke

        with (
            mock.patch.object(
                handlers,
                "_workflow_handlers_forbidden_operation",
                side_effect=once(
                    "forbidden",
                    handlers._workflow_handlers_forbidden_operation,
                ),
            ),
            mock.patch.object(
                handlers,
                "_workflow_handlers_input_mutation",
                side_effect=once(
                    "mutation",
                    handlers._workflow_handlers_input_mutation,
                ),
            ),
            mock.patch.object(
                handlers,
                "_workflow_handlers_global_references",
                side_effect=once(
                    "references",
                    handlers._workflow_handlers_global_references,
                ),
            ),
        ):
            manifests = handlers.load_package_handler_manifests(
                package_root=ROOT,
                namespace=actual_namespace(),
            )

        self.assertEqual(
            {manifest.registry_kind for manifest in manifests},
            set(EXPECTED_IDS),
        )
        self.assertTrue(all(observed.values()))

    def test_package_inventory_matches_catalog_contract_ids(self) -> None:
        manifests = handlers.load_package_handler_manifests(
            package_root=ROOT,
            namespace=actual_namespace(),
        )

        self.assertEqual(
            {item.registry_kind for item in manifests},
            set(EXPECTED_IDS),
        )
        for manifest in manifests:
            with self.subTest(registry=manifest.registry_kind):
                self.assertEqual(
                    {entry.handler_id for entry in manifest.entries},
                    EXPECTED_IDS[manifest.registry_kind],
                )
                for entry in manifest.entries:
                    self.assertEqual(
                        len(entry.implementation_sha256), 64
                    )
                    self.assertTrue(entry.implementation_files)
                    self.assertTrue(
                        all(
                            item.kind in {"J", "T", "B"}
                            for item in entry.implementation_files
                        )
                    )
                    with self.assertRaises(TypeError):
                        entry.symbols["module"] = "forbidden"

        entries_by_id = {
            entry.handler_id: entry
            for manifest in manifests
            for entry in manifest.entries
        }
        for entry in entries_by_id.values():
            paths = {item.path for item in entry.implementation_files}
            self.assertNotIn("scripts/dev_flow.py", paths)
            if not entry.handler_id.startswith("executor.v4-"):
                self.assertNotIn(
                    "scripts/dev_flow_parts/workflow_catalog.py", paths
                )
                self.assertNotIn(
                    "scripts/dev_flow_parts/workflow_registry.py", paths
                )
        v4_executor = entries_by_id["executor.v4-unresolved/v2"]
        v4_paths = {
            item.path for item in v4_executor.implementation_files
        }
        self.assertTrue(
            {
                "scripts/dev_flow_parts/workflow_action_reconciliation.py",
                "scripts/dev_flow_parts/workflow_action_transaction.py",
                "scripts/dev_flow_parts/workflow_state.py",
                "scripts/dev_flow_parts/workflow_v4_handlers.py",
                "workflows/runtime/executors.json",
            }.issubset(v4_paths)
        )
        self.assertNotIn(
            "scripts/dev_flow_parts/runtime_adapters.py", v4_paths
        )
        self.assertEqual(
            v4_executor.semantic_roots,
            (
                "_manager_default_actions",
                "execute_v3_workflow_action_transaction",
                "install_v4_runtime_policy",
                "reconcile_v3_workflow_action_quarantine",
                "recover_v3_workflow_action_transaction",
            ),
        )
        self.assertEqual(
            {
                item.path
                for item in entries_by_id[
                    "command.recover-atomic-write/v1"
                ].implementation_files
            },
            {
                "scripts/dev_flow_parts/cli.py",
                "scripts/dev_flow_parts/commands.py",
                "scripts/dev_flow_parts/core.py",
                "scripts/dev_flow_parts/git.py",
                "scripts/dev_flow_parts/mutation.py",
            },
        )
        for handler_id in (
            "guard.note-required/v1",
            "reducer.invalidate-plan/v1",
            "executor.deterministic/v1",
        ):
            self.assertEqual(
                [
                    item.path
                    for item in entries_by_id[
                        handler_id
                    ].implementation_files
                ],
                [
                    "scripts/dev_flow_parts/"
                    "workflow_builtin_handlers.py"
                ],
            )
        for handler_id in (
            "reducer.v3-cancel/v1",
            "reducer.v3-impact-reassess/v1",
            "reducer.v3-invalidate-plan/v1",
            "reducer.v3-invalidate-review/v1",
            "gate.baseline-fetch-outcome/v1",
            "gate.impact-degraded-outcome/v1",
            "gate.lite-outcome/v1",
            "gate.plan-outcome/v1",
            "gate.review-outcome/v1",
            "gate.route-outcome/v1",
            "gate.workspace-outcome/v1",
        ):
            self.assertEqual(
                [
                    item.path
                    for item in entries_by_id[
                        handler_id
                    ].implementation_files
                ],
                [
                    "scripts/dev_flow_parts/"
                    "workflow_v3_handlers.py"
                ],
            )
        multi_repository_guard_ids = {
            "guard.multi-repository-barrier-current/v1",
            "guard.multi-repository-cancellation-quiesced/v1",
            "guard.multi-repository-integration-current/v1",
            "guard.multi-repository-review-current/v1",
        }
        self.assertEqual(
            {
                entries_by_id[handler_id].symbols["evaluator"]
                for handler_id in multi_repository_guard_ids
            },
            {"_workflow_handlers_guard_multi_repository_authority"},
        )

        commands = next(
            item for item in manifests if item.registry_kind == "commands"
        )
        runtime = dev_flow.RuntimeRegistries()
        dev_flow.initialize_package_handler_registries(
            registries=runtime,
            namespace=actual_namespace(),
            package_root=ROOT,
        )
        parser = dev_flow._build_parser_from_command_registry(
            runtime.commands
        )
        subparser_action = next(
            action
            for action in parser._actions
            if isinstance(action, dev_flow.argparse._SubParsersAction)
        )
        self.assertEqual(
            {entry.command for entry in commands.entries},
            set(subparser_action.choices),
        )
        self.assertEqual(
            {
                entry.symbols["handler"]
                for entry in commands.entries
            },
            {
                getattr(subparser_action.choices[name], "_defaults")[
                    "handler"
                ].__name__
                for name in subparser_action.choices
            },
        )
        self.assertEqual(
            {
                entry.symbols["parser_factory"]
                for entry in commands.entries
            },
            {
                f"_register_{entry.command.replace('-', '_')}_parser"
                for entry in commands.entries
            },
        )
        self.assertEqual(
            [
                entry.command
                for entry in sorted(
                    commands.entries,
                    key=lambda item: item.parser_order,
                )
            ],
            list(subparser_action.choices),
        )

    def test_initialization_seals_all_registries_and_resolver_binds_bytes(
        self,
    ) -> None:
        namespace = actual_namespace()
        runtime = dev_flow.RuntimeRegistries()
        manifests = handlers.initialize_package_handler_registries(
            registries=runtime,
            namespace=namespace,
            package_root=ROOT,
        )

        self.assertTrue(runtime.sealed)
        self.assertEqual(
            [len(item.entries) for item in runtime.all()],
            [
                len(EXPECTED_IDS[item.name])
                for item in runtime.all()
            ],
        )
        resolver = handlers.PackageHandlerResolver(
            runtime, manifests, ROOT, identity
        )
        original_guard = namespace["_guard_note_required"]
        resolved = resolver.resolve(
            "guards", "guard.note-required/v1", "v1"
        )
        self.assertEqual(
            resolved.evaluator_symbol, "_guard_note_required"
        )
        namespace["_guard_note_required"] = lambda *_: None
        try:
            self.assertIs(
                resolver.resolve_callable(
                    "guards",
                    "guard.note-required/v1",
                    "v1",
                    "evaluator",
                ),
                original_guard,
            )
        finally:
            namespace["_guard_note_required"] = original_guard

        read_query = lambda projection: projection
        membrane = resolver.capability_membrane(
            "guards",
            "guard.baseline-current/v1",
            "v1",
            queries={
                "legacy.kernel-evidence-read": read_query
            },
        )
        self.assertEqual(
            membrane.available_queries,
            ("legacy.kernel-evidence-read",),
        )
        with self.assertRaises(
            handlers.WorkflowHandlerAuditError
        ) as raised:
            resolver.capability_membrane(
                "guards",
                "guard.baseline-current/v1",
                "v1",
            )
        self.assertEqual(
            raised.exception.code,
            "HANDLER_CAPABILITY_BINDING_MISMATCH",
        )
        reducer_membrane = resolver.capability_membrane(
            "reducers", "reducer.status/v1", "v1"
        )
        self.assertIsInstance(
            reducer_membrane, handlers.ReducerCapabilities
        )
        identity_handlers = resolver.identity_handlers(
            (
                types.SimpleNamespace(
                    registry="guards",
                    identifier="guard.note-required/v1",
                    version="v1",
                ),
                types.SimpleNamespace(
                    registry="reducers",
                    identifier="reducer.invalidate-plan/v1",
                    version="v1",
                ),
            )
        )
        self.assertEqual(
            [item.handler_id for item in identity_handlers],
            [
                "guard.note-required/v1",
                "reducer.invalidate-plan/v1",
            ],
        )
        for item in identity_handlers:
            for implementation_file in item.files:
                self.assertEqual(
                    implementation_file.source,
                    (ROOT / implementation_file.path).read_bytes(),
                )
        reachable: dict[
            tuple[str, str, str], types.SimpleNamespace
        ] = {}
        for graph_path in (
            ROOT / "workflows" / "bundles"
        ).glob("*/workflow.json"):
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            for contract in graph["contracts"]:
                key = (
                    contract["registry"],
                    contract["id"],
                    contract["version"],
                )
                reachable[key] = types.SimpleNamespace(
                    registry=key[0],
                    identifier=key[1],
                    version=key[2],
                )
                resolver.resolve(*key)
        reachable_identities = resolver.identity_handlers(
            tuple(reachable.values())
        )
        self.assertEqual(
            {item.handler_id for item in reachable_identities},
            {identifier for _registry, identifier, _version in reachable},
        )
        with self.assertRaises(
            dev_flow.WorkflowRegistryError
        ) as raised:
            runtime.guards.register(resolved)
        self.assertEqual(raised.exception.code, "REGISTRY_SEALED")
        self.assertFalse(hasattr(handlers, "unseal"))
        self.assertFalse(hasattr(handlers, "reset"))

    def test_cli_parser_generation_fails_closed_on_registration_drift(
        self,
    ) -> None:
        def handler(_arguments: object) -> dict[str, object]:
            return {"ok": True}

        def valid_factory(
            subparsers: object,
            registration: object,
            registered_handler: object,
        ) -> None:
            parser = subparsers.add_parser(
                registration.command,
                help="synthetic registered command",
            )
            parser.add_argument(
                "--mode",
                choices=("safe", "fast"),
                default="safe",
                help="execution mode",
            )
            parser.set_defaults(handler=registered_handler)

        def wrong_spelling_factory(
            subparsers: object,
            _registration: object,
            registered_handler: object,
        ) -> None:
            parser = subparsers.add_parser("unregistered")
            parser.set_defaults(handler=registered_handler)

        def registration(
            identifier: str,
            command: str,
            parser_order: int,
            parser_factory_symbol: str,
        ) -> object:
            return dev_flow.CommandRegistration(
                identifier=identifier,
                contract_version="v1",
                implementation_sha256="a" * 64,
                authority=("controller-read",),
                capabilities=(),
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                implementation_files=(
                    "scripts/dev_flow_parts/cli.py",
                ),
                command=command,
                action_id=f"synthetic.{command}",
                parser_order=parser_order,
                parser_factory_symbol=parser_factory_symbol,
                handler_symbol="handler",
            )

        commands = dev_flow.CommandRegistry()
        commands.register(
            registration(
                "command.synthetic",
                "synthetic",
                0,
                "valid_factory",
            )
        )
        commands.seal(
            {
                "valid_factory": valid_factory,
                "handler": handler,
            }
        )
        parser = dev_flow._build_parser_from_command_registry(commands)
        parsed = parser.parse_args(["synthetic", "--mode", "fast"])
        self.assertEqual(parsed.command, "synthetic")
        self.assertEqual(parsed.mode, "fast")
        self.assertIs(parsed.handler, handler)

        duplicate_orders = dev_flow.CommandRegistry()
        duplicate_orders.register(
            registration(
                "command.alpha", "alpha", 0, "valid_factory"
            )
        )
        duplicate_orders.register(
            registration(
                "command.beta", "beta", 0, "valid_factory"
            )
        )
        duplicate_orders.seal(
            {
                "valid_factory": valid_factory,
                "handler": handler,
            }
        )
        with self.assertRaises(
            dev_flow.WorkflowRegistryError
        ) as raised:
            dev_flow._build_parser_from_command_registry(
                duplicate_orders
            )
        self.assertEqual(
            raised.exception.code, "REGISTRY_PARSER_ORDER_INVALID"
        )

        wrong_spelling = dev_flow.CommandRegistry()
        wrong_spelling.register(
            registration(
                "command.synthetic",
                "synthetic",
                0,
                "wrong_spelling_factory",
            )
        )
        wrong_spelling.seal(
            {
                "wrong_spelling_factory": wrong_spelling_factory,
                "handler": handler,
            }
        )
        with self.assertRaises(
            dev_flow.WorkflowRegistryError
        ) as raised:
            dev_flow._build_parser_from_command_registry(wrong_spelling)
        self.assertEqual(
            raised.exception.code, "REGISTRY_PARSER_FACTORY_INVALID"
        )

    def test_command_manifest_rejects_ambiguous_parser_metadata(
        self,
    ) -> None:
        def entry(
            command: str,
            parser_order: int,
            parser_factory: str,
        ) -> object:
            return types.SimpleNamespace(
                command=command,
                parser_order=parser_order,
                symbols={"parser_factory": parser_factory},
            )

        cases = (
            (
                (
                    entry("alpha", 0, "factory_alpha"),
                    entry("alpha", 1, "factory_beta"),
                ),
                "duplicate_commands",
            ),
            (
                (
                    entry("alpha", 0, "factory_alpha"),
                    entry("beta", 0, "factory_beta"),
                ),
                "duplicate_parser_orders",
            ),
            (
                (
                    entry("alpha", 0, "factory"),
                    entry("beta", 1, "factory"),
                ),
                "duplicate_parser_factories",
            ),
            (
                (
                    entry("alpha", 0, "factory_alpha"),
                    entry("beta", 2, "factory_beta"),
                ),
                "parser_orders",
            ),
        )
        for entries, detail in cases:
            with self.subTest(detail=detail), self.assertRaises(
                handlers.WorkflowHandlerAuditError
            ) as raised:
                handlers._workflow_handlers_validate_command_parser_registrations(
                    entries
                )
            self.assertEqual(
                raised.exception.code,
                "HANDLER_COMMAND_PARSER_REGISTRATION_INVALID",
            )
            self.assertTrue(raised.exception.details[detail])

    def test_shared_namespace_exec_order_cannot_corrupt_handler_audit(
        self,
    ) -> None:
        module_name = f"workflow_shared_{uuid.uuid4().hex}"
        shared = load_shared_runtime_without_initialization(module_name)
        try:
            for path in (
                REGISTRY_PATH,
                HANDLERS_PATH,
                BUILTIN_HANDLERS_PATH,
                CATALOG_PATH,
            ):
                source = path.read_bytes()
                exec(
                    compile(source, str(path), "exec"),
                    vars(shared),
                    vars(shared),
                )

            first = shared.load_package_handler_manifests(
                package_root=ROOT,
                namespace=vars(shared),
            )
            second = shared.load_package_handler_manifests(
                package_root=ROOT,
                namespace=vars(shared),
            )
            self.assertEqual(
                [
                    (item.registry_kind, len(item.entries))
                    for item in first
                ],
                [
                    (item.registry_kind, len(item.entries))
                    for item in second
                ],
            )
            runtime = shared.RuntimeRegistries()
            shared.initialize_package_handler_registries(
                registries=runtime,
                namespace=vars(shared),
                package_root=ROOT,
            )
            resolver = shared.PackageHandlerResolver(
                runtime, second, ROOT, shared
            )
            handler_values = resolver.identity_handlers(
                (
                    shared.ContractReference(
                        "guards", "guard.note-required/v1", "v1"
                    ),
                )
            )
            self.assertEqual(
                handler_values[0].handler_id,
                "guard.note-required/v1",
            )
        finally:
            sys.modules.pop(module_name, None)

    def test_private_shared_globals_use_component_prefix(self) -> None:
        stable_bindings = {
            "_disabled_executor_dispatch",
            "_guard_blocked_resume_target",
            "_guard_note_required",
            "_reduce_action_outcome",
            "_reduce_block",
            "_reduce_cancel",
            "_reduce_impact_reassess",
            "_reduce_invalidate_plan",
            "_reduce_invalidate_review",
            "_reduce_resume",
            "_reduce_status",
        }
        unexpected: list[str] = []
        for path in (HANDLERS_PATH, BUILTIN_HANDLERS_PATH):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                names: list[str] = []
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names = [node.name]
                elif isinstance(node, ast.Assign):
                    names = [
                        target.id
                        for target in node.targets
                        if isinstance(target, ast.Name)
                    ]
                elif isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name
                ):
                    names = [node.target.id]
                for name in names:
                    if (
                        name.startswith("_")
                        and name not in stable_bindings
                        and not name.startswith("_workflow_handlers_")
                    ):
                        unexpected.append(name)
        self.assertEqual(unexpected, [])

    def test_capability_membranes_are_immutable_and_minimal(self) -> None:
        calls: list[object] = []
        queries = {
            "legacy.kernel-evidence-read": (
                lambda projection: calls.append(projection) or {"ok": True}
            )
        }
        capabilities = handlers.GuardCapabilities(_queries=queries)
        queries.clear()

        self.assertEqual(
            capabilities.available_queries,
            ("legacy.kernel-evidence-read",),
        )
        self.assertEqual(
            capabilities.query(
                "legacy.kernel-evidence-read", {"revision": 1}
            ),
            {"ok": True},
        )
        self.assertEqual(calls, [{"revision": 1}])
        self.assertFalse(hasattr(capabilities, "__dict__"))
        with self.assertRaises(TypeError):
            capabilities._queries["network"] = lambda value: value
        with self.assertRaises(FrozenInstanceError):
            capabilities.contract_version = "v2"
        with self.assertRaises(
            handlers.WorkflowHandlerAuditError
        ) as raised:
            capabilities.query("network", {})
        self.assertEqual(
            raised.exception.code, "HANDLER_CAPABILITY_UNDECLARED"
        )

        reducer_capabilities = handlers.ReducerCapabilities()
        self.assertFalse(hasattr(reducer_capabilities, "__dict__"))
        self.assertFalse(hasattr(reducer_capabilities, "query"))
        self.assertFalse(hasattr(reducer_capabilities, "filesystem"))
        self.assertFalse(hasattr(reducer_capabilities, "git"))
        self.assertFalse(hasattr(reducer_capabilities, "process"))
        self.assertFalse(hasattr(reducer_capabilities, "registry"))
        self.assertFalse(hasattr(reducer_capabilities, "commit"))

    def test_shadow_invalidation_reducers_do_not_mutate_projection(
        self,
    ) -> None:
        projection = {"target_status": "PLANNING"}
        original = dict(projection)
        result = builtin_handlers._reduce_invalidate_plan(
            projection, handlers.ReducerCapabilities()
        )

        self.assertEqual(projection, original)
        self.assertEqual(result["set"], {"/review_snapshots": []})
        self.assertEqual(
            result["remove"],
            ["/approvals/plan", "/approvals/review"],
        )
        reassess = builtin_handlers._reduce_impact_reassess(
            {}, handlers.ReducerCapabilities()
        )
        self.assertEqual(reassess["set"]["/status"], "INDEXED")
        self.assertIn(
            "retire-current-workspaces", reassess["operations"]
        )

    def test_strict_manifest_rejects_unknown_fields_paths_and_symbols(
        self,
    ) -> None:
        cases: list[
            tuple[
                str,
                Callable[[dict[str, object]], None],
                str,
                bool,
            ]
        ] = [
            (
                "unknown field",
                lambda entry: entry.__setitem__(
                    "module", "target_repo.handler"
                ),
                "HANDLER_MANIFEST_FIELDS_INVALID",
                True,
            ),
            (
                "dotted symbol",
                lambda entry: entry.__setitem__(
                    "symbols", {"evaluator": "module.guard"}
                ),
                "HANDLER_SYMBOL_INVALID",
                True,
            ),
            (
                "missing symbol",
                lambda _entry: None,
                "HANDLER_SYMBOL_MISSING",
                False,
            ),
            (
                "glob",
                lambda entry: entry.__setitem__(
                    "implementation_file_set", "synthetic-v1"
                ),
                "HANDLER_IMPLEMENTATION_PATH_INVALID",
                True,
            ),
            (
                "traversal",
                lambda entry: entry.__setitem__(
                    "implementation_file_set", "synthetic-v1"
                ),
                "HANDLER_IMPLEMENTATION_PATH_INVALID",
                True,
            ),
        ]
        for name, mutate, expected_code, has_symbol in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                entry = synthetic_guard_entry()
                mutate(entry)
                implementation_path = "scripts/guard.py"
                if name == "glob":
                    implementation_path = "scripts/*.py"
                elif name == "traversal":
                    implementation_path = "../guard.py"
                if name in {"glob", "traversal"}:
                    # The unsafe declaration is rejected before the source is read.
                    runtime = root / "workflows" / "runtime"
                    runtime.mkdir(parents=True)
                    for kind in (
                        "commands",
                        "guards",
                        "reducers",
                        "gates",
                        "executors",
                    ):
                        document = empty_manifest(kind)
                        if kind == "guards":
                            document["implementation_file_sets"] = {
                                "synthetic-v1": [
                                    {
                                        "path": implementation_path,
                                        "kind": "T",
                                    }
                                ]
                            }
                            document["entries"] = [entry]
                        (runtime / f"{kind}.json").write_text(
                            json.dumps(document), encoding="utf-8"
                        )
                else:
                    write_synthetic_package(root, entry=entry)
                if name in {"glob", "traversal"}:
                    namespace = {"guard": lambda *_args: True}
                elif has_symbol:
                    namespace = synthetic_namespace(root)
                else:
                    namespace = {}
                with self.assertRaises(
                    handlers.WorkflowHandlerAuditError
                ) as raised:
                    handlers.load_package_handler_manifests(
                        package_root=root, namespace=namespace
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_missing_file_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_synthetic_package(root)
            (root / "scripts" / "guard.py").unlink()
            with self.assertRaises(
                handlers.WorkflowHandlerAuditError
            ) as raised:
                handlers.load_package_handler_manifests(
                    package_root=root, namespace={}
                )
            self.assertEqual(
                raised.exception.code,
                "HANDLER_IMPLEMENTATION_FILE_MISSING",
            )

        if hasattr(os, "symlink"):
            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                write_synthetic_package(root)
                source = root / "outside.py"
                source.write_text(
                    "def guard(projection, capabilities): return True\n",
                    encoding="utf-8",
                )
                declared = root / "scripts" / "guard.py"
                declared.unlink()
                declared.symlink_to(source)
                with self.assertRaises(
                    handlers.WorkflowHandlerAuditError
                ) as raised:
                    handlers.load_package_handler_manifests(
                        package_root=root,
                        namespace=synthetic_namespace(root),
                    )
                self.assertEqual(
                    raised.exception.code,
                    "HANDLER_IMPLEMENTATION_FILE_INVALID",
                )

            with tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                write_synthetic_package(root)
                scripts = root / "scripts"
                real_scripts = root / "real-scripts"
                scripts.rename(real_scripts)
                scripts.symlink_to(real_scripts, target_is_directory=True)
                with self.assertRaises(
                    handlers.WorkflowHandlerAuditError
                ) as raised:
                    handlers.load_package_handler_manifests(
                        package_root=root,
                        namespace={},
                    )
                self.assertEqual(
                    raised.exception.code,
                    "HANDLER_IMPLEMENTATION_FILE_INVALID",
                )

    def test_guard_authority_capability_global_and_import_audit(self) -> None:
        cases = (
            (
                "authority",
                {"authority": ["filesystem-write"]},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities): return True\n"
                ),
                "HANDLER_AUTHORITY_FORBIDDEN",
            ),
            (
                "capability",
                {"capabilities": ["network"]},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities): return True\n"
                ),
                "HANDLER_CAPABILITY_FORBIDDEN",
            ),
            (
                "global",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    return hidden(projection)\n"
                ),
                "HANDLER_GLOBAL_UNDECLARED",
            ),
            (
                "comprehension scope",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    [hidden for hidden in ()]\n"
                    "    return hidden(projection)\n"
                ),
                "HANDLER_GLOBAL_UNDECLARED",
            ),
            (
                "forbidden alias",
                {
                    "audit": {
                        "profile": "pure-v1",
                        "allowed_globals": ["write"],
                        "allowed_imports": [],
                    }
                },
                (
                    "from __future__ import annotations\n"
                    "write = open\n"
                    "def guard(projection, capabilities):\n"
                    "    return write\n"
                ),
                "HANDLER_CAPABILITY_REFERENCE_FORBIDDEN",
            ),
            (
                "object setattr",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    object.__setattr__(capabilities, '_queries', {})\n"
                    "    return True\n"
                ),
                "HANDLER_CAPABILITY_REFERENCE_FORBIDDEN",
            ),
            (
                "projection mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    projection['status'] = 'CORRUPTED'\n"
                    "    return True\n"
                ),
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
            ),
            (
                "projection alias mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    child = projection['child']\n"
                    "    alias = child\n"
                    "    alias.clear()\n"
                    "    return True\n"
                ),
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
            ),
            (
                "projection tuple alias mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    alias, unused = (projection['child'], {})\n"
                    "    alias.clear()\n"
                    "    return True\n"
                ),
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
            ),
            (
                "projection conditional alias mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    alias = (projection['a'] if projection.get('x')"
                    " else projection['b'])\n"
                    "    alias.clear()\n"
                    "    return True\n"
                ),
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
            ),
            (
                "projection boolean alias mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    alias = projection.get('a') or projection['b']\n"
                    "    alias.clear()\n"
                    "    return True\n"
                ),
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
            ),
            (
                "projection container retrieval mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    box = (projection['child'],)\n"
                    "    alias = box[0]\n"
                    "    alias.clear()\n"
                    "    return True\n"
                ),
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
            ),
            (
                "projection comprehension retrieval mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    box = [item for item in (projection['child'],)]\n"
                    "    alias = box[0]\n"
                    "    alias.clear()\n"
                    "    return True\n"
                ),
                "HANDLER_INPUT_MUTATION_FORBIDDEN",
            ),
            (
                "projection dunder mutation",
                {},
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    dict.__setitem__(projection, 'x', 1)\n"
                    "    return True\n"
                ),
                "HANDLER_CAPABILITY_REFERENCE_FORBIDDEN",
            ),
            (
                "process import",
                {
                    "audit": {
                        "profile": "pure-v1",
                        "allowed_globals": [],
                        "allowed_imports": ["subprocess"],
                    }
                },
                (
                    "from __future__ import annotations\n"
                    "import subprocess\n"
                    "def guard(projection, capabilities):\n"
                    "    return subprocess.run(['true'])\n"
                ),
                "HANDLER_CAPABILITY_REFERENCE_FORBIDDEN",
            ),
            (
                "environment import",
                {
                    "audit": {
                        "profile": "pure-v1",
                        "allowed_globals": [],
                        "allowed_imports": ["os"],
                    }
                },
                (
                    "from __future__ import annotations\n"
                    "import os\n"
                    "def guard(projection, capabilities):\n"
                    "    return os.getenv('PLUGIN_DATA')\n"
                ),
                "HANDLER_IMPORT_FORBIDDEN",
            ),
        )
        for name, overrides, source, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                entry = synthetic_guard_entry()
                entry.update(overrides)
                write_synthetic_package(
                    root, source=source, entry=entry
                )
                with self.assertRaises(
                    handlers.WorkflowHandlerAuditError
                ) as raised:
                    handlers.load_package_handler_manifests(
                        package_root=root,
                        namespace=synthetic_namespace(root),
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_pure_bindings_require_exact_sync_signature(self) -> None:
        cases = (
            (
                "zero arguments",
                (
                    "from __future__ import annotations\n"
                    "def guard():\n"
                    "    return True\n"
                ),
            ),
            (
                "async",
                (
                    "from __future__ import annotations\n"
                    "async def guard(projection, capabilities):\n"
                    "    return True\n"
                ),
            ),
            (
                "generator",
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    yield True\n"
                ),
            ),
        )
        for name, source in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                write_synthetic_package(root, source=source)
                with self.assertRaises(
                    handlers.WorkflowHandlerAuditError
                ) as raised:
                    handlers.load_package_handler_manifests(
                        package_root=root,
                        namespace=synthetic_namespace(root),
                    )
                self.assertEqual(
                    raised.exception.code,
                    "HANDLER_SYMBOL_CONTRACT_INVALID",
                )

    def test_runtime_binding_must_match_audited_code_and_namespace(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_synthetic_package(root)
            source_path = root / "scripts" / "guard.py"
            forged: dict[str, object] = {}
            exec(
                compile(
                    (
                        "from __future__ import annotations\n"
                        "def guard(projection, capabilities):\n"
                        "    return False\n"
                    ),
                    str(source_path.resolve()),
                    "exec",
                ),
                forged,
                forged,
            )
            with self.assertRaises(
                handlers.WorkflowHandlerAuditError
            ) as raised:
                handlers.load_package_handler_manifests(
                    package_root=root, namespace=forged
                )
            self.assertEqual(
                raised.exception.code,
                "HANDLER_SYMBOL_SOURCE_MISMATCH",
            )

            namespace = synthetic_namespace(root)
            original = namespace["guard"]
            assert isinstance(original, types.FunctionType)
            function_globals: dict[str, object] = {}
            rebound: dict[str, object] = {}
            rebound["guard"] = types.FunctionType(
                original.__code__,
                function_globals,
                name="guard",
            )
            with self.assertRaises(
                handlers.WorkflowHandlerAuditError
            ) as raised:
                handlers.load_package_handler_manifests(
                    package_root=root, namespace=rebound
                )
            self.assertEqual(
                raised.exception.code,
                "HANDLER_SYMBOL_SOURCE_MISMATCH",
            )

    def test_manifest_rejects_non_scalar_unicode_structurally(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_synthetic_package(root)
            path = root / "workflows" / "runtime" / "commands.json"
            document = empty_manifest("commands")
            document["audit_policy"] = "\ud800"
            path.write_text(
                json.dumps(document, ensure_ascii=True),
                encoding="utf-8",
            )
            with self.assertRaises(
                handlers.WorkflowHandlerAuditError
            ) as raised:
                handlers.load_package_handler_manifests(
                    package_root=root,
                    namespace=synthetic_namespace(root),
                )
            self.assertEqual(
                raised.exception.code,
                "HANDLER_MANIFEST_UNICODE_INVALID",
            )

    def test_loader_ignores_environment_entry_points_and_extra_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as package_raw:
            with tempfile.TemporaryDirectory() as external_raw:
                self._assert_loader_ignores_external_discovery(
                    Path(package_raw), Path(external_raw)
                )

    def _assert_loader_ignores_external_discovery(
        self, package_root: Path, external_root: Path
    ) -> None:
        write_synthetic_package(package_root)
        (package_root / "workflows" / "runtime" / "plugin.json").write_text(
            "{malformed", encoding="utf-8"
        )
        (external_root / "guards.json").write_text(
            "{malformed", encoding="utf-8"
        )
        with mock.patch.dict(
            os.environ,
            {
                "PLUGIN_DATA": str(external_root),
                "DEV_FLOW_DATA_DIR": str(external_root),
                "PYTHONPATH": str(external_root),
            },
        ):
            with mock.patch.object(
                importlib.metadata, "entry_points"
            ) as entry_points:
                manifests = handlers.load_package_handler_manifests(
                    package_root=package_root,
                    namespace=synthetic_namespace(package_root),
                )
        entry_points.assert_not_called()
        self.assertEqual(
            sum(len(item.entries) for item in manifests), 1
        )

    def test_implementation_digest_tracks_exact_source_and_resolver_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_synthetic_package(root)
            namespace = synthetic_namespace(root)
            namespace.update(vars(registry))
            first = handlers.load_package_handler_manifests(
                package_root=root, namespace=namespace
            )
            first_digest = next(
                entry.implementation_sha256
                for manifest in first
                for entry in manifest.entries
            )
            runtime = registry.RuntimeRegistries()
            handlers.initialize_package_handler_registries(
                registries=runtime,
                namespace=namespace,
                package_root=root,
            )
            resolver = handlers.PackageHandlerResolver(
                runtime, first, root, identity
            )
            values = resolver.identity_handlers(
                (
                    types.SimpleNamespace(
                        registry="guards",
                        identifier="guard.synthetic/v1",
                        version="v1",
                    ),
                )
            )
            self.assertEqual(
                identity.handler_implementation_sha256(
                    values[0].handler_id,
                    values[0].contract_id,
                    values[0].files,
                ),
                first_digest,
            )
            unrelated = root / "scripts" / "unrelated.py"
            unrelated.write_text("VALUE = 1\n", encoding="utf-8")
            unrelated_first = handlers.load_package_handler_manifests(
                package_root=root, namespace=namespace
            )
            unrelated.write_text("VALUE = 2\n", encoding="utf-8")
            unrelated_second = handlers.load_package_handler_manifests(
                package_root=root, namespace=namespace
            )
            self.assertEqual(
                [
                    entry.implementation_sha256
                    for manifest in unrelated_first
                    for entry in manifest.entries
                ],
                [
                    entry.implementation_sha256
                    for manifest in unrelated_second
                    for entry in manifest.entries
                ],
            )

            (root / "scripts" / "guard.py").write_text(
                (
                    "from __future__ import annotations\n"
                    "def guard(projection, capabilities):\n"
                    "    return False\n"
                ),
                encoding="utf-8",
            )
            namespace = synthetic_namespace(root)
            namespace.update(vars(registry))
            second = handlers.load_package_handler_manifests(
                package_root=root, namespace=namespace
            )
            second_digest = next(
                entry.implementation_sha256
                for manifest in second
                for entry in manifest.entries
            )
            self.assertNotEqual(first_digest, second_digest)
            with self.assertRaises(
                handlers.WorkflowHandlerAuditError
            ) as raised:
                resolver.identity_handlers(
                    (
                        types.SimpleNamespace(
                            registry="guards",
                            identifier="guard.synthetic/v1",
                            version="v1",
                        ),
                    )
                )
            self.assertEqual(
                raised.exception.code,
                "HANDLER_IMPLEMENTATION_IDENTITY_MISMATCH",
            )

    def test_v4_digest_binds_transaction_and_reconciliation_sources(
        self,
    ) -> None:
        manifests = handlers.load_package_handler_manifests(
            package_root=ROOT,
            namespace=actual_namespace(),
        )
        spec = next(
            entry
            for manifest in manifests
            for entry in manifest.entries
            if entry.handler_id == "executor.v4-unresolved/v2"
        )
        files = tuple(
            identity.BundleFile(
                declaration.path,
                declaration.kind,
                (ROOT / declaration.path).read_bytes(),
            )
            for declaration in spec.implementation_files
        )
        self.assertEqual(
            identity.handler_implementation_sha256(
                spec.handler_id, spec.contract_id, files
            ),
            spec.implementation_sha256,
        )
        baseline_bundle = identity.bundle_sha256(
            (),
            (
                identity.HandlerImplementation(
                    spec.handler_id, spec.contract_id, files
                ),
            ),
        )
        for path in (
            "scripts/dev_flow_parts/workflow_action_reconciliation.py",
            "scripts/dev_flow_parts/workflow_action_transaction.py",
        ):
            with self.subTest(path=path):
                changed_files = tuple(
                    identity.BundleFile(
                        item.path,
                        item.kind,
                        (
                            item.source + b"\n# identity drift\n"
                            if item.path == path
                            else item.source
                        ),
                    )
                    for item in files
                )
                self.assertNotEqual(
                    identity.bundle_sha256(
                        (),
                        (
                            identity.HandlerImplementation(
                                spec.handler_id,
                                spec.contract_id,
                                changed_files,
                            ),
                        ),
                    ),
                    baseline_bundle,
                )


if __name__ == "__main__":
    unittest.main()
