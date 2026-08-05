"""Physically read-only current-product task inspection."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import threading
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.product import PLUGIN_DATA_NAMESPACE
from dev_flow_orchestrator.store import TaskStore
from support import RepositoryTestCase, make_repository


def filesystem_identity(root: Path) -> tuple:
    if not root.exists() and not root.is_symlink():
        return ()
    identities = []
    pending = [root]
    while pending:
        path = pending.pop()
        metadata = path.lstat()
        relative = "." if path == root else str(path.relative_to(root))
        kind = stat.S_IFMT(metadata.st_mode)
        digest = None
        target = None
        if stat.S_ISREG(metadata.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        elif stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(path)
        elif stat.S_ISDIR(metadata.st_mode):
            pending.extend(sorted(path.iterdir(), reverse=True))
        identities.append(
            (
                relative,
                kind,
                stat.S_IMODE(metadata.st_mode),
                metadata.st_size,
                metadata.st_mtime_ns,
                digest,
                target,
            )
        )
    return tuple(sorted(identities))


class ReadOnlyInspectionTests(RepositoryTestCase):
    def state_path(self, task_id: str) -> Path:
        return (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )

    def test_missing_namespace_is_empty_and_is_not_created(self) -> None:
        missing = self.root / "missing-controller-data"
        store = TaskStore(str(missing))

        self.assertEqual(store.inspect_inventory(), ((), ()))
        self.assertFalse(missing.exists())

    def test_healthy_inventory_and_detail_do_not_change_filesystem(self) -> None:
        task_id = self.start_lite("inspect without mutation")
        data_root = Path(self.data_dir)
        before = filesystem_identity(data_root)

        entries, diagnostics = self.controller.store.inspect_inventory()
        state, definition = self.controller.store.inspect_with_definition(task_id)

        self.assertEqual(diagnostics, ())
        self.assertEqual(tuple(item.task_id for item, _ in entries), (task_id,))
        self.assertEqual(state.task_id, task_id)
        self.assertEqual(definition.workflow_id, "lite")
        self.assertEqual(filesystem_identity(data_root), before)

    def test_corrupt_entry_is_isolated_with_sanitized_diagnostic(self) -> None:
        healthy = self.start_lite("healthy")
        repository = make_repository(self.root, "corrupt-inspection-repository")
        corrupt = self.controller.start(
            requirement="corrupt",
            workflow="lite",
            repositories=(str(repository),),
        ).task_id
        self.state_path(corrupt).write_text("{not-json", encoding="utf-8")
        data_root = Path(self.data_dir)
        before = filesystem_identity(data_root)

        entries, diagnostics = self.controller.store.inspect_inventory()

        self.assertEqual(tuple(item.task_id for item, _ in entries), (healthy,))
        self.assertEqual(
            diagnostics,
            ({"code": "STATE_INVALID", "task_id": corrupt},),
        )
        self.assertNotIn(str(data_root), repr(diagnostics))
        self.assertEqual(filesystem_identity(data_root), before)

    def test_tasks_symlink_is_rejected_without_following_or_writing(self) -> None:
        data_root = self.root / "symlink-controller-data"
        target = self.root / "symlink-target"
        namespace = data_root / PLUGIN_DATA_NAMESPACE
        namespace.mkdir(parents=True)
        target.mkdir()
        (namespace / "tasks").symlink_to(target, target_is_directory=True)
        before_data = filesystem_identity(data_root)
        before_target = filesystem_identity(target)

        entries, diagnostics = TaskStore(str(data_root)).inspect_inventory()

        self.assertEqual(entries, ())
        self.assertEqual(diagnostics, ({"code": "DATA_PATH_UNSAFE", "task_id": "tasks"},))
        self.assertEqual(filesystem_identity(data_root), before_data)
        self.assertEqual(filesystem_identity(target), before_target)

    def test_prior_namespace_is_ignored_and_unchanged(self) -> None:
        data_root = self.root / "prior-only-controller-data"
        prior = data_root / "0.2.0" / "tasks" / "task-retained"
        prior.mkdir(parents=True)
        (prior / "state.json").write_bytes(b'{"version":"0.2.0"}\n')
        before = filesystem_identity(data_root)

        self.assertEqual(TaskStore(str(data_root)).inspect_inventory(), ((), ()))
        self.assertEqual(filesystem_identity(data_root), before)
        self.assertFalse((data_root / PLUGIN_DATA_NAMESPACE).exists())

    def test_atomic_replacement_yields_only_complete_old_or_new_state(self) -> None:
        task_id = self.start_lite("atomic inspection")
        state_path = self.state_path(task_id)
        old_payload = state_path.read_bytes()
        projection = self.controller.next(task_id)
        self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {},
            binding=projection["action"]["binding"],
        )
        new_payload = state_path.read_bytes()
        state_path.write_bytes(old_payload)
        started = threading.Event()

        def replace_repeatedly() -> None:
            started.set()
            for index in range(100):
                temporary = state_path.with_name("state.swap.{}.json".format(index))
                temporary.write_bytes(new_payload if index % 2 else old_payload)
                os.replace(str(temporary), str(state_path))

        writer = threading.Thread(target=replace_repeatedly)
        writer.start()
        started.wait(timeout=1)
        revisions = set()
        while writer.is_alive():
            state, _ = self.controller.store.inspect_with_definition(task_id)
            revisions.add(state.revision)
        writer.join(timeout=1)
        state, _ = self.controller.store.inspect_with_definition(task_id)
        revisions.add(state.revision)

        self.assertTrue(revisions)
        self.assertLessEqual(revisions, {0, 1})


if __name__ == "__main__":
    unittest.main()
