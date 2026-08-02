"""Shared test support: scratch git repositories and controllers."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

from dev_flow_orchestrator.controller import Controller


def make_repository(root: Path, name: str = "work") -> Path:
    repository = root / name
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@local"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"],
        check=True,
    )
    (repository / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "a.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "init"],
        check=True,
    )
    return repository


class RepositoryTestCase(unittest.TestCase):
    """Temporary data dir plus a scratch git repository and controller."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = str(self.root / "data")
        self.repository = make_repository(self.root)
        self.controller = Controller(self.data_dir)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def start_lite(self, requirement: str = "A test requirement") -> str:
        state = self.controller.start(
            requirement=requirement,
            workflow="lite",
            repository=str(self.repository),
        )
        return state.task_id
