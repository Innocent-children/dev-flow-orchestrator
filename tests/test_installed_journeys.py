"""Focused subprocess-only self-test for installed Stage 1 acceptance."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    EXTERNAL_EVIDENCE_SCHEMA,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    VERIFICATION_COVERAGE_SCHEMA,
)
from scripts import validate_installed_stage1 as acceptance


RUNNER = ROOT / "scripts" / "validate_installed_stage1.py"


class ExternalEvidenceValidationTests(unittest.TestCase):
    def _driver(self, tool: str) -> dict:
        return {
            "execution": "actual-tool-execution",
            "output_sha256": "b" * 64,
            "result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": "available",
                "tool": tool,
                "phase": "stage1-release",
                "details": {"observation": "actual tool output captured"},
                "limitations": [],
            },
        }

    def _external(self) -> dict:
        return {
            "schema": EXTERNAL_EVIDENCE_SCHEMA,
            "installed_snapshot_digest": "a" * 64,
            "driver_executions": [
                self._driver("openspec"),
                self._driver("codebase-memory"),
                self._driver("independent-review"),
            ],
        }

    def test_external_evidence_is_snapshot_bound(self) -> None:
        result = acceptance._validate_external_release_evidence(
            self._external(), "a" * 64
        )
        self.assertEqual(len(result["driver_executions"]), 3)

        changed = self._external()
        changed["installed_snapshot_digest"] = "2" * 64
        with self.assertRaises(acceptance.AcceptanceFailure):
            acceptance._validate_external_release_evidence(
                changed, "a" * 64
            )


@unittest.skipUnless(sys.platform == "darwin", "installed acceptance is macOS-only")
class InstalledStage1JourneyTests(unittest.TestCase):
    def test_current_model_journeys_require_external_release_evidence(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--plugin-root",
                str(ROOT),
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
        self.assertTrue(evidence["execution_ok"], evidence["errors"])
        self.assertEqual(evidence["release_gate"]["status"], "unverified")
        self.assertEqual(
            evidence["release_gate"]["blockers"],
            [
                "actual OpenSpec, codebase-memory, and independent-review executions were not provided"
            ],
        )
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
        for workflow in (
            "bugfix",
            "feature",
            "full",
            "investigation",
            "lite",
            "refactor",
        ):
            outcome = evidence["outcomes"]["stage1-official-{}".format(workflow)]
            dossier = outcome["dossier"]
            baseline = evidence["baselines"]["stage1-official-{}".format(workflow)]
            self.assertEqual(
                baseline["snapshot"]["schema"],
                REPOSITORY_SET_SNAPSHOT_SCHEMA,
            )
            self.assertEqual(len(baseline["snapshot"]["repositories"]), 1)
            self.assertEqual(dossier["schema"], DELIVERY_DOSSIER_SCHEMA)
            self.assertEqual(len(dossier["repository_set"]["members"]), 1)
            verification = dossier.get("verification")
            if verification is not None:
                self.assertEqual(
                    set(verification["coverage"]),
                    {"schema", "criteria", "repositories", "integration"},
                )
                self.assertEqual(
                    verification["coverage"]["schema"],
                    VERIFICATION_COVERAGE_SCHEMA,
                )
        self.assertTrue(
            {
                "process-restart-resume",
                "cancellation",
                "verification-rework-exhaustion",
                "criterion-waiver",
                "contract-revision-and-openspec-resources",
                "exact-set-secondary-resume-drift-resources-dossier",
                "exact-set-lite-success-dossier",
            }.issubset(names)
        )
        exact_set = next(
            journey
            for journey in evidence["journeys"]
            if journey["name"]
            == "exact-set-secondary-resume-drift-resources-dossier"
        )
        self.assertEqual(exact_set["drift_error"], "ACTION_BINDING_STALE")
        self.assertEqual(exact_set["secondary_hook_schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertIsInstance(exact_set["secondary_hook_process"], int)
        self.assertEqual(exact_set["dossier_schema"], DELIVERY_DOSSIER_SCHEMA)
        self.assertEqual(len(exact_set["repository_ids"]), 2)
        self.assertNotEqual(
            exact_set["stale_aggregate_digest"],
            exact_set["fresh_aggregate_digest"],
        )
        self.assertTrue(exact_set["scoped_resource_repository_ids"])
        self.assertTrue(
            set(exact_set["scoped_resource_repository_ids"]).issubset(
                set(exact_set["repository_ids"])
            )
        )
        exact_outcome = evidence["outcomes"]["stage1-exact-set"]
        self.assertEqual(
            exact_outcome["dossier"]["schema"],
            DELIVERY_DOSSIER_SCHEMA,
        )
        self.assertEqual(
            len(exact_outcome["dossier"]["repository_set"]["members"]),
            2,
        )
        exact_lite = next(
            journey
            for journey in evidence["journeys"]
            if journey["name"] == "exact-set-lite-success-dossier"
        )
        self.assertEqual(exact_lite["workflow"], "lite")
        self.assertEqual(exact_lite["projection_schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(
            exact_lite["dossier_schema"],
            DELIVERY_DOSSIER_SCHEMA,
        )
        self.assertEqual(exact_lite["outcome"], "success")
        self.assertEqual(len(exact_lite["repository_ids"]), 2)
        self.assertEqual(
            set(exact_lite["dossier_repository_ids"]),
            set(exact_lite["repository_ids"]),
        )
        lite_outcome = evidence["outcomes"]["stage1-exact-set-lite"]
        self.assertEqual(lite_outcome["workflow"]["id"], "lite")
        self.assertEqual(
            lite_outcome["dossier"]["schema"],
            DELIVERY_DOSSIER_SCHEMA,
        )
        self.assertEqual(
            len(lite_outcome["dossier"]["repository_set"]["members"]),
            2,
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
                and path["result"]["schema"] == DRIVER_RESULT_SCHEMA
                for path in evidence["driver_paths"]
            )
        )
        self.assertTrue(evidence["hook"]["bootstrap_verified"])
        self.assertEqual(
            evidence["hook"]["codex_new_task_pickup"], "manual-unverified"
        )
        self.assertTrue(evidence["process_model"]["fresh_subprocess_per_command"])


if __name__ == "__main__":
    unittest.main()
