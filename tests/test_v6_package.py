"""V6 package validation covers candidate-owned delivery semantics."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_package import validate


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".codebase-memory", ".pytest_cache", "__pycache__"}
    return set(names) & ignored


class V6PackageValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.candidate = Path(self.temporary.name) / "candidate with spaces"
        shutil.copytree(ROOT, self.candidate, ignore=_ignore)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_error_contains(self, result: dict, fragment: str) -> None:
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(fragment in error for error in result["errors"]),
            result["errors"],
        )

    def test_current_candidate_is_valid(self) -> None:
        self.assertEqual(validate(self.candidate)["errors"], [])

    def test_shipped_candidate_excludes_host_local_tooling_metadata(self) -> None:
        (self.candidate / "pyproject.toml").unlink()
        (self.candidate / "uv.lock").unlink()
        self.assertEqual(validate(self.candidate)["errors"], [])

    def test_missing_hook_bootstrap_is_reported(self) -> None:
        (self.candidate / "hooks" / "dev_flow_hook.py").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn("missing hooks/dev_flow_hook.py", result["errors"])

    def test_non_executable_launcher_is_reported(self) -> None:
        launcher = self.candidate / "scripts" / "dev_flow_python_launcher"
        launcher.chmod(stat.S_IRUSR | stat.S_IWUSR)
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn(
            "scripts/dev_flow_python_launcher is not executable",
            result["errors"],
        )

    def test_hook_bootstrap_must_identify_v6(self) -> None:
        hook = self.candidate / "hooks" / "dev_flow_hook.py"
        current = hook.read_text(encoding="utf-8")
        self.assertIn("V6 Hook", current)
        hook.write_text(current.replace("V6 Hook", "V5 Hook"), encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "hooks/dev_flow_hook.py does not identify V6",
        )

    def test_stale_public_selector_is_reported(self) -> None:
        for name in ("README.md", "README_CN.md"):
            with self.subTest(name=name):
                readme = self.candidate / name
                original = readme.read_text(encoding="utf-8")
                readme.write_text(original + "\nUse lite@5.\n", encoding="utf-8")
                result = validate(self.candidate)
                self.assertFalse(result["ok"])
                self.assertIn(
                    "stale public workflow selector remains: " + name,
                    result["errors"],
                )
                readme.write_text(original, encoding="utf-8")

    def test_missing_canonical_chinese_readme_is_reported(self) -> None:
        (self.candidate / "README_CN.md").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn("missing README_CN.md", result["errors"])

    def test_missing_roadmap_is_reported(self) -> None:
        (self.candidate / "ROADMAP.md").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn("missing ROADMAP.md", result["errors"])

    def test_missing_chinese_roadmap_is_reported(self) -> None:
        (self.candidate / "ROADMAP_CN.md").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn("missing ROADMAP_CN.md", result["errors"])

    def test_foreign_candidate_uses_its_own_workflow(self) -> None:
        workflow = self.candidate / "workflows" / "lite.yaml"
        workflow.write_text("schema: [\n", encoding="utf-8")
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(
                "built-in workflow 'lite' failed to load" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_required_workflow_assets_are_derived_from_candidate_catalog(self) -> None:
        product = self.candidate / "src" / "dev_flow_orchestrator" / "product.py"
        original = product.read_text(encoding="utf-8")
        changed = original.replace(
            '    "refactor",\n',
            '    "portfolio-probe",\n',
        )
        self.assertNotEqual(changed, original)
        product.write_text(changed, encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(result, "missing workflows/portfolio-probe.yaml")

    def test_workflow_assets_must_exactly_match_candidate_catalog(self) -> None:
        extra = self.candidate / "workflows" / "unlisted.yaml"
        extra.write_text(
            (self.candidate / "workflows" / "lite.yaml").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "workflow assets differ from product.WORKFLOW_IDS",
        )

    def test_official_workflow_requires_typed_artifacts(self) -> None:
        workflow = self.candidate / "workflows" / "investigation.yaml"
        original = workflow.read_text(encoding="utf-8")
        changed = original.replace(
            "    artifact: {type: repository-baseline, workspace: produces-source, inputs: []}\n",
            "",
            1,
        )
        self.assertNotEqual(changed, original)
        workflow.write_text(changed, encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "workflow-v2 action nodes must declare artifact",
        )

    def test_official_assurance_requires_exhausted_route(self) -> None:
        workflow = self.candidate / "workflows" / "lite.yaml"
        original = workflow.read_text(encoding="utf-8")
        changed = original.replace(
            "      exhausted: {node: finalize_verification_incomplete, status: FINALIZING}\n",
            "",
            1,
        )
        self.assertNotEqual(changed, original)
        workflow.write_text(changed, encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(result, "rework.exhausted is required")

    def test_optional_driver_requires_fallback_and_produced_type(self) -> None:
        workflow = self.candidate / "workflows" / "feature.yaml"
        original = workflow.read_text(encoding="utf-8")
        fallback = next(
            line for line in original.splitlines(keepends=True) if "fallback:" in line
        )
        workflow.write_text(original.replace(fallback, "", 1), encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "workflow 'feature' node impact driver contract is invalid",
        )

    def test_non_cancelled_terminal_requires_delivery_dossier(self) -> None:
        workflow = self.candidate / "workflows" / "lite.yaml"
        original = workflow.read_text(encoding="utf-8")
        changed = original.replace(
            "      type: delivery-dossier\n",
            "      type: delivery-summary\n",
            1,
        )
        self.assertNotEqual(changed, original)
        workflow.write_text(changed, encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "delivery.finalize must produce artifact type delivery-dossier",
        )

    def test_manifest_rejects_unsupported_hook_field(self) -> None:
        manifest_path = self.candidate / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["hooks"] = "./hooks/hooks.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "plugin manifest contains unsupported field(s): hooks",
        )

    def test_lock_version_must_match_manifest_cachebuster(self) -> None:
        lock = self.candidate / "uv.lock"
        current = lock.read_text(encoding="utf-8")
        lock.write_text(
            current.replace("6.0.0+codex.", "6.0.1+codex.", 1),
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assert_error_contains(result, "manifest and uv.lock versions differ")

    def test_snapshot_pure_module_rejects_os_io(self) -> None:
        snapshot = (
            self.candidate / "src" / "dev_flow_orchestrator" / "snapshot.py"
        )
        snapshot.write_text(
            snapshot.read_text(encoding="utf-8")
            + "\n\ndef _forbidden_probe():\n    return os.stat('.')\n",
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "snapshot.py uses forbidden infrastructure API os.stat",
        )

    def test_impact_skill_common_driver_envelope_is_valid(self) -> None:
        result = validate(self.candidate)
        impact_errors = [
            error
            for error in result["errors"]
            if error.startswith("analyze-change-impact Skill")
        ]
        self.assertEqual(impact_errors, [])

    def test_impact_skill_requires_common_driver_envelope_fields(self) -> None:
        skill = self.candidate / "skills" / "analyze-change-impact" / "SKILL.md"
        current = skill.read_text(encoding="utf-8")
        changed = current.replace('  "tool": "codebase-memory",\n', "", 1)
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "analyze-change-impact Skill has no valid common driver_result envelope",
        )

    def test_impact_skill_requires_tool_report_inside_details(self) -> None:
        skill = self.candidate / "skills" / "analyze-change-impact" / "SKILL.md"
        current = skill.read_text(encoding="utf-8")
        changed = current.replace(
            '    "schema": "dev-flow-impact-report/v1",\n',
            '    "schema": "impact-summary/v1",\n',
            1,
        )
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "analyze-change-impact Skill does not place a complete impact report "
            "in driver_result.details",
        )

    def test_impact_skill_requires_details_placement_guidance(self) -> None:
        skill = self.candidate / "skills" / "analyze-change-impact" / "SKILL.md"
        current = skill.read_text(encoding="utf-8")
        changed = current.replace("driver_result.details", "driver_result payload")
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "analyze-change-impact Skill does not explain "
            "driver_result.details placement",
        )

    def test_bilingual_docs_require_v5_rollback_language(self) -> None:
        readme = self.candidate / "README_CN.md"
        current = readme.read_text(encoding="utf-8")
        self.assertIn("回滚", current)
        readme.write_text(current.replace("回滚", "恢复旧版"), encoding="utf-8")
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "README_CN.md 缺少阶段 1 或 V5 兼容性说明",
        )

    def test_main_skill_requires_delivery_dossier_guidance(self) -> None:
        skill = self.candidate / "skills" / "follow-dev-flow" / "SKILL.md"
        current = skill.read_text(encoding="utf-8")
        self.assertIn("Delivery Dossier", current)
        skill.write_text(
            current.replace("Delivery Dossier", "delivery summary"),
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "follow-dev-flow Skill is missing V6 delivery guidance",
        )

    def test_stale_main_skill_agent_guidance_is_reported(self) -> None:
        metadata = (
            self.candidate
            / "skills"
            / "follow-dev-flow"
            / "agents"
            / "openai.yaml"
        )
        current = metadata.read_text(encoding="utf-8")
        stale_variants = (
            current.replace("V6", "V5"),
            current.replace("单个 Git 仓库", "单仓库或多仓库"),
        )
        for stale in stale_variants:
            with self.subTest(stale=stale):
                self.assertNotEqual(stale, current)
                metadata.write_text(stale, encoding="utf-8")
                result = validate(self.candidate)
                self.assert_error_contains(
                    result,
                    "follow-dev-flow agent metadata contains a stale generation "
                    "or multi-repository claim",
                )

    def test_main_skill_default_prompt_invokes_skill(self) -> None:
        metadata = (
            self.candidate
            / "skills"
            / "follow-dev-flow"
            / "agents"
            / "openai.yaml"
        )
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                "$follow-dev-flow", "follow-dev-flow"
            ),
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn(
            "follow-dev-flow default_prompt does not invoke $follow-dev-flow",
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
