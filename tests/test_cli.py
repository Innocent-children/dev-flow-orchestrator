"""Current CLI subprocess journeys and machine-readable error contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from support import make_repository
from dev_flow_orchestrator.cli import _resolve_data_dir
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    MODEL_VERSION,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    TASK_CHANGE_CLAIMS_SCHEMA,
    WORKFLOW_SCHEMA,
)


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

    def test_data_directory_defaults_to_codex_plugin_namespace(self) -> None:
        codex_root = self.root / "codex-home"
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow.py"),
                "web",
                "status",
            ],
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "CODEX_HOME": str(codex_root),
                "PYTHONPATH": str(SRC),
            },
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "stopped")
        self.assertFalse(codex_root.exists())

    def test_data_directory_resolution_precedence_is_explicit_plugin_then_codex(self) -> None:
        explicit = self.root / "explicit"
        plugin_data = self.root / "plugin-data"
        codex_root = self.root / "codex-root"

        with mock.patch.dict(
            os.environ,
            {"PLUGIN_DATA": str(plugin_data), "CODEX_HOME": str(codex_root)},
            clear=False,
        ):
            self.assertEqual(_resolve_data_dir(str(explicit)), str(explicit.resolve()))
            self.assertEqual(
                _resolve_data_dir(None),
                str((plugin_data / MODEL_VERSION).resolve()),
            )
        with mock.patch.dict(
            os.environ,
            {"CODEX_HOME": str(codex_root)},
            clear=False,
        ):
            os.environ.pop("PLUGIN_DATA", None)
            self.assertEqual(
                _resolve_data_dir(None),
                str(
                    (
                        codex_root
                        / "plugins"
                        / "data"
                        / "dev-flow-orchestrator-personal"
                        / MODEL_VERSION
                    ).resolve()
                ),
            )

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
        repository_id = started["task"]["repositories"][0]["id"]
        self.assertEqual(started["task"]["workflow"]["version"], MODEL_VERSION)

        shown = self.invoke_success("show", task_id)
        self.assertEqual(shown["task"]["task_id"], task_id)
        self.assertEqual(shown["task"]["current_node"], "preflight")
        self.assertEqual(
            shown["task"]["current_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(len(shown["task"]["current_snapshot"]["repositories"]), 1)

        projection = self.next_projection(task_id)
        self.assertEqual(projection["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(len(projection["repository_set"]["repositories"]), 1)
        self.assertEqual(
            projection["repository_set"]["repositories"][0]["id"],
            repository_id,
        )
        self.assertEqual(projection["action"]["action_id"], "task.preflight")
        applied = self.apply_projection(task_id, projection, {})
        self.assertEqual(applied["receipt"]["status"], "ANALYZING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "impact.record")
        applied = self.apply_projection(task_id, projection, {
            "summary": "CLI impact confirmed",
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": "available",
            },
            "impact_manifest": {
                "confidence": "source-confirmed",
                "entries": [{
                    "repository_id": repository_id,
                    "path": "a.txt",
                    "symbol": None,
                    "criterion_ids": ["requirement"],
                }],
                "edges": [],
                "risk_triggers": [],
                "public_behavior": False,
                "documentation_required": False,
                "manual_evidence_required": False,
                "executable_reproduction_required": True,
                "overflow": False,
                "limitations": [],
            },
        })
        self.assertEqual(applied["receipt"]["status"], "IMPLEMENTING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "implementation.record")
        with (self.repository / "a.txt").open("a", encoding="utf-8") as stream:
            stream.write("implemented through CLI\n")
        applied = self.apply_projection(
            task_id,
            projection,
            {
                "summary": "Implemented through CLI",
                "ownership_claims": {
                    "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                    "claims": [{
                        "repository_id": repository_id,
                        "path": "a.txt",
                        "classification": "implementation",
                        "criterion_ids": ["requirement"],
                        "purpose": "Exercise CLI task-owned changes",
                    }],
                },
            },
        )
        self.assertEqual(applied["receipt"]["status"], "VERIFYING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "assurance.execute")
        obligation = projection["action"]["current_obligation"]
        self.assertEqual(obligation["repository_ids"], [repository_id])
        verification_command = "python3 -m unittest tests.test_cli"
        applied = self.apply_projection(
            task_id,
            projection,
            {
                "summary": "CLI lifecycle verified",
                "assurance_result": {
                    "obligation_id": obligation["obligation_id"],
                    "passed": True,
                    "evidence": [{
                        "kind": "command",
                        "reference": verification_command,
                        "summary": "CLI lifecycle verified",
                    }],
                    "limitations": [],
                },
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
        self.assertEqual(
            applied["projection"]["dossier"]["schema"],
            DELIVERY_DOSSIER_SCHEMA,
        )
        self.assertTrue(applied["projection"]["dossier"]["current"])
        self.assertEqual(
            applied["projection"]["dossier"]["repository_set_id"],
            applied["projection"]["repository_set"]["id"],
        )

        shown = self.invoke_success("show", task_id)
        dossier = shown["task"]["records"][-1]["artifact"]["body"]
        self.assertEqual(dossier["schema"], DELIVERY_DOSSIER_SCHEMA)
        self.assertEqual(dossier["change_summary"], "Delivered through CLI")
        self.assertEqual(dossier["handoff_recommendation"], "Ready to use")
        self.assertEqual(dossier["coverage"]["requirement"]["status"], "proven")
        self.assertEqual(dossier["repository_set"]["members"][0]["repository_id"], repository_id)
        self.assertTrue(dossier["verification"]["assurance_execution"]["passed"])
        self.assertEqual(dossier["assurance_plan"]["profile"], "lite")
        self.assertTrue(dossier["aggregate_freshness"]["current"])
        self.assertEqual(
            dossier["repository_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertTrue(shown["task"]["dossier"]["current"])

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
        shown = self.invoke_success("show", task_id)
        self.assertEqual(
            shown["task"]["records"][-1]["snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )

    def test_workflow_accepts_custom_current_path(self) -> None:
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
            WORKFLOW_SCHEMA,
        )
        self.assertEqual(started["task"]["workflow"]["version"], MODEL_VERSION)

    def test_missing_task_error_is_machine_readable(self) -> None:
        completed, value = self.invoke_json("show", "missing-task-id")
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(value["ok"])
        self.assertEqual(value["error"]["code"], "TASK_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
