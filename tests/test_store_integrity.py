"""Current TaskStore path, inventory, and ledger integrity."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError, json_value
from dev_flow_orchestrator.product import PLUGIN_DATA_NAMESPACE
from support import RepositoryTestCase, make_repository


class StoreIntegrityTests(RepositoryTestCase):
    def state_path(self, task_id: str) -> Path:
        return (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )

    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def test_state_symlink_is_rejected(self) -> None:
        first = self.start_lite("first")
        second_repository = make_repository(self.root, "second-repository")
        second = self.controller.start(
            requirement="second",
            workflow="lite",
            repositories=(str(second_repository),),
        ).task_id
        first_path = self.state_path(first)
        second_path = self.state_path(second)
        first_path.unlink()
        first_path.symlink_to(second_path)

        with self.assertRaises(DevFlowError) as context:
            self.controller.show(first)
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_dangling_state_symlink_is_rejected(self) -> None:
        task_id = self.start_lite()
        state_path = self.state_path(task_id)
        state_path.unlink()
        state_path.symlink_to(self.root / "missing-state.json")

        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_task_directory_symlink_is_rejected(self) -> None:
        existing = self.start_lite()
        tasks = Path(self.data_dir) / PLUGIN_DATA_NAMESPACE / "tasks"
        alias = tasks / "task-alias"
        alias.symlink_to(tasks / existing, target_is_directory=True)

        with self.assertRaises(DevFlowError) as context:
            self.controller.show("task-alias")
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_lock_symlink_is_rejected(self) -> None:
        task_id = self.start_lite()
        lock = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "locks"
            / (task_id + ".lock")
        )
        lock.unlink()
        lock.symlink_to(self.root / "lock-target")

        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_inventory_omits_orphan_but_direct_load_is_strict(self) -> None:
        healthy = self.start_lite("healthy")
        orphan = "task-orphan"
        (Path(self.data_dir) / PLUGIN_DATA_NAMESPACE / "tasks" / orphan).mkdir()

        self.assertEqual(
            tuple(state.task_id for state in self.controller.list_tasks()),
            (healthy,),
        )
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(orphan)
        self.assertEqual(context.exception.code, "TASK_NOT_FOUND")

    def test_inventory_omits_corrupt_state_but_direct_load_is_strict(self) -> None:
        healthy = self.start_lite("healthy")
        corrupt_repository = make_repository(self.root, "corrupt-repository")
        corrupt = self.controller.start(
            requirement="corrupt",
            workflow="lite",
            repositories=(str(corrupt_repository),),
        ).task_id
        self.state_path(corrupt).write_text("{not json", encoding="utf-8")

        self.assertEqual(
            tuple(state.task_id for state in self.controller.list_tasks()),
            (healthy,),
        )
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(corrupt)
        self.assertEqual(context.exception.code, "STATE_INVALID")

    def test_unsupported_product_version_is_rejected(self) -> None:
        task_id = self.start_lite()
        state_path = self.state_path(task_id)
        value = json.loads(state_path.read_text(encoding="utf-8"))
        value["version"] = "unsupported"
        state_path.write_text(json.dumps(value), encoding="utf-8")

        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "STATE_INVALID")

    def test_inventory_tasks_root_symlink_is_strict(self) -> None:
        data_root = self.root / "strict-inventory"
        target = self.root / "inventory-target"
        data_root.mkdir()
        target.mkdir()
        namespace = data_root / PLUGIN_DATA_NAMESPACE
        namespace.mkdir()
        (namespace / "tasks").symlink_to(target, target_is_directory=True)
        controller = Controller(str(data_root))

        with self.assertRaises(DevFlowError) as context:
            controller.list_tasks()
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_inventory_locks_root_symlink_is_strict(self) -> None:
        self.start_lite("healthy")
        locks_root = Path(self.data_dir) / PLUGIN_DATA_NAMESPACE / "locks"
        target = self.root / "locks-target"
        locks_root.rename(target)
        locks_root.symlink_to(target, target_is_directory=True)

        with self.assertRaises(DevFlowError) as context:
            self.controller.list_tasks()
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_state_path_and_embedded_task_id_must_match(self) -> None:
        first = self.start_lite("first")
        second_repository = make_repository(self.root, "identity-repository")
        second = self.controller.start(
            requirement="second",
            workflow="lite",
            repositories=(str(second_repository),),
        ).task_id
        self.state_path(first).write_bytes(self.state_path(second).read_bytes())

        with self.assertRaises(DevFlowError) as context:
            self.controller.show(first)
        self.assertEqual(context.exception.code, "STATE_INVALID")
        self.assertEqual(context.exception.details["expected_task_id"], first)

    def test_prior_namespace_bytes_are_inert_and_unchanged(self) -> None:
        prior = Path(self.data_dir) / "0.2.0" / "tasks" / "task-retained"
        prior.mkdir(parents=True)
        state_path = prior / "state.json"
        retained = b'{"version":"0.2.0","opaque":true}\n'
        state_path.write_bytes(retained)

        task_id = self.start_lite("current namespace only")

        self.assertEqual(state_path.read_bytes(), retained)
        self.assertEqual(
            tuple(state.task_id for state in self.controller.list_tasks()),
            (task_id,),
        )
        self.assertTrue(self.state_path(task_id).is_file())

    def test_initial_contract_and_requirement_are_immutable(self) -> None:
        task_id = self.start_lite()
        before = self.controller.show(task_id)
        changed_contract = json_value(before.original_contract)
        changed_contract["summary"] = "Rewritten contract"

        for field, value in (
            ("requirement", "Rewritten requirement"),
            ("original_contract", changed_contract),
        ):
            with self.subTest(field=field):
                with self.assertRaises(DevFlowError) as context:
                    self.controller.store.update(
                        task_id,
                        0,
                        lambda state, field=field, value=value: replace(
                            state, **{field: value}
                        ),
                    )
                self.assertEqual(context.exception.code, "STATE_WRITE_INVALID")
                self.assertEqual(context.exception.details["fields"], [field])
                self.assertEqual(self.controller.show(task_id), before)

    def test_mutation_cannot_rewrite_existing_records(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        before = self.controller.show(task_id)
        rewritten = json_value(before.records[0])
        rewritten["payload"] = {"forged": True}

        with self.assertRaises(DevFlowError) as context:
            self.controller.store.update(
                task_id,
                before.revision,
                lambda state: replace(
                    state,
                    revision=state.revision + 1,
                    updated_at="2026-08-01T00:00:00Z",
                    records=(rewritten, state.records[0]),
                ),
            )

        self.assertEqual(context.exception.code, "STATE_WRITE_INVALID")
        self.assertEqual(self.controller.show(task_id), before)

    def test_invalid_candidate_shape_fails_before_write(self) -> None:
        task_id = self.start_lite()
        before = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.store.update(
                task_id,
                0,
                lambda state: replace(
                    state,
                    revision=1,
                    updated_at="2026-08-01T00:00:00Z",
                    status="",
                    records=({"invalid": True},),
                ),
            )

        self.assertEqual(context.exception.code, "STATE_INVALID")
        self.assertEqual(context.exception.details["reason"], "state_shape_invalid")
        self.assertEqual(self.controller.show(task_id), before)


if __name__ == "__main__":
    unittest.main()
