from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "workflow_registry.py"
)
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_workflow_registry", REGISTRY_PATH
)
assert SPEC is not None and SPEC.loader is not None
registry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = registry
SPEC.loader.exec_module(registry)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
SCHEMA = {"type": "object", "additionalProperties": False}


def command_registration(
    *,
    identifier: str = "command.show",
    version: str = "v1",
    digest: str = DIGEST_A,
    command: str = "show",
    parser_order: int = 0,
    parser_factory_symbol: str = "_register_show_parser",
) -> object:
    return registry.CommandRegistration(
        identifier=identifier,
        contract_version=version,
        implementation_sha256=digest,
        authority=("read-only",),
        capabilities=(),
        input_schema=SCHEMA,
        output_schema=SCHEMA,
        implementation_files=("scripts/dev_flow_parts/commands.py",),
        command=command,
        action_id="task.show",
        parser_order=parser_order,
        parser_factory_symbol=parser_factory_symbol,
        handler_symbol="command_show",
    )


class WorkflowRegistryTests(unittest.TestCase):
    def test_typed_registry_rejects_wrong_entry_type(self) -> None:
        commands = registry.CommandRegistry()
        guard = registry.GuardRegistration(
            identifier="guard.current",
            contract_version="v1",
            implementation_sha256=DIGEST_A,
            authority=("read-only",),
            capabilities=(),
            input_schema=SCHEMA,
            output_schema=SCHEMA,
            implementation_files=(
                "scripts/dev_flow_parts/review.py",
            ),
            evaluator_symbol="_guard_current",
        )

        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            commands.register(guard)

        self.assertEqual(raised.exception.code, "REGISTRY_TYPE_MISMATCH")
        self.assertEqual(commands.entries, {})

    def test_duplicate_binding_is_deterministic_and_preserves_first(self) -> None:
        commands = registry.CommandRegistry()
        first = commands.register(command_registration())

        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            commands.register(command_registration(digest=DIGEST_B))

        self.assertEqual(raised.exception.code, "REGISTRY_DUPLICATE")
        self.assertIs(
            commands.resolve("command.show", "v1"),
            first,
        )
        self.assertEqual(
            raised.exception.details["existing_implementation_sha256"],
            DIGEST_A,
        )
        self.assertEqual(
            raised.exception.details["received_implementation_sha256"],
            DIGEST_B,
        )

    def test_seal_prevents_registration_removal_and_replacement(self) -> None:
        commands = registry.CommandRegistry()
        commands.register(command_registration())
        commands.seal()

        operations = (
            lambda: commands.register(
                command_registration(identifier="command.list")
            ),
            lambda: commands.remove("command.show", "v1"),
            lambda: commands.replace(
                command_registration(digest=DIGEST_B)
            ),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(
                    registry.WorkflowRegistryError
                ) as raised:
                    operation()
                self.assertEqual(raised.exception.code, "REGISTRY_SEALED")

        self.assertEqual(len(commands.entries), 1)

    def test_entries_and_typed_contracts_are_deeply_immutable(self) -> None:
        commands = registry.CommandRegistry()
        entry = commands.register(
            registry.CommandRegistration(
                identifier="command.show",
                contract_version="v1",
                implementation_sha256=DIGEST_A,
                authority=("read-only",),
                capabilities=(),
                input_schema={
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                    },
                },
                output_schema=SCHEMA,
                implementation_files=(
                    "scripts/dev_flow_parts/commands.py",
                ),
                command="show",
                action_id="task.show",
                parser_order=0,
                parser_factory_symbol="_register_show_parser",
                handler_symbol="command_show",
            )
        )

        with self.assertRaises(TypeError):
            commands.entries[("command.other", "v1")] = entry
        with self.assertRaises(TypeError):
            entry.input_schema["type"] = "array"
        properties = entry.input_schema["properties"]
        with self.assertRaises(TypeError):
            properties["task"] = {"type": "integer"}

    def test_runtime_registries_reject_cross_registry_identity_collision(
        self,
    ) -> None:
        runtime = registry.RuntimeRegistries()
        runtime.commands.register(command_registration())
        guard = registry.GuardRegistration(
            identifier="command.show",
            contract_version="v1",
            implementation_sha256=DIGEST_A,
            authority=("read-only",),
            capabilities=(),
            input_schema=SCHEMA,
            output_schema=SCHEMA,
            implementation_files=(
                "scripts/dev_flow_parts/review.py",
            ),
            evaluator_symbol="_guard_current",
        )

        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            runtime.guards.register(guard)

        self.assertEqual(
            raised.exception.code, "REGISTRY_GLOBAL_DUPLICATE"
        )
        self.assertEqual(runtime.guards.entries, {})

    def test_runtime_seal_is_atomic_from_callers_perspective(self) -> None:
        runtime = registry.RuntimeRegistries()
        runtime.commands.register(command_registration())
        runtime.seal()

        self.assertTrue(runtime.sealed)
        self.assertTrue(all(item.sealed for item in runtime.all()))
        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            runtime.executors.register(
                registry.ExecutorRegistration(
                    identifier="executor.codex",
                    contract_version="v1",
                    implementation_sha256=DIGEST_A,
                    authority=("external-process",),
                    capabilities=(),
                    input_schema=SCHEMA,
                    output_schema=SCHEMA,
                    implementation_files=(
                        "scripts/dev_flow_parts/process.py",
                    ),
                    dispatcher_symbol="_dispatch_codex",
                    effect_classification="external",
                )
            )
        self.assertEqual(raised.exception.code, "REGISTRY_SEALED")

    def test_runtime_seal_freezes_executable_bindings_atomically(
        self,
    ) -> None:
        runtime = registry.RuntimeRegistries()
        runtime.commands.register(command_registration())
        first = object()
        second = object()
        first_handler = lambda: first
        namespace = {
            "_register_show_parser": lambda: None,
            "command_show": first_handler,
        }

        runtime.seal(namespace)
        namespace["command_show"] = lambda: second

        bound = runtime.commands.resolve_callable(
            "command.show", "v1", "handler"
        )
        self.assertIs(bound, first_handler)
        self.assertIs(bound(), first)
        with self.assertRaises(
            registry.WorkflowRegistryError
        ) as raised:
            runtime.seal(namespace)
        self.assertEqual(
            raised.exception.code, "REGISTRY_SET_SEALED"
        )
        self.assertIs(
            runtime.commands.resolve_callable(
                "command.show", "v1", "handler"
            ),
            first_handler,
        )

    def test_binding_failure_leaves_every_runtime_registry_unsealed(
        self,
    ) -> None:
        runtime = registry.RuntimeRegistries()
        runtime.commands.register(command_registration())

        with self.assertRaises(
            registry.WorkflowRegistryError
        ) as raised:
            runtime.seal({"_register_show_parser": lambda: None})

        self.assertEqual(
            raised.exception.code, "REGISTRY_SYMBOL_UNAVAILABLE"
        )
        self.assertFalse(runtime.sealed)
        self.assertTrue(
            all(not item.sealed for item in runtime.all())
        )

    def test_registration_validation_rejects_incomplete_or_unsafe_metadata(
        self,
    ) -> None:
        cases = (
            (
                "Bad ID",
                {"identifier": "Bad ID"},
                "REGISTRY_INVALID_ID",
            ),
            (
                "version",
                {"version": "1"},
                "REGISTRY_INVALID_VERSION",
            ),
            (
                "digest",
                {"digest": "ABC"},
                "REGISTRY_INVALID_DIGEST",
            ),
            (
                "parser order",
                {"parser_order": -1},
                "REGISTRY_INVALID_PARSER_ORDER",
            ),
        )
        for name, overrides, expected_code in cases:
            with self.subTest(name=name):
                with self.assertRaises(
                    registry.WorkflowRegistryError
                ) as raised:
                    command_registration(**overrides)
                self.assertEqual(raised.exception.code, expected_code)

        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            registry.GuardRegistration(
                identifier="guard.current",
                contract_version="v1",
                implementation_sha256=DIGEST_A,
                authority=("filesystem-write",),
                capabilities=(),
                input_schema=SCHEMA,
                output_schema=SCHEMA,
                implementation_files=(
                    "scripts/dev_flow_parts/review.py",
                ),
                evaluator_symbol="_guard_current",
            )
        self.assertEqual(
            raised.exception.code, "REGISTRY_FORBIDDEN_AUTHORITY"
        )

    def test_manifest_is_stable_and_excludes_callables(self) -> None:
        runtime = registry.RuntimeRegistries()
        runtime.commands.register(
            command_registration(identifier="command.zeta")
        )
        runtime.guards.register(
            registry.GuardRegistration(
                identifier="guard.alpha",
                contract_version="v1",
                implementation_sha256=DIGEST_B,
                authority=("read-only",),
                capabilities=("legacy.kernel-evidence-read",),
                input_schema=SCHEMA,
                output_schema=SCHEMA,
                implementation_files=(
                    "scripts/dev_flow_parts/review.py",
                ),
                evaluator_symbol="_guard_current",
            )
        )
        runtime.seal()

        manifest = runtime.manifest()

        self.assertEqual(
            [entry["identifier"] for entry in manifest],
            ["command.zeta", "guard.alpha"],
        )
        self.assertNotIn("handler", manifest[0])
        self.assertNotIn("evaluator", manifest[1])
        self.assertEqual(manifest[0]["command"], "show")
        self.assertEqual(manifest[0]["parser_order"], 0)
        self.assertEqual(
            manifest[1]["capabilities"],
            ["legacy.kernel-evidence-read"],
        )

    def test_capability_sets_are_immutable_unique_and_sorted(self) -> None:
        entry = registry.GuardRegistration(
            identifier="guard.current",
            contract_version="v1",
            implementation_sha256=DIGEST_A,
            authority=("read-only",),
            capabilities=(
                "legacy.kernel-evidence-read",
                "projection.current-evidence",
            ),
            input_schema=SCHEMA,
            output_schema=SCHEMA,
            implementation_files=(
                "scripts/dev_flow_parts/review.py",
            ),
            evaluator_symbol="_guard_current",
        )
        self.assertIsInstance(entry.capabilities, tuple)

        with self.assertRaises(
            registry.WorkflowRegistryError
        ) as raised:
            registry.GuardRegistration(
                identifier="guard.invalid-capabilities",
                contract_version="v1",
                implementation_sha256=DIGEST_A,
                authority=("read-only",),
                capabilities=("projection.z", "projection.a"),
                input_schema=SCHEMA,
                output_schema=SCHEMA,
                implementation_files=(
                    "scripts/dev_flow_parts/review.py",
                ),
                evaluator_symbol="_guard_current",
            )
        self.assertEqual(
            raised.exception.code,
            "REGISTRY_INVALID_CAPABILITY_SET",
        )

    def test_symbols_are_late_bound_from_the_live_shared_namespace(self) -> None:
        entry = command_registration()

        first = object()
        second = object()
        namespace = {
            "_register_show_parser": lambda: None,
            "command_show": lambda: first,
        }
        bound_first = entry.bind("handler", namespace)
        self.assertIs(bound_first(), first)
        namespace["command_show"] = lambda: second
        bound_second = entry.bind("handler", namespace)
        self.assertIs(bound_second(), second)
        self.assertIsNot(bound_first, bound_second)

        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            entry.bind("unknown", namespace)
        self.assertEqual(
            raised.exception.code, "REGISTRY_UNKNOWN_BINDING_ROLE"
        )

    def test_dotted_or_missing_symbols_fail_closed(self) -> None:
        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            registry.GuardRegistration(
                identifier="guard.current",
                contract_version="v1",
                implementation_sha256=DIGEST_A,
                authority=("read-only",),
                capabilities=(),
                input_schema=SCHEMA,
                output_schema=SCHEMA,
                implementation_files=(
                    "scripts/dev_flow_parts/review.py",
                ),
                evaluator_symbol="module.guard",
            )
        self.assertEqual(raised.exception.code, "REGISTRY_INVALID_SYMBOL")

        entry = command_registration()
        with self.assertRaises(registry.WorkflowRegistryError) as raised:
            entry.bind("handler", {})
        self.assertEqual(
            raised.exception.code, "REGISTRY_SYMBOL_UNAVAILABLE"
        )


if __name__ == "__main__":
    unittest.main()
