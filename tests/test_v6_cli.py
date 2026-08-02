"""V6 CLI subprocess journeys and machine-readable error contract."""

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

from support import make_repository


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

    def invoke_json(self, *arguments: str):
        completed = run_cli(self.data_dir, *arguments)
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                "CLI did not emit JSON: {}\nstdout={}\nstderr={}".format(
                    exc,
                    completed.stdout,
                    completed.stderr,
                )
            )
        return completed, value

    def invoke_success(self, *arguments: str) -> dict:
        completed, value = self.invoke_json(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(value["ok"])
        return value

    def next_projection(self, task_id: str) -> dict:
        return self.invoke_success("next", task_id)["projection"]

    def apply_projection(
        self,
        task_id: str,
        projection: dict,
        payload: dict,
    ) -> dict:
        action = projection["action"]
        return self.invoke_success(
            "apply",
            task_id,
            "--action",
            action["action_id"],
            "--payload-json",
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "--binding-json",
            json.dumps(action["binding"], sort_keys=True, separators=(",", ":")),
        )

    def start_lite(self, requirement: str) -> dict:
        return self.invoke_success(
            "start",
            "--requirement",
            requirement,
            "--workflow",
            "lite",
            "--repo",
            str(self.repository),
        )

    def test_full_lite_lifecycle_via_cli(self) -> None:
        started = self.start_lite("cli feature")
        self.assertEqual(started["command"], "start")
        task_id = started["task"]["task_id"]
        self.assertEqual(started["task"]["workflow"]["version"], 6)

        shown = self.invoke_success("show", task_id)
        self.assertEqual(shown["task"]["task_id"], task_id)
        self.assertEqual(shown["task"]["current_node"], "preflight")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "task.preflight")
        applied = self.apply_projection(task_id, projection, {})
        self.assertEqual(applied["receipt"]["status"], "IMPLEMENTING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "implementation.record")
        with (self.repository / "a.txt").open("a", encoding="utf-8") as stream:
            stream.write("implemented through CLI\n")
        applied = self.apply_projection(
            task_id,
            projection,
            {"summary": "Implemented through CLI"},
        )
        self.assertEqual(applied["receipt"]["status"], "VERIFYING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "verification.record")
        applied = self.apply_projection(
            task_id,
            projection,
            {
                "passed": True,
                "command": "python3 -m unittest tests.test_v6_cli",
                "coverage": {"requirement": "proven"},
                "summary": "CLI lifecycle verified",
            },
        )
        self.assertEqual(applied["receipt"]["status"], "FINALIZING")

        projection = self.next_projection(task_id)
        self.assertEqual(
            projection["action"]["action_id"],
            "delivery.finalize.success",
        )
        applied = self.apply_projection(
            task_id,
            projection,
            {
                "summary": "Delivered through CLI",
                "remaining_risks": {},
                "handoff": "Ready to use",
            },
        )
        self.assertEqual(applied["receipt"]["status"], "DONE")
        self.assertTrue(applied["projection"]["done"])
        self.assertEqual(applied["projection"]["dossier"]["outcome"], "success")

        shown = self.invoke_success("show", task_id)
        dossier = shown["task"]["records"][-1]["artifact"]["body"]
        self.assertEqual(dossier["schema"], "dev-flow-delivery-dossier/v1")
        self.assertEqual(dossier["change_summary"], "Delivered through CLI")
        self.assertEqual(dossier["handoff_recommendation"], "Ready to use")
        self.assertEqual(dossier["coverage"]["requirement"]["status"], "proven")

    def test_cancel_after_preflight_and_list(self) -> None:
        started = self.start_lite("cancel me")
        task_id = started["task"]["task_id"]
        projection = self.next_projection(task_id)
        self.apply_projection(task_id, projection, {})

        cancelled = self.invoke_success(
            "cancel",
            task_id,
            "--reason",
            "No longer required",
        )
        self.assertEqual(cancelled["receipt"]["status"], "CANCELLED")
        listing = self.invoke_success("list")
        self.assertEqual(len(listing["tasks"]), 1)
        self.assertEqual(listing["tasks"][0]["task_id"], task_id)
        self.assertEqual(listing["tasks"][0]["status"], "CANCELLED")

    def test_workflow_accepts_custom_v6_path(self) -> None:
        flow_path = self.root / "custom-lite.yaml"
        flow_path.write_text(
            (ROOT / "workflows" / "lite.yaml")
            .read_text(encoding="utf-8")
            .replace("id: lite\n", "id: custom-lite\n", 1),
            encoding="utf-8",
        )
        started = self.invoke_success(
            "start",
            "--requirement",
            "custom",
            "--workflow",
            str(flow_path),
            "--repo",
            str(self.repository),
        )
        self.assertEqual(started["task"]["workflow"]["id"], str(flow_path))
        self.assertEqual(
            started["task"]["workflow"]["schema"],
            "dev-flow-workflow/v2",
        )
        self.assertEqual(started["task"]["workflow"]["version"], 6)

    def test_missing_task_error_is_machine_readable(self) -> None:
        completed, value = self.invoke_json("show", "missing-task-id")
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(value["ok"])
        self.assertEqual(value["error"]["code"], "TASK_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
