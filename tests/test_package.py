"""Current package validation covers candidate-owned delivery semantics."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.product import IMPACT_REPORT_SCHEMA, PRODUCT_VERSION
from scripts.validate_package import validate


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".codebase-memory", ".pytest_cache", "__pycache__"}
    return set(names) & ignored


class PackageValidationTests(unittest.TestCase):
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

    def test_hook_bootstrap_must_identify_current_version(self) -> None:
        hook = self.candidate / "hooks" / "dev_flow_hook.py"
        current = hook.read_text(encoding="utf-8")
        current_label = "Dev Flow {} Hook".format(PRODUCT_VERSION)
        self.assertIn(current_label, current)
        hook.write_text(
            current.replace(current_label, "unversioned Hook"),
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assert_error_contains(
            result,
            "hooks/dev_flow_hook.py does not identify the current product version",
        )

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
            "current workflow action nodes must declare artifact",
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

    def test_official_workflow_cancellation_is_stage_declared(self) -> None:
        workflow = self.candidate / "workflows" / "lite.yaml"
        original = workflow.read_text(encoding="utf-8")
        changed = original.replace(
            "  stages: [preflight, impact, implement, verify, verification_rework]\n",
            "  stages: [preflight, finalize_success]\n",
            1,
        )
        self.assertNotEqual(changed, original)
        workflow.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "does not expose stage-declared cancellation for most normal stages",
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

    def test_lock_version_must_match_manifest_version(self) -> None:
        lock = self.candidate / "uv.lock"
        current = lock.read_text(encoding="utf-8")
        lock.write_text(
            current.replace(
                'version = "{}"'.format(PRODUCT_VERSION),
                'version = "unsupported"',
                1,
            ),
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
            '    "schema": "{}",\n'.format(IMPACT_REPORT_SCHEMA),
            '    "schema": "dev-flow-impact-report/unsupported",\n',
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
            "follow-dev-flow Skill is missing current-version delivery guidance",
        )

    def test_main_skill_requires_mismatch_authorization_guidance(self) -> None:
        skill = self.candidate / "skills" / "follow-dev-flow" / "SKILL.md"
        current = skill.read_text(encoding="utf-8")
        mismatch_authorization = (
            "request\n"
            "   explicit user authorization and stop for the decision."
        )
        self.assertEqual(current.count(mismatch_authorization), 1)
        changed = current.replace(
            mismatch_authorization,
            "continue without an operator decision.",
            1,
        )
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "follow-dev-flow Skill does not close confirmed repository mismatches",
        )

    def test_main_skill_requires_mismatch_terminal_verification(self) -> None:
        skill = self.candidate / "skills" / "follow-dev-flow" / "SKILL.md"
        current = skill.read_text(encoding="utf-8")
        changed = current.replace("`status: CANCELLED`", "`status: stopped`")
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "follow-dev-flow Skill does not close confirmed repository mismatches",
        )

    def test_main_skill_requires_mismatch_no_git_mutation_boundary(self) -> None:
        skill = self.candidate / "skills" / "follow-dev-flow" / "SKILL.md"
        current = skill.read_text(encoding="utf-8")
        changed = current.replace(
            "stash, reset, clean, checkout",
            "stash or checkout",
        )
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "follow-dev-flow Skill does not close confirmed repository mismatches",
        )

    def test_one_repository_only_main_skill_agent_guidance_is_reported(self) -> None:
        metadata = (
            self.candidate
            / "skills"
            / "follow-dev-flow"
            / "agents"
            / "openai.yaml"
        )
        current = metadata.read_text(encoding="utf-8")
        changed = current.replace(
            "在一至八个精确仓库工作树中",
            "在当前一个 Git 仓库中",
        )
        self.assertNotEqual(changed, current)
        metadata.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "follow-dev-flow agent metadata does not use the current exact-set version",
        )

    def test_repository_topology_authority_is_validated(self) -> None:
        product = self.candidate / "src" / "dev_flow_orchestrator" / "product.py"
        current = product.read_text(encoding="utf-8")
        changed = current.replace("MAX_REPOSITORY_COUNT = 8", "MAX_REPOSITORY_COUNT = 7")
        self.assertNotEqual(changed, current)
        product.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "product repository-topology authority is invalid",
        )

    def test_cli_must_retain_repeatable_repository_selection(self) -> None:
        cli = self.candidate / "src" / "dev_flow_orchestrator" / "cli.py"
        current = cli.read_text(encoding="utf-8")
        changed = current.replace('action="append"', 'action="store"', 1)
        self.assertNotEqual(changed, current)
        cli.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "src/dev_flow_orchestrator/cli.py is not wired to the "
            "repository-topology authority",
        )

    def test_installed_validator_must_include_exact_set_journey(self) -> None:
        runner = self.candidate / "scripts" / "validate_installed_stage1.py"
        current = runner.read_text(encoding="utf-8")
        changed = current.replace(
            "exact-set-secondary-resume-drift-resources-dossier",
            "one-repository-only",
            1,
        )
        self.assertNotEqual(changed, current)
        runner.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "installed validation does not prove the exact-set journeys",
        )

    def test_installed_validator_must_include_exact_set_lite_journey(self) -> None:
        runner = self.candidate / "scripts" / "validate_installed_stage1.py"
        current = runner.read_text(encoding="utf-8")
        changed = current.replace(
            "exact-set-lite-success-dossier",
            "one-repository-lite-only",
            1,
        )
        self.assertNotEqual(changed, current)
        runner.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "installed validation does not prove the exact-set journeys",
        )

    def test_positive_later_stage_claim_is_not_hidden_by_existing_negation(self) -> None:
        claims = {
            "README.md": "The controller automatically creates branches.",
            "README_CN.md": "控制器支持协调并行 Agent。",
        }
        for relative, claim in claims.items():
            with self.subTest(relative=relative):
                path = self.candidate / relative
                original = path.read_text(encoding="utf-8")
                path.write_text(original + "\n" + claim + "\n", encoding="utf-8")
                self.assert_error_contains(
                    validate(self.candidate),
                    "unsupported later-stage product claim remains: " + relative,
                )
                path.write_text(original, encoding="utf-8")

        manifest_path = self.candidate / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("never", manifest["interface"]["longDescription"].lower())
        manifest["interface"]["defaultPrompt"].append(
            "The controller runs repositories in parallel."
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "plugin manifest claims unsupported later-stage product behavior",
        )

    def test_all_current_product_surfaces_reject_version_coded_content(self) -> None:
        generation_marker = "V" + "6"
        component_marker = "v" + "2"
        text_assets = (
            ("src/dev_flow_orchestrator/git_client.py", generation_marker),
            ("tests/test_yaml_subset.py", generation_marker),
            (".github/workflows/focused.yml", generation_marker),
            ("skills/review-dev-flow-change/SKILL.md", component_marker),
            ("hooks/dev_flow_hook.py", component_marker),
            ("scripts/validate_installed_stage1.py", generation_marker),
            ("README.md", component_marker),
            ("workflows/lite.yaml", component_marker),
            ("pyproject.toml", component_marker),
        )
        for relative, marker in text_assets:
            path = self.candidate / relative
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n# injected product generation: "
                + marker
                + "\n",
                encoding="utf-8",
            )

        manifest_path = self.candidate / ".codex-plugin" / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["description"] += " " + generation_marker
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        result = validate(self.candidate)
        checked_assets = tuple(relative for relative, _marker in text_assets) + (
            ".codex-plugin/plugin.json",
        )
        for relative in checked_assets:
            with self.subTest(relative=relative):
                self.assert_error_contains(
                    result,
                    "current product asset content contains version-coded "
                    "identifier: " + relative,
                )

    def test_current_product_asset_paths_reject_component_coded_versions(self) -> None:
        component_marker = "v" + "2"
        relative = "tests/test_{}_probe.py".format(component_marker)
        path = self.candidate / relative
        path.write_text("# temporary path probe\n", encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "current product asset path contains version-coded identifier: "
            + relative,
        )

    def test_current_product_assets_reject_non_current_numeric_schema(self) -> None:
        numeric_version = ".".join(("0", "1", "0"))
        schema = "dev-flow-agent/" + numeric_version
        readme = self.candidate / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8")
            + "\nTemporary schema probe: `"
            + schema
            + "`.\n",
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "current product asset contains non-current dev-flow numeric schema: "
            "README.md",
        )

    def test_historical_openspec_assets_are_outside_version_scan(self) -> None:
        generation_marker = "V" + "6"
        numeric_version = ".".join(("0", "1", "0"))
        archive = (
            self.candidate
            / "openspec"
            / "changes"
            / "archive"
            / ("historical-" + generation_marker)
            / "spec.md"
        )
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(
            generation_marker + " dev-flow-agent/" + numeric_version + "\n",
            encoding="utf-8",
        )
        self.assertEqual(validate(self.candidate)["errors"], [])

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
