"""CLI JSON contract: one JSON object per invocation, stable exit codes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from v5_support import make_repository


def run_cli(data_dir: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts" / "dev_flow.py"),
            "--data-dir",
            data_dir,
            *arguments,
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = str(self.root / "data")
        self.repository = make_repository(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_start(self) -> None:
        completed = run_cli(
            self.data_dir,
            "start",
            "--requirement",
            "cli feature",
            "--workflow",
            "lite",
            "--repo",
            str(self.repository),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertTrue(value["ok"])
        self.assertEqual(value["command"], "start")
        self.assertEqual(value["task"]["status"], "INTAKE")
        self.assertTrue((Path(self.data_dir) / "tasks").is_dir())
        self.assertFalse((Path(self.data_dir) / "v5").exists())

    def test_full_lifecycle_via_cli(self) -> None:
        started = json.loads(
            run_cli(
                self.data_dir,
                "start",
                "--requirement",
                "cli feature",
                "--workflow",
                "lite",
                "--repo",
                str(self.repository),
            ).stdout
        )
        task_id = started["task"]["task_id"]

        shown = json.loads(run_cli(self.data_dir, "show", task_id).stdout)
        self.assertTrue(shown["ok"])
        self.assertEqual(shown["task"]["task_id"], task_id)

        projection = json.loads(run_cli(self.data_dir, "next", task_id).stdout)
        self.assertEqual(projection["projection"]["action"]["action_id"],
                         "task.preflight")

        applied = json.loads(
            run_cli(self.data_dir, "apply", task_id, "--action", "task.preflight").stdout
        )
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["receipt"]["status"], "IMPLEMENTING")

        applied = json.loads(
            run_cli(
                self.data_dir,
                "apply",
                task_id,
                "--action",
                "task.implementation.complete",
                "--payload-json",
                '{"summary": "done"}',
            ).stdout
        )
        self.assertEqual(applied["receipt"]["status"], "VERIFYING")

        applied = json.loads(
            run_cli(
                self.data_dir,
                "apply",
                task_id,
                "--action",
                "evidence.test.record",
                "--payload-json",
                '{"passed": true, "command": "unit"}',
            ).stdout
        )
        self.assertEqual(applied["receipt"]["status"], "DONE")
        self.assertTrue(applied["projection"]["done"])

    def test_cancel_and_list(self) -> None:
        started = json.loads(
            run_cli(
                self.data_dir,
                "start",
                "--requirement",
                "cancel me",
                "--workflow",
                "lite",
                "--repo",
                str(self.repository),
            ).stdout
        )
        task_id = started["task"]["task_id"]
        cancelled = json.loads(
            run_cli(self.data_dir, "cancel", task_id, "--reason", "nope").stdout
        )
        self.assertTrue(cancelled["ok"])
        self.assertEqual(cancelled["receipt"]["status"], "CANCELLED")
        listing = json.loads(run_cli(self.data_dir, "list").stdout)
        self.assertEqual(len(listing["tasks"]), 1)
        self.assertEqual(listing["tasks"][0]["status"], "CANCELLED")

    def test_workflow_accepts_custom_path(self) -> None:
        flow_path = self.root / "flow.yaml"
        flow_path.write_text(
            "schema: dev-flow-workflow/v1\n"
            "id: minimal\n"
            "version: 5\n"
            "entry: preflight\n"
            "nodes:\n"
            "  preflight:\n"
            "    action_id: task.preflight\n"
            "    handler: preflight\n"
            "    target: {node: done, status: DONE}\n"
            "    effect: git.inspect-repository\n"
            "  done: {terminal: true}\n",
            encoding="utf-8",
        )
        completed = run_cli(
            self.data_dir,
            "start",
            "--requirement",
            "custom",
            "--workflow",
            str(flow_path),
            "--repo",
            str(self.repository),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertEqual(value["task"]["workflow"]["id"], str(flow_path))

    def test_bad_argument_is_machine_readable(self) -> None:
        completed = run_cli(self.data_dir, "show", "missing-task-id")
        self.assertEqual(completed.returncode, 2)
        value = json.loads(completed.stdout)
        self.assertFalse(value["ok"])
        self.assertEqual(value["error"]["code"], "TASK_NOT_FOUND")

    def test_expected_revision_is_gone(self) -> None:
        completed = run_cli(
            self.data_dir,
            "apply",
            "task-x",
            "--action",
            "task.preflight",
            "--expected-revision",
            "0",
        )
        self.assertEqual(completed.returncode, 2)
        value = json.loads(completed.stdout)
        self.assertEqual(value["error"]["code"], "ARGUMENT_INVALID")

    def test_apply_invalid_payload_json(self) -> None:
        started = json.loads(
            run_cli(
                self.data_dir,
                "start",
                "--requirement",
                "x",
                "--workflow",
                "lite",
                "--repo",
                str(self.repository),
            ).stdout
        )
        task_id = started["task"]["task_id"]
        completed = run_cli(
            self.data_dir,
            "apply",
            task_id,
            "--action",
            "task.preflight",
            "--payload-json",
            "{broken",
        )
        self.assertEqual(completed.returncode, 2)
        value = json.loads(completed.stdout)
        self.assertEqual(value["error"]["code"], "ARGUMENT_JSON_INVALID")


if __name__ == "__main__":
    unittest.main()
