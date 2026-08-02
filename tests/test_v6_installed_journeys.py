"""Focused subprocess-only self-test for installed Stage 1 acceptance."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import validate_installed_stage1 as acceptance


RUNNER = ROOT / "scripts" / "validate_installed_stage1.py"


class ExternalEvidenceValidationTests(unittest.TestCase):
    def _driver(self, tool: str) -> dict:
        return {
            "execution": "actual-tool-execution",
            "output_sha256": "b" * 64,
            "result": {
                "schema": "dev-flow-driver-result/v1",
                "status": "available",
                "tool": tool,
                "phase": "stage1-release",
                "details": {"observation": "actual tool output captured"},
                "limitations": [],
            },
        }

    def _external(self) -> dict:
        observation = {
            "state_digest": "c" * 64,
            "list_output_sha256": "d" * 64,
            "show_output_sha256": "e" * 64,
            "task": {
                "task_id": "retained-task",
                "revision": 7,
                "status": "VERIFYING",
                "current_node": "verify",
            },
        }
        return {
            "schema": "dev-flow-stage1-external-evidence/v1",
            "installed_snapshot_digest": "a" * 64,
            "driver_executions": [
                self._driver("openspec"),
                self._driver("codebase-memory"),
                self._driver("independent-review"),
            ],
            "retained_v5": {
                "schema": "dev-flow-retained-v5-inspection/v1",
                "root_snapshot_digest": "f" * 64,
                "controller_locator_sha256": "1" * 64,
                "operations": ["list", "show"],
                "read_only": True,
                "before": observation,
                "after": dict(observation),
            },
        }

    def test_external_evidence_is_snapshot_bound_and_requires_unchanged_v5(self) -> None:
        retained = {"status": "snapshot-verified", "snapshot_digest_before": "f" * 64}
        result = acceptance._validate_external_release_evidence(
            self._external(), "a" * 64, retained
        )
        self.assertEqual(len(result["driver_executions"]), 3)
        self.assertTrue(result["retained_v5"]["unchanged"])

        changed = self._external()
        changed["retained_v5"]["after"]["state_digest"] = "2" * 64
        with self.assertRaises(acceptance.AcceptanceFailure):
            acceptance._validate_external_release_evidence(
                changed, "a" * 64, retained
            )


@unittest.skipUnless(sys.platform == "darwin", "installed acceptance is macOS-only")
class InstalledStage1JourneyTests(unittest.TestCase):
    def test_controller_simulation_cannot_replace_external_release_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-v5-root-only-") as root:
            retained = Path(root)
            (retained / ".codex-plugin").mkdir()
            (retained / "scripts").mkdir()
            (retained / ".codex-plugin" / "plugin.json").write_text(
                json.dumps(
                    {
                        "name": "dev-flow-orchestrator",
                        "version": "5.0.0+codex.selftest",
                    }
                ),
                encoding="utf-8",
            )
            launcher = retained / "scripts" / "dev_flow_python_launcher"
            launcher.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            launcher.chmod(0o755)
            (retained / "scripts" / "dev_flow.py").write_text(
                "# retained V5 identity fixture\n", encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--plugin-root",
                    str(ROOT),
                    "--retained-v5-root",
                    str(retained),
                ],
                cwd=str(ROOT),
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONHASHSEED": "0",
                },
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=180,
            )
        try:
            evidence = json.loads(completed.stdout)
        except ValueError as exc:
            self.fail(
                "installed runner returned invalid JSON: {} ({})".format(
                    completed.stdout[-2048:], exc
                )
            )
        self.assertEqual(
            completed.returncode,
            1,
            "{}\n{}".format(evidence.get("errors"), completed.stderr),
        )
        self.assertFalse(evidence["ok"])
        self.assertTrue(evidence["execution_ok"])
        self.assertEqual(evidence["release_gate"]["status"], "unverified")
        self.assertEqual(evidence["release_gate"]["blockers"], [
            "actual OpenSpec, codebase-memory, and independent-review executions were not provided",
            "retained V5 list/show before-and-after evidence was not provided",
        ])
        self.assertTrue(evidence["installed"]["immutable_during_run"])
        self.assertTrue(evidence["package_validation"]["result"]["ok"])
        official = {
            "official-success-{}".format(workflow)
            for workflow in (
                "bugfix",
                "feature",
                "full",
                "investigation",
                "lite",
                "refactor",
            )
        }
        names = {journey["name"] for journey in evidence["journeys"]}
        self.assertTrue(official.issubset(names))
        self.assertTrue(
            {
                "process-restart-resume",
                "cancellation",
                "verification-rework-exhaustion",
                "criterion-waiver",
                "contract-revision-and-openspec-resources",
            }.issubset(names)
        )
        self.assertEqual(
            {
                path["result"]["status"]
                for path in evidence["driver_paths"]
            },
            {"available", "degraded", "unavailable"},
        )
        self.assertTrue(
            all(
                path["evidence_class"] == "controller-contract-simulation"
                and path["qualifies_as_driver_execution"] is False
                and path["result"]["schema"] == "dev-flow-driver-result/v1"
                for path in evidence["driver_paths"]
            )
        )
        self.assertTrue(evidence["hook"]["bootstrap_verified"])
        self.assertEqual(
            evidence["hook"]["codex_new_task_pickup"], "manual-unverified"
        )
        self.assertTrue(evidence["process_model"]["fresh_subprocess_per_command"])
        self.assertTrue(
            evidence["retained_v5"]["snapshot_immutable_during_run"]
        )
        self.assertEqual(
            evidence["retained_v5"]["data_evidence"]["status"],
            "unverified",
        )


if __name__ == "__main__":
    unittest.main()
