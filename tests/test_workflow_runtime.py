from __future__ import annotations

import dataclasses
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock


if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = test_case.SCRIPT
dev_flow = test_case.dev_flow


class WorkflowRuntimeTests(unittest.TestCase):
    def test_startup_publishes_one_complete_sealed_runtime(self) -> None:
        services = dev_flow.workflow_runtime_services()

        self.assertIs(services, dev_flow._WORKFLOW_RUNTIME_SERVICES)
        self.assertIsInstance(services.store, dev_flow.WorkflowStoreService)
        self.assertIsInstance(services.locks, dev_flow.WorkflowLockService)
        self.assertIsInstance(
            services.evidence, dev_flow.WorkflowEvidenceService
        )
        self.assertIsInstance(services.git, dev_flow.WorkflowGitService)
        self.assertIsInstance(
            services.adapters, dev_flow.WorkflowAdapterService
        )
        self.assertIs(
            services.adapters.registry,
            dev_flow._RUNTIME_ADAPTER_REGISTRY,
        )
        self.assertTrue(services.registries.sealed)
        self.assertTrue(
            all(registry.sealed for registry in services.registries.all())
        )
        manifest = services.registries.manifest()
        registered = {
            (
                registry.name,
                entry.identifier,
                entry.contract_version,
            )
            for registry in services.registries.all()
            for entry in registry.entries.values()
        }
        self.assertEqual(
            {
                (
                    item["registry"],
                    item["identifier"],
                    item["contract_version"],
                )
                for item in manifest
            },
            registered,
        )
        self.assertEqual(len(manifest), len(registered))
        self.assertEqual(
            set(services.catalog.bundles),
            {
                ("full", 3),
                ("full", 4),
                ("lite", 3),
                ("lite", 4),
                ("full-legacy", 2),
                ("lite-legacy", 2),
            },
        )
        self.assertEqual(
            set(services.legacy_adapters),
            {
                (1, "full"),
                (1, "lite"),
                (2, "full"),
                (2, "lite"),
            },
        )
        self.assertTrue(
            all(
                activation["active"] is False
                for activation in services.catalog.activations
            )
        )
        self.assertEqual(
            services.catalog.resolve("full", 3).active_profiles,
            (),
        )
        self.assertEqual(
            services.catalog.resolve("lite", 3).active_profiles,
            (),
        )
        self.assertEqual(
            services.catalog.resolve("full", 4).active_profiles,
            (),
        )
        self.assertEqual(
            services.catalog.resolve("lite", 4).active_profiles,
            (),
        )
        self.assertTrue(
            all(
                services.catalog.resolve(workflow_id, 2).active_profiles == ()
                for workflow_id in ("full-legacy", "lite-legacy")
            )
        )

    def test_fresh_build_is_sealed_and_rejects_late_registration(
        self,
    ) -> None:
        services = dev_flow.build_workflow_runtime(vars(dev_flow))
        existing = next(iter(services.registries.guards.entries.values()))

        with self.assertRaises(dev_flow.WorkflowRegistryError) as raised:
            services.registries.guards.register(existing)

        self.assertEqual(raised.exception.code, "REGISTRY_SEALED")

    def test_runtime_capability_surface_is_frozen_and_fixed(self) -> None:
        services = dev_flow.workflow_runtime_services()

        with self.assertRaises(dataclasses.FrozenInstanceError):
            services.store._load_state = object()
        with self.assertRaises(dev_flow.WorkflowCatalogError) as raised:
            dev_flow._WorkflowRuntimeOperation(
                symbol="_commit_state",
                namespace=vars(dev_flow),
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_RUNTIME_CAPABILITY_UNDECLARED",
        )
        self.assertFalse(hasattr(services.store, "resolve"))
        self.assertFalse(hasattr(services.git, "resolve"))
        self.assertFalse(hasattr(services.adapters, "resolve"))

    def test_runtime_capabilities_resolve_legacy_backends_late(
        self,
    ) -> None:
        services = dev_flow.workflow_runtime_services()
        store_result = object()
        task_directory_result = object()
        event_result = object()
        evidence_result = object()
        git_result = object()
        adapter_result = object()

        with (
            mock.patch.object(
                dev_flow,
                "_read_task_state_structural_snapshot",
                return_value=store_result,
            ) as read_snapshot,
            mock.patch.object(
                dev_flow,
                "_task_dir",
                return_value=task_directory_result,
            ) as task_directory,
            mock.patch.object(
                dev_flow,
                "_fingerprint_repo",
                return_value=evidence_result,
            ) as fingerprint,
            mock.patch.object(
                dev_flow,
                "_osc_read_bounded_events",
                return_value=event_result,
            ) as read_events,
            mock.patch.object(
                dev_flow,
                "_git_evidence",
                return_value=git_result,
            ) as git_observe,
            mock.patch.object(
                dev_flow,
                "create_mcp_controller_service",
                return_value=adapter_result,
            ) as create_mcp,
        ):
            self.assertIs(
                services.store.task_directory("task-1", "/data"),
                task_directory_result,
            )
            self.assertIs(
                services.store.read_structural_snapshot(
                    Path("/task/state.json")
                ),
                store_result,
            )
            self.assertIs(
                services.store.read_bounded_events(Path("/task")),
                event_result,
            )
            self.assertIs(
                services.evidence.fingerprint_repository(Path("/repo")),
                evidence_result,
            )
            self.assertIs(
                services.git.observe(Path("/repo"), "status"),
                git_result,
            )
            self.assertIs(
                services.adapters.create_mcp_controller_service(
                    data_dir="/data"
                ),
                adapter_result,
            )

        read_snapshot.assert_called_once_with(Path("/task/state.json"))
        task_directory.assert_called_once_with("task-1", "/data")
        read_events.assert_called_once_with(Path("/task"))
        fingerprint.assert_called_once_with(Path("/repo"))
        git_observe.assert_called_once_with(Path("/repo"), "status")
        create_mcp.assert_called_once_with(data_dir="/data")

    def test_lock_capability_shares_the_facade_context(self) -> None:
        services = dev_flow.workflow_runtime_services()
        task_directory = Path("/data/tasks/task-1")
        workspace_directory = Path("/workspaces/task-1")
        token = dev_flow._HELD_LOCK_DIRECTORIES.set(
            (
                str(task_directory.resolve(strict=False)),
                str(workspace_directory.resolve(strict=False)),
            )
        )
        try:
            with mock.patch.object(
                dev_flow,
                "_held_task_directory",
                return_value=task_directory,
            ):
                self.assertEqual(
                    services.locks.workflow_transition_locks(
                        {"task_id": "task-1"}
                    ),
                    (True, True, True),
                )
        finally:
            dev_flow._HELD_LOCK_DIRECTORIES.reset(token)

    def test_production_mutations_consume_the_runtime_lock_boundary(
        self,
    ) -> None:
        mutation_functions = (
            dev_flow.evaluate_v3_workflow_movement,
            dev_flow._workflow_action_kernel_context,
            dev_flow.commit_v3_node_event,
            dev_flow._osc_commit_control_event,
        )

        for function in mutation_functions:
            with self.subTest(function=function.__name__):
                self.assertIn(
                    "workflow_runtime_services",
                    function.__code__.co_names,
                )
                self.assertNotIn(
                    "_workflow_transition_locks",
                    function.__code__.co_names,
                )

    def test_failed_initialization_never_publishes_partial_services(
        self,
    ) -> None:
        failure = dev_flow.WorkflowCatalogError(
            "WORKFLOW_TEST_LOAD_FAILED",
            "synthetic catalog failure",
        )
        with (
            mock.patch.object(
                dev_flow, "_workflow_runtime_services", None
            ),
            mock.patch.object(
                dev_flow,
                "load_workflow_catalog",
                side_effect=failure,
            ),
        ):
            with self.assertRaises(dev_flow.WorkflowCatalogError):
                dev_flow.initialize_workflow_runtime(vars(dev_flow))
            self.assertIsNone(dev_flow._workflow_runtime_services)

    def test_missing_capability_never_publishes_partial_services(
        self,
    ) -> None:
        with (
            mock.patch.object(
                dev_flow, "_workflow_runtime_services", None
            ),
            mock.patch.object(dev_flow, "_git_evidence", None),
        ):
            with self.assertRaises(dev_flow.WorkflowCatalogError) as raised:
                dev_flow.initialize_workflow_runtime(vars(dev_flow))
            self.assertEqual(
                raised.exception.code,
                "WORKFLOW_RUNTIME_CAPABILITY_UNAVAILABLE",
            )
            self.assertIsNone(dev_flow._workflow_runtime_services)

    def test_reserved_v3_inspection_uses_exact_pinned_bundle_identity(
        self,
    ) -> None:
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        state = {
            "schema_version": 3,
            "task_id": "runtime-v3",
            "revision": 0,
            "status": "INTAKE",
            "flow": "full",
            "execution_profile": "single-repository",
            "workflow_ref": {
                "id": bundle.workflow_id,
                "version": bundle.workflow_version,
                "schema": bundle.graph["schema"],
                "graph_sha256": bundle.graph_sha256,
                "bundle_sha256": bundle.bundle_sha256,
            },
            "node_instances": [],
        }

        resolution = dev_flow.resolve_loaded_task_workflow(
            state, purpose="inspection"
        )

        self.assertTrue(resolution["supported"])
        self.assertEqual(resolution["kind"], "bundle")
        self.assertEqual(
            resolution["bundle_sha256"], bundle.bundle_sha256
        )
        with self.assertRaises(dev_flow.WorkflowStateError) as blocked:
            dev_flow.resolve_loaded_task_workflow(
                state, purpose="mutation"
            )
        self.assertEqual(
            blocked.exception.code, "WORKFLOW_RESERVED_UNEXPOSED"
        )
        substituted = json.loads(json.dumps(state))
        substituted["workflow_ref"]["bundle_sha256"] = "f" * 64
        with self.assertRaises(dev_flow.WorkflowStateError) as raised:
            dev_flow.resolve_loaded_task_workflow(
                substituted, purpose="inspection"
            )
        self.assertEqual(raised.exception.code, "WORKFLOW_BUNDLE_UNKNOWN")

    def test_independent_module_loads_receive_independent_singletons(
        self,
    ) -> None:
        loaded = []
        for _ in range(2):
            name = f"dev_flow_runtime_{uuid.uuid4().hex}"
            spec = importlib.util.spec_from_file_location(name, SCRIPT)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loaded.append(module)

        self.assertIsNot(
            loaded[0].workflow_runtime_services(),
            loaded[1].workflow_runtime_services(),
        )
        self.assertEqual(
            len(loaded[0].workflow_runtime_services().catalog.bundles), 6
        )
        self.assertEqual(
            len(loaded[1].workflow_runtime_services().catalog.bundles), 6
        )
        self.assertIsNot(
            loaded[0]._HELD_LOCK_DIRECTORIES,
            loaded[1]._HELD_LOCK_DIRECTORIES,
        )
        self.assertIsNot(
            loaded[0]._FILESYSTEM_CASE_CACHE,
            loaded[1]._FILESYSTEM_CASE_CACHE,
        )
        self.assertIsNot(
            loaded[0]._FILESYSTEM_UNICODE_CACHE,
            loaded[1]._FILESYSTEM_UNICODE_CACHE,
        )
        loaded[0]._FILESYSTEM_CASE_CACHE["first-facade-only"] = True
        loaded[0]._FILESYSTEM_UNICODE_CACHE["first-facade-only"] = False
        self.assertNotIn(
            "first-facade-only", loaded[1]._FILESYSTEM_CASE_CACHE
        )
        self.assertNotIn(
            "first-facade-only", loaded[1]._FILESYSTEM_UNICODE_CACHE
        )
        first_token = loaded[0]._HELD_LOCK_DIRECTORIES.set(
            ("first-facade-only",)
        )
        try:
            self.assertEqual(
                loaded[0].workflow_runtime_services().locks.held_directories(),
                ("first-facade-only",),
            )
            self.assertEqual(
                loaded[1].workflow_runtime_services().locks.held_directories(),
                (),
            )
        finally:
            loaded[0]._HELD_LOCK_DIRECTORIES.reset(first_token)
        with (
            mock.patch.object(
                loaded[0],
                "_read_task_state_structural_snapshot",
                return_value={"facade": 0},
            ),
            mock.patch.object(
                loaded[1],
                "_read_task_state_structural_snapshot",
                return_value={"facade": 1},
            ),
        ):
            self.assertEqual(
                loaded[0]
                .workflow_runtime_services()
                .store.read_structural_snapshot(Path("/state.json")),
                {"facade": 0},
            )
            self.assertEqual(
                loaded[1]
                .workflow_runtime_services()
                .store.read_structural_snapshot(Path("/state.json")),
                {"facade": 1},
            )

    def test_isolated_direct_script_startup_initializes_runtime(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(SCRIPT),
                    "list",
                    "--data-dir",
                    temporary,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertTrue(response["ok"])
        self.assertEqual(response["command"], "list")


if __name__ == "__main__":
    unittest.main()
