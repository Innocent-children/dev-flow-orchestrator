"""Focused acceptance tests for the installed MCP STDIO journey."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TESTS))

from scripts import manage_runtime
from scripts import validate_installed_stage1 as acceptance
from support import (
    assert_hermetic_subprocess_env,
    hermetic_subprocess_env,
    probe_subprocess_runtime_roots,
)


RUNNER = ROOT / "scripts" / "validate_installed_stage1.py"
SOURCE_LAUNCHER = ROOT / "scripts" / "dev_flow_mcp.py"
LEGACY_RELEASE_COMMIT = "38685bf09e934ba5c97ea61112110beedb7083ca"
LAUNCHER_PLACEHOLDER = "__DEV_FLOW_RUNTIME_PYTHON__"
CANDIDATE_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".venv",
    ".codebase-memory",
    ".idea",
    ".qoder",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    ".DS_Store",
    "__pycache__",
    "*.py[cod]",
    "htmlcov",
    "work",
)


def _git(repository: Path, *arguments: str) -> str:
    environment = hermetic_subprocess_env(repository.parent)
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class InstalledMCPJourneyTests(unittest.TestCase):
    def test_tree_digest_is_stable_and_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "asset.txt"
            path.write_text("one\n", encoding="utf-8")
            first = acceptance._tree_digest(root)
            self.assertEqual(first, acceptance._tree_digest(root))
            path.write_text("two\n", encoding="utf-8")
            self.assertNotEqual(first, acceptance._tree_digest(root))

    def test_missing_launcher_fails_with_canonical_json_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = hermetic_subprocess_env(root)
            probe_subprocess_runtime_roots(root, environment)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--plugin-root",
                    str(ROOT),
                    "--launcher",
                    str(ROOT / "missing-dev-flow-mcp"),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        evidence = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(evidence["ok"])
        self.assertEqual(evidence["schema"], acceptance.EVIDENCE_SCHEMA)
        self.assertTrue(evidence["errors"])

    def _run_full_journey(
        self,
        *,
        plugin_root: Path,
        python_executable: Path,
        launcher: Path | None,
        environment: dict[str, str] | None = None,
        environment_root: Path | None = None,
        interpreter_arguments: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        temporary_parent = None if environment_root is None else str(environment_root)
        with tempfile.TemporaryDirectory(dir=temporary_parent) as temporary:
            fixture_root = (
                Path(temporary).resolve()
                if environment_root is None
                else environment_root.resolve()
            )
            if environment is None:
                child_environment = hermetic_subprocess_env(fixture_root)
            else:
                child_environment = dict(environment)
                assert_hermetic_subprocess_env(fixture_root, child_environment)
            roots = probe_subprocess_runtime_roots(fixture_root, child_environment)
            self.assertTrue(roots["data"].is_relative_to(fixture_root))
            self.assertTrue(roots["runtime"].is_relative_to(fixture_root))
            archived = subprocess.run(
                ["git", "archive", "--format=tar", LEGACY_RELEASE_COMMIT],
                cwd=ROOT,
                env=child_environment,
                capture_output=True,
                check=True,
            ).stdout
            legacy_root = Path(temporary) / "legacy 0.4.2 artifact"
            legacy_root.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archived), mode="r:") as archive:
                archive.extractall(legacy_root)
            legacy_manifest = json.loads(
                (legacy_root / ".codex-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(legacy_manifest["version"], "0.4.2")
            command = [
                str(python_executable),
                *interpreter_arguments,
                str(plugin_root / "scripts" / "validate_installed_stage1.py"),
                "--plugin-root",
                str(plugin_root),
                "--legacy-cli-root",
                str(legacy_root),
            ]
            if launcher is not None:
                command.extend(("--launcher", str(launcher)))
            completed = subprocess.run(
                command,
                cwd=plugin_root,
                env=child_environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
        return completed

    def _assert_full_journey_evidence(
        self,
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        self.assertNotIn("Fatal Python error", completed.stderr)
        try:
            evidence = json.loads(completed.stdout)
        except ValueError as exc:
            self.fail(
                "installed runner returned invalid JSON: {} ({})".format(
                    completed.stdout[-2048:], exc
                )
            )
        self.assertEqual(completed.returncode, 0, evidence.get("errors") or completed.stderr)
        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["plugin_digest_before"], evidence["plugin_digest_after"])
        journey = evidence["journey"]
        self.assertEqual(journey["initialize"]["server"], "dev-flow")
        self.assertEqual(journey["initialize"]["release"], "0.5.0")
        self.assertEqual(len(journey["initialize"]["instructions_sha256"]), 64)
        self.assertEqual(tuple(journey["catalog"]), acceptance.EXPECTED_TOOLS)
        self.assertTrue(journey["read_smoke"])
        self.assertTrue(journey["mutation_smoke"])
        self.assertTrue(journey["secondary_member_resume"])
        self.assertTrue(journey["restart_resume"])
        self.assertTrue(journey["disconnect_recovery"]["response_lost_after_commit"])
        self.assertFalse(journey["disconnect_recovery"]["blind_mutation_replay"])
        self.assertEqual(journey["disconnect_recovery"]["authoritative_revision"], 1)
        self.assertEqual(
            journey["disconnect_recovery"]["next_action_after_restart"],
            "impact.record",
        )
        self.assertTrue(journey["executor_source_reads"]["instrumented"])
        self.assertEqual(journey["executor_source_reads"]["forbidden_reads"], [])
        by_workflow = {
            (item["workflow"], item["route"]): item
            for item in journey["official_workflows"]
        }
        self.assertEqual(
            set(by_workflow),
            {
                (workflow, route)
                for workflow in acceptance.OFFICIAL_WORKFLOWS
                for route in ("focused", "closed-trigger")
            },
        )
        for (workflow, route), item in by_workflow.items():
            with self.subTest(workflow=workflow, route=route):
                self.assertEqual(item["terminal_status"], "DONE")
                self.assertEqual(item["dossier"]["schema"], acceptance.DOSSIER_SCHEMA)
                self.assertTrue(
                    acceptance.EXPECTED_OBLIGATIONS[workflow].issubset(
                        set(item["obligation_kinds"])
                    )
                )
                self.assertEqual(
                    item["allowance"], acceptance.EXPECTED_ALLOWANCE[workflow]
                )
                authority = item["assurance_authority"]
                self.assertEqual(authority["profile"], workflow)
                not_required = authority["not_required"]
                self.assertEqual(
                    set(not_required),
                    {
                        "documentation",
                        "independent_review",
                        "integration",
                        "manual_evidence",
                        "repository_ids",
                        "rule",
                    },
                )
                self.assertEqual(
                    not_required["rule"],
                    "closed-policy-profile-impact-and-risk-derivation",
                )
                observed = set(item["obligation_kinds"])
                self.assertEqual(
                    not_required["documentation"],
                    "documentation-check" not in observed,
                )
                self.assertEqual(
                    not_required["independent_review"],
                    "independent-review" not in observed,
                )
                self.assertTrue(not_required["integration"])
                self.assertEqual(
                    not_required["manual_evidence"],
                    "manual-evidence" not in observed,
                )
                self.assertEqual(
                    len(not_required["repository_ids"]),
                    0 if "repository-check" in observed else item["repository_count"],
                )
                self.assertEqual(
                    set(authority["ceilings"]),
                    {"verification", "review", "rework", "total_action"},
                )
                self.assertEqual(
                    item["driver_observations"]["codebase_memory"]["tool"],
                    "codebase-memory",
                )
                if route == "closed-trigger":
                    self.assertIn("independent-review", item["obligation_kinds"])
        feature_closed = by_workflow[("feature", "closed-trigger")]
        self.assertTrue(feature_closed["scenario_evidence"]["openspec_stale_seen"])
        self.assertTrue(
            feature_closed["scenario_evidence"]["impact_gap_replanned"]
        )
        self.assertTrue(
            feature_closed["scenario_evidence"]["impact_observed_current"]
        )
        self.assertEqual(
            feature_closed["scenario_evidence"]["plan_blocked"], "AMBIENT_DRIFT"
        )
        self.assertTrue(
            feature_closed["scenario_evidence"]["restored_for_replan"]
        )
        self.assertTrue(
            feature_closed["scenario_evidence"]["implementation_reexecuted"]
        )
        bugfix_closed = by_workflow[("bugfix", "closed-trigger")]
        self.assertTrue(bugfix_closed["scenario_evidence"]["review_waived"])
        full_closed = by_workflow[("full", "closed-trigger")]
        self.assertTrue(full_closed["scenario_evidence"]["finding_disposed"])
        lite_closed = by_workflow[("lite", "closed-trigger")]
        self.assertEqual(
            lite_closed["scenario_evidence"]["finding_relations"],
            ["introduced", "affected"],
        )
        self.assertTrue(lite_closed["scenario_evidence"]["review_rework_seen"])
        legacy = journey["legacy_cli_resume"]
        self.assertEqual(legacy["release"], "0.4.2")
        self.assertEqual(legacy["model"], "0.4.0")
        self.assertTrue(legacy["discovered_by_mcp"])
        self.assertFalse(legacy["state_migration"])
        self.assertEqual(legacy["terminal_status"], "DONE")
        self.assertEqual(legacy["dossier"]["schema"], acceptance.DOSSIER_SCHEMA)
        revision = journey["contract_revision"]
        self.assertEqual(revision["reentered"], "impact")
        self.assertEqual(
            revision["adopted_paths"], ["ambient-adopted.txt", "journey-plan.md"]
        )
        self.assertEqual(revision["terminal_status"], "DONE")
        self.assertEqual(revision["dossier"]["schema"], acceptance.DOSSIER_SCHEMA)
        self.assertEqual(
            journey["corrupt_inventory"]["error_code"],
            "LEASE_INVENTORY_INVALID",
        )
        self.assertFalse(journey["corrupt_inventory"]["partial_task_created"])
        self.assertTrue(journey["linked_worktrees"]["shared_git_common_dir"])
        self.assertTrue(
            journey["linked_worktrees"]["distinct_worktree_memberships"]
        )
        self.assertEqual(
            len(journey["linked_worktrees"]["public_mcp_admissions"]), 2
        )
        exact_set = journey["exact_set_lite"]
        self.assertEqual(exact_set["repository_count"], 2)
        self.assertEqual(exact_set["terminal_status"], "DONE")
        self.assertEqual(exact_set["dossier"]["schema"], acceptance.DOSSIER_SCHEMA)
        self.assertEqual(journey["terminal_status"], "DONE")

    @unittest.skipUnless(
        sys.platform == "darwin",
        "installed launcher journey currently runs on macOS",
    )
    def test_real_stdio_source_launcher_exercises_installed_harness_journeys(
        self,
    ) -> None:
        completed = self._run_full_journey(
            plugin_root=ROOT,
            python_executable=Path(sys.executable),
            launcher=SOURCE_LAUNCHER,
        )
        self._assert_full_journey_evidence(completed)

    @unittest.skipUnless(
        sys.platform == "darwin",
        "managed installed launcher journey currently runs on macOS",
    )
    def test_managed_runtime_path_launcher_exercises_full_installed_journey(
        self,
    ) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is required for managed-runtime integration")

        with tempfile.TemporaryDirectory(
            prefix="dev-flow-managed-installed-journey-"
        ) as temporary:
            base = Path(temporary)
            candidate = base / "candidate source with spaces"
            shutil.copytree(ROOT, candidate, ignore=CANDIDATE_COPY_IGNORE)

            _git(candidate, "init", "-q")
            _git(candidate, "config", "user.name", "Managed Journey Test")
            _git(
                candidate,
                "config",
                "user.email",
                "managed-journey@example.invalid",
            )
            _git(candidate, "add", "--all")
            _git(
                candidate,
                "-c",
                "commit.gpgSign=false",
                "commit",
                "-qm",
                "managed installed candidate",
            )
            source_commit = _git(candidate, "rev-parse", "HEAD")
            self.assertEqual(len(source_commit), 40)
            self.assertEqual(_git(candidate, "status", "--porcelain"), "")

            runtime_root = base / "managed runtime with spaces 雪's"
            data_root = base / "task data"
            data_root.mkdir()
            build_environment = hermetic_subprocess_env(base)
            probe_subprocess_runtime_roots(base, build_environment)
            with mock.patch.dict(os.environ, build_environment, clear=True):
                built = manage_runtime.build(
                    candidate,
                    runtime_root,
                    source_commit,
                    data_root,
                )
            self.assertTrue(built["ok"])
            self.assertFalse(built["reused"])
            self.assertEqual(built["receipt"]["source_commit"], source_commit)
            self.assertEqual(
                _git(candidate, "rev-parse", "HEAD"),
                built["receipt"]["source_commit"],
            )
            self.assertEqual(_git(candidate, "status", "--porcelain"), "")

            runtime_python = (
                Path(built["runtime_dir"]) / "venv" / "bin" / "python"
            )
            self.assertTrue(runtime_python.is_file())
            bin_dir = base / "native bin"
            bin_dir.mkdir()
            launcher = bin_dir / "dev-flow-mcp"
            template_text = (
                candidate / "scripts" / "dev_flow_mcp_launcher"
            ).read_text(encoding="utf-8")
            self.assertEqual(template_text.count(LAUNCHER_PLACEHOLDER), 1)
            launcher_text = template_text.replace(
                LAUNCHER_PLACEHOLDER,
                shlex.quote(str(runtime_python)),
                1,
            )
            self.assertNotIn(LAUNCHER_PLACEHOLDER, launcher_text)
            self.assertNotIn("dev_flow_mcp.py", launcher_text)
            launcher.write_text(launcher_text, encoding="utf-8")
            launcher.chmod(0o755)

            environment = hermetic_subprocess_env(
                base,
                path_entries=(bin_dir,),
            )
            self.assertEqual(
                shutil.which("dev-flow-mcp", path=environment["PATH"]),
                str(launcher),
            )
            completed = self._run_full_journey(
                plugin_root=candidate,
                python_executable=runtime_python,
                launcher=None,
                environment=environment,
                environment_root=base,
                interpreter_arguments=("-I",),
            )

        self._assert_full_journey_evidence(completed)


if __name__ == "__main__":
    unittest.main()
