"""Current package validation covers candidate-owned delivery semantics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.product import IMPACT_REPORT_SCHEMA, MODEL_VERSION, RELEASE_VERSION
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

    def test_patch_release_keeps_current_model_candidate_valid(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(self.candidate / "scripts" / "bump_version.py"),
                "--root",
                str(self.candidate),
                "0.4.1",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(validate(self.candidate)["errors"], [])

    def test_candidate_requires_project_metadata_and_exact_dependency_lock(self) -> None:
        for relative in ("pyproject.toml", "uv.lock"):
            path = self.candidate / relative
            preserved = path.read_bytes()
            path.unlink()
            self.assert_error_contains(validate(self.candidate), "missing " + relative)
            path.write_bytes(preserved)

    def test_missing_mcp_runtime_builder_is_reported(self) -> None:
        (self.candidate / "scripts" / "manage_runtime.py").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn(
            "pre-import candidate is missing scripts/manage_runtime.py",
            result["errors"],
        )

    def test_public_docs_semantics_reject_incomplete_windows_bootstrap(self) -> None:
        install = self.candidate / "scripts" / "install.ps1"
        install.write_text(
            install.read_text(encoding="utf-8").replace(
                "@DEV_FLOW_INDEX_SHA256@", "@REMOVED_INDEX_DIGEST@"
            ),
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate), "Windows release bootstrap template is incomplete"
        )

    def test_release_bootstraps_reject_checkout_dependencies(self) -> None:
        install = self.candidate / "scripts" / "install.ps1"
        install.write_text(
            install.read_text(encoding="utf-8") + "\ngit fetch --ff-only\n",
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate), "scripts/install.ps1 depends on a Git checkout"
        )

    def test_uninstaller_rejects_checkout_era_keep_source_interface(self) -> None:
        uninstall = self.candidate / "scripts" / "uninstall.ps1"
        uninstall.write_text(
            uninstall.read_text(encoding="utf-8") + "\nparam([switch]$KeepSource)\n",
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate), "retains the checkout-era KeepSource interface"
        )

    def test_ci_runs_full_discovery_once_and_keeps_matrix_lightweight(self) -> None:
        workflow = self.candidate / ".github" / "workflows" / "focused.yml"
        source = workflow.read_text(encoding="utf-8")
        discovery = 'uv run python -m unittest discover -s tests -p "test_*.py"'
        workflow.write_text(source + "\n      - run: " + discovery + "\n", encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate), "full unittest discovery exactly once"
        )

    def test_preimport_gate_requires_artifact_receipt_and_dispatcher_contracts(self) -> None:
        probes = (
            ("scripts/release_artifact.py", "dev-flow-release-index/1.0.0"),
            ("scripts/runtime_integrity.py", "dev-flow-runtime-receipt/3.0.0"),
            ("scripts/stable_dispatcher.py", "uninstall_driver_sha256"),
        )
        for relative, token in probes:
            with self.subTest(relative=relative):
                path = self.candidate / relative
                original = path.read_text(encoding="utf-8")
                changed = original.replace(token, "removed-contract-token")
                self.assertNotEqual(changed, original)
                path.write_text(changed, encoding="utf-8")
                self.assert_error_contains(
                    validate(self.candidate),
                    "pre-import candidate source is incomplete: " + relative,
                )
                path.write_text(original, encoding="utf-8")

    def test_public_docs_semantics_reject_unsupported_standalone_provisioning(self) -> None:
        install = self.candidate / "INSTALL.md"
        install.write_text(
            install.read_text(encoding="utf-8") + "\n    codex mcp add dev-flow -- dev-flow-mcp --stdio\n",
            encoding="utf-8",
        )
        self.assert_error_contains(validate(self.candidate), "documents unsupported standalone provisioning")

    def test_public_docs_semantics_reject_nonexistent_installer_parameter(self) -> None:
        readme = self.candidate / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nUse `--standalone`.\n", encoding="utf-8")
        self.assert_error_contains(validate(self.candidate), "unsupported installer parameter --standalone")

    def test_public_docs_semantics_reject_language_mode_divergence(self) -> None:
        install = self.candidate / "INSTALL_CN.md"
        install.write_text(
            install.read_text(encoding="utf-8").replace("不受支持", "完全受支持"),
            encoding="utf-8",
        )
        self.assert_error_contains(validate(self.candidate), "disagree on bundled-only support")

    def test_public_docs_semantics_reject_obsolete_hook_authority(self) -> None:
        readme = self.candidate / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\nHook trust is the product authority.\n",
            encoding="utf-8",
        )
        self.assert_error_contains(validate(self.candidate), "restores obsolete Hook authority")

    def test_public_docs_semantics_require_legacy_checkout_preservation(self) -> None:
        install = self.candidate / "INSTALL.md"
        install.write_text(
            install.read_text(encoding="utf-8")
            .replace("every legacy checkout", "all predecessor material")
            .replace("The legacy source checkout remains untouched and retained", "The predecessor is unspecified"),
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate), "missing legacy-checkout preservation guidance"
        )

    def test_stale_validation_report_cannot_become_current_authority(self) -> None:
        (self.candidate / "VALIDATION_REPORT.md").write_text("stale\n", encoding="utf-8")
        self.assert_error_contains(validate(self.candidate), "stale VALIDATION_REPORT.md")

    def test_public_docs_semantic_gate_rejects_an_early_return(self) -> None:
        validator = self.candidate / "scripts" / "validate_package.py"
        text = validator.read_text(encoding="utf-8")
        marker = 'def _validate_public_docs(root: Path, errors: list[str]) -> None:\n'
        validator.write_text(text.replace(marker, marker + "    return\n", 1), encoding="utf-8")
        self.assert_error_contains(validate(self.candidate), "semantic validation contains an early return")

    def test_preimport_gate_rejects_incomplete_mcp_before_candidate_execution(self) -> None:
        marker = self.candidate / "candidate-imported.marker"
        product = self.candidate / "src/dev_flow_orchestrator/product.py"
        product.write_text(
            product.read_text(encoding="utf-8")
            + "\n__import__('pathlib').Path({}).write_text('executed')\n".format(
                repr(str(marker))
            ),
            encoding="utf-8",
        )
        (self.candidate / "src/dev_flow_orchestrator/mcp/server.py").unlink()
        result = validate(self.candidate)
        self.assert_error_contains(result, "missing src/dev_flow_orchestrator/mcp/server.py")
        self.assertFalse(marker.exists(), result)

    def test_legacy_hook_or_skill_reintroduction_is_rejected(self) -> None:
        for relative in ("hooks/hooks.json", "skills/follow-dev-flow/SKILL.md"):
            path = self.candidate / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("legacy\n", encoding="utf-8")
            self.assert_error_contains(validate(self.candidate), "predecessor path remains:")
            path.unlink()

    def test_dev_flow_skill_files_are_required_before_candidate_imports(self) -> None:
        relative = "skills/dev-flow/references/activation-and-routing.md"
        (self.candidate / relative).unlink()
        self.assert_error_contains(
            validate(self.candidate),
            "pre-import candidate is missing " + relative,
        )

    def test_dev_flow_skill_frontmatter_is_closed(self) -> None:
        skill = self.candidate / "skills/dev-flow/SKILL.md"
        current = skill.read_text(encoding="utf-8")
        changed = current.replace(
            "description: Start, resume,",
            "metadata: unsupported\ndescription: Start, resume,",
            1,
        )
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "frontmatter must contain only name and description",
        )

    def test_dev_flow_skill_description_must_cover_implicit_matching(self) -> None:
        skill = self.candidate / "skills/dev-flow/SKILL.md"
        current = skill.read_text(encoding="utf-8")
        changed = current.replace(
            "substantive multi-step repository work",
            "repository work",
            1,
        )
        self.assertNotEqual(changed, current)
        skill.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "does not support explicit and implicit activation",
        )

    def test_dev_flow_skill_agent_rejects_an_unsupported_dependency(self) -> None:
        agent = self.candidate / "skills/dev-flow/agents/openai.yaml"
        agent.write_text(
            agent.read_text(encoding="utf-8") + "dependencies: {}\n",
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "without an MCP dependency",
        )

    def test_dev_flow_skill_cannot_define_a_parallel_protocol(self) -> None:
        skill = self.candidate / "skills/dev-flow/SKILL.md"
        skill.write_text(
            skill.read_text(encoding="utf-8")
            + "\n## Action catalog\n\n- implementation.record: write files\n",
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "duplicates Controller protocol authority",
        )

    def test_dev_flow_skill_guidance_is_closed_against_protocol_shaped_drift(self) -> None:
        cases = (
            (
                "skills/dev-flow/SKILL.md",
                "\n## Controller operations\n\n- implementation.record: write files\n",
            ),
            (
                "skills/dev-flow/SKILL.md",
                "\n- implementation.record\n- payload field: summary\n",
            ),
            (
                "skills/dev-flow/references/activation-and-routing.md",
                "\nConnect to https://example.invalid/dev-flow as a fallback.\n",
            ),
            (
                "skills/dev-flow/references/activation-and-routing.md",
                "\nCall `dev_flow_run_shell` to finish the action.\n",
            ),
        )
        for relative, addition in cases:
            with self.subTest(relative=relative, addition=addition.strip()):
                path = self.candidate / relative
                original = path.read_text(encoding="utf-8")
                try:
                    path.write_text(original + addition, encoding="utf-8")
                    self.assert_error_contains(
                        validate(self.candidate),
                        relative + " differs from its audited canonical guidance",
                    )
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_public_docs_reject_dev_flow_skill_semantic_drift(self) -> None:
        cases = (
            ("README.md", "$dev-flow", "$disabled-flow"),
            ("README_CN.md", "$dev-flow", "$disabled-flow"),
            ("INSTALL.md", "$dev-flow", "$disabled-flow"),
            ("INSTALL_CN.md", "$dev-flow", "$disabled-flow"),
            ("ARCHITECTURE.md", "$dev-flow", "$disabled-flow"),
            ("ARCHITECTURE_CN.md", "$dev-flow", "$disabled-flow"),
            ("README.md", "activate it implicitly", "activate it manually"),
            (
                "ARCHITECTURE_CN.md",
                'mcpServers: "./.mcp.json"',
                'mcpServers: "https://example.invalid"',
            ),
            (
                "INSTALL.md",
                "It does not authorize a mutation by itself",
                "It authorizes mutations by itself",
            ),
            (
                "INSTALL_CN.md",
                "installed-stage validator",
                "manual inspection",
            ),
        )
        for relative, expected, replacement in cases:
            with self.subTest(relative=relative, expected=expected):
                path = self.candidate / relative
                original = path.read_text(encoding="utf-8")
                changed = original.replace(expected, replacement)
                self.assertNotEqual(changed, original)
                try:
                    path.write_text(changed, encoding="utf-8")
                    self.assert_error_contains(
                        validate(self.candidate),
                        relative
                        + " is missing formal dev-flow Skill activation, "
                        "registration, authority, or installation evidence",
                    )
                finally:
                    path.write_text(original, encoding="utf-8")

    @unittest.skipIf(os.name == "nt", "POSIX executable bits are not a Windows contract")
    def test_non_executable_launcher_is_reported(self) -> None:
        for relative in (
            "scripts/dev_flow_python_launcher",
            "scripts/dev_flow_mcp_launcher",
        ):
            launcher = self.candidate / relative
            original_mode = launcher.stat().st_mode
            launcher.chmod(stat.S_IRUSR | stat.S_IWUSR)
            result = validate(self.candidate)
            self.assertFalse(result["ok"])
            self.assertIn(relative + " is not executable", result["errors"])
            launcher.chmod(original_mode)

    def test_mcp_interface_identity_is_release_neutral(self) -> None:
        identity = (self.candidate / "src/dev_flow_orchestrator/mcp/identity.py").read_text(encoding="utf-8")
        self.assertIn("MCP_INTERFACE_SCHEMA", identity)
        self.assertNotIn(RELEASE_VERSION, identity)

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

    def test_missing_chinese_install_guide_is_reported(self) -> None:
        (self.candidate / "INSTALL_CN.md").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn("missing INSTALL_CN.md", result["errors"])

    def test_chinese_web_ui_documentation_drift_is_reported(self) -> None:
        readme = self.candidate / "README_CN.md"
        current = readme.read_text(encoding="utf-8")
        readme.write_text(
            current.replace("只读 Web UI", "任务界面"),
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "README_CN.md is missing synchronized MCP-first product guidance",
        )

    def test_roadmap_must_keep_read_only_slice_scope(self) -> None:
        roadmap = self.candidate / "ROADMAP.md"
        current = roadmap.read_text(encoding="utf-8")
        roadmap.write_text(
            current.replace(
                "Full unittest discovery",
                "partial module list",
            ),
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "ROADMAP.md is missing synchronized MCP-first product guidance",
        )

    def test_roadmap_rejects_full_horizon_two_delivery_claim(self) -> None:
        roadmap = self.candidate / "ROADMAP.md"
        roadmap.write_text(
            roadmap.read_text(encoding="utf-8")
            .replace("native Windows", "cross-platform", 1),
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "ROADMAP.md is missing the bounded Windows integration guidance",
        )

    def test_docs_reject_web_ui_mutation_authority(self) -> None:
        install = self.candidate / "INSTALL_CN.md"
        install.write_text(
            install.read_text(encoding="utf-8") + "\nWeb UI 可以推进任务。\n",
            encoding="utf-8",
        )
        self.assert_error_contains(
            validate(self.candidate),
            "INSTALL_CN.md claims unsupported Web UI mutation authority",
        )

    def test_missing_web_ui_asset_is_reported(self) -> None:
        (self.candidate / "src/dev_flow_orchestrator/web_assets/app.js").unlink()
        self.assert_error_contains(validate(self.candidate), "missing Web UI asset app.js")

    def test_web_ui_runtime_rejects_third_party_dependency(self) -> None:
        web = self.candidate / "src/dev_flow_orchestrator/web.py"
        web.write_text("import flask\n" + web.read_text(encoding="utf-8"), encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "web.py imports non-standard runtime dependency flask",
        )

    def test_installed_evidence_must_include_mcp_read_journey(self) -> None:
        runner = self.candidate / "scripts/validate_installed_stage1.py"
        current = runner.read_text(encoding="utf-8")
        changed = current.replace('"read_smoke": True', '"read_smoke": False')
        self.assertNotEqual(changed, current)
        runner.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "installed evidence does not preserve the MCP STDIO observation boundary",
        )

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
            "pre-import plugin manifest is invalid",
        )

    def test_lock_version_must_match_manifest_version(self) -> None:
        lock = self.candidate / "uv.lock"
        current = lock.read_text(encoding="utf-8")
        lock.write_text(
            current.replace(
                'version = "{}"'.format(RELEASE_VERSION),
                'version = "unsupported"',
                1,
            ),
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assert_error_contains(result, "pre-import exact dependency lock is invalid")

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

    def test_mcp_guidance_catalog_covers_execution_classes(self) -> None:
        guidance = (self.candidate / "src/dev_flow_orchestrator/mcp/guidance.py").read_text(encoding="utf-8")
        for entry in (
            "preflight", "impact", "planning", "implementation", "investigation",
            "documentation", "rework", "assurance", "finalize", "cancel", "generic",
        ):
            self.assertIn('"{}":'.format(entry), guidance)
        self.assertIn("current and baseline codebase-memory projects separate", guidance)
        self.assertIn("Delivery Dossier", guidance)

    def test_mcp_guidance_rejects_positive_package_source_reading(self) -> None:
        guidance = self.candidate / "src/dev_flow_orchestrator/mcp/guidance.py"
        current = guidance.read_text(encoding="utf-8")
        changed = current.replace(
            "Do not read or edit Controller task-state files",
            "Read Controller state files",
            1,
        )
        self.assertNotEqual(changed, current)
        guidance.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "MCP guidance tells the model to read removed or raw runtime authority",
        )

    def test_mcp_guidance_catalog_omission_is_reported(self) -> None:
        guidance = self.candidate / "src/dev_flow_orchestrator/mcp/guidance.py"
        current = guidance.read_text(encoding="utf-8")
        changed = current.replace('    "impact": {', '    "impact-removed": {', 1)
        self.assertNotEqual(changed, current)
        guidance.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "MCP guidance action catalog is not closed and complete",
        )

    def test_mcp_metadata_annotations_and_first_excess_budgets_are_validated(self) -> None:
        tools = self.candidate / "src/dev_flow_orchestrator/mcp/tools.py"
        original_tools = tools.read_text(encoding="utf-8")
        changed = original_tools.replace(
            "READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)",
            "READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)",
            1,
        )
        self.assertNotEqual(changed, original_tools)
        tools.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "MCP descriptions, annotations, or task-support metadata are invalid",
        )
        tools.write_text(original_tools, encoding="utf-8")

        results = self.candidate / "src/dev_flow_orchestrator/mcp/results.py"
        original_results = results.read_text(encoding="utf-8")
        changed = original_results.replace(
            "MAX_TEXT_SUMMARY_BYTES = 4 * 1024",
            "MAX_TEXT_SUMMARY_BYTES = 4 * 1024 + 1",
            1,
        )
        self.assertNotEqual(changed, original_results)
        results.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "MCP context budget authority is invalid: src/dev_flow_orchestrator/mcp/results.py",
        )

    def test_openspec_development_artifacts_are_outside_package_validation(self) -> None:
        openspec = self.candidate / "openspec" / "changes" / "in-progress"
        openspec.mkdir(parents=True)
        (openspec / "traceability.json").write_text("not package metadata\n", encoding="utf-8")
        self.assertEqual(validate(self.candidate)["errors"], [])

    def test_manifest_registers_the_skill_and_mcp_companions(self) -> None:
        manifest = json.loads((self.candidate / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertFalse((self.candidate / "hooks").exists())
        self.assertEqual(
            sorted(
                path.relative_to(self.candidate).as_posix()
                for path in (self.candidate / "skills/dev-flow").rglob("*")
                if path.is_file()
            ),
            [
                "skills/dev-flow/SKILL.md",
                "skills/dev-flow/agents/openai.yaml",
                "skills/dev-flow/references/activation-and-routing.md",
            ],
        )

    def test_installed_validator_must_record_skill_and_mcp_evidence(self) -> None:
        runner = self.candidate / "scripts/validate_installed_stage1.py"
        current = runner.read_text(encoding="utf-8")
        changed = current.replace('"skill": None', '"skill": False', 1)
        self.assertNotEqual(changed, current)
        runner.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "installed validation does not prove the bundled dev-flow Skill and MCP registration",
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
            "dev_flow_find_tasks_for_path",
            "dev_flow_find_one_repository",
        )
        self.assertNotEqual(changed, current)
        runner.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "installed validation does not exercise the real MCP exact-set journey",
        )

    def test_installed_validator_must_include_exact_set_lite_journey(self) -> None:
        runner = self.candidate / "scripts" / "validate_installed_stage1.py"
        current = runner.read_text(encoding="utf-8")
        changed = current.replace(
            "dev_flow_get_next_action",
            "dev_flow_get_partial_action",
        )
        self.assertNotEqual(changed, current)
        runner.write_text(changed, encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "installed validation does not exercise the real MCP exact-set journey",
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
            ("src/dev_flow_orchestrator/mcp/guidance.py", component_marker),
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

    def test_mcp_registration_command_is_exact(self) -> None:
        registration = self.candidate / ".mcp.json"
        document = json.loads(registration.read_text(encoding="utf-8"))
        document["mcpServers"]["dev-flow"]["args"] = ["--http"]
        registration.write_text(json.dumps(document), encoding="utf-8")
        self.assert_error_contains(
            validate(self.candidate),
            "pre-import MCP registration is invalid",
        )


if __name__ == "__main__":
    unittest.main()
