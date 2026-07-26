from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_package = load_script(
    "validate_package",
    PLUGIN_ROOT / "scripts" / "validate_package.py",
)
audit_runtime_imports = load_script(
    "audit_runtime_imports",
    PLUGIN_ROOT / "scripts" / "audit_runtime_imports.py",
)
run_bundled_validators = load_script(
    "run_bundled_validators",
    PLUGIN_ROOT / "scripts" / "run_bundled_validators.py",
)


class PackageValidationTests(unittest.TestCase):
    def test_current_package_manifest_hooks_skills_and_references_validate(self) -> None:
        self.assertEqual(validate_package.validate_package(PLUGIN_ROOT), [])

    def test_main_workflow_requires_chinese_choices_and_per_transition_confirmation(self) -> None:
        skill = (
            PLUGIN_ROOT / "skills" / "follow-dev-flow" / "SKILL.md"
        ).read_text(encoding="utf-8")
        state_machine = (
            PLUGIN_ROOT
            / "skills"
            / "follow-dev-flow"
            / "references"
            / "state-machine.md"
        ).read_text(encoding="utf-8")
        openspec_route = (
            PLUGIN_ROOT
            / "skills"
            / "follow-dev-flow"
            / "references"
            / "openspec-route.md"
        ).read_text(encoding="utf-8")
        interface = (
            PLUGIN_ROOT
            / "skills"
            / "follow-dev-flow"
            / "agents"
            / "openai.yaml"
        ).read_text(encoding="utf-8")

        for label in (
            "使用当前分支（精简流程）",
            "新建并切换分支（精简流程）",
            "创建独立工作树（完整流程）",
        ):
            self.assertIn(label, skill)
            self.assertIn(label, state_machine)
        for status_changing_command in (
            "preflight --confirm-preview",
            "baseline",
            "record-index --role baseline",
            "set-route",
            "approve --gate route",
            "prepare-workspace --execute",
            "review-snapshot",
            "transition",
            "cancel",
        ):
            self.assertIn(status_changing_command, state_machine)
        self.assertIn("一次确认不得授权后续状态边", skill)
        self.assertIn("git switch -c <branch>", skill)
        self.assertIn("git switch -c <branch>", state_machine)
        self.assertIn("preflight --preview", skill)
        self.assertIn("PREFLIGHT_PREVIEW_STALE", state_machine)
        self.assertIn("start` rejects a missing `--workspace-strategy", state_machine)
        self.assertIn("language the user explicitly selects", openspec_route)
        self.assertIn("repository's unambiguous dominant language", openspec_route)
        self.assertIn("stop and ask the user", openspec_route)
        self.assertIn("执行开发流程", interface)

    def test_controller_hook_and_document_workflow_names_stay_in_sync(self) -> None:
        controller = load_script(
            "dev_flow_name_sync",
            PLUGIN_ROOT / "scripts" / "dev_flow.py",
        )
        hook = load_script(
            "dev_flow_hook_name_sync",
            PLUGIN_ROOT / "hooks" / "dev_flow_hook.py",
        )
        state_machine = (
            PLUGIN_ROOT
            / "skills"
            / "follow-dev-flow"
            / "references"
            / "state-machine.md"
        ).read_text(encoding="utf-8")

        self.assertEqual(controller.FLOW_NAMES_ZH, hook.FLOW_NAMES_ZH)
        self.assertEqual(controller.STATE_NAMES_ZH, hook.STATE_NAMES_ZH)
        self.assertEqual(
            controller.WORKSPACE_STRATEGY_NAMES_ZH,
            hook.WORKSPACE_STRATEGY_NAMES_ZH,
        )
        self.assertEqual(tuple(controller.ORDERED_STATES), hook.STAGES)
        self.assertEqual(
            tuple(controller.LITE_ORDERED_STATES),
            hook.LITE_STAGES,
        )
        for stable_id, display_name in {
            **controller.FLOW_NAMES_ZH,
            **controller.STATE_NAMES_ZH,
        }.items():
            self.assertIn(
                f"| `{stable_id}` | {display_name} |",
                state_machine,
            )

    def test_portable_inventory_rejects_case_and_unicode_aliases(self) -> None:
        errors = validate_package.case_collision_errors(
            {
                "templates/Guide.md",
                "templates/guide.md",
                "assets/\u00e9.txt",
                "assets/e\u0301.txt",
            }
        )
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("portable package path collision" in item for item in errors))

    def test_manifest_validator_is_independent_of_default_hook_discovery(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        inventory = validate_package.package_inventory(PLUGIN_ROOT)
        self.assertEqual(
            validate_package.validate_manifest(manifest, inventory, PLUGIN_ROOT),
            [],
        )
        manifest["hooks"] = "./hooks/hooks.json"
        errors = validate_package.validate_manifest(manifest, inventory, PLUGIN_ROOT)
        self.assertTrue(any("must omit `hooks`" in item for item in errors))

    def test_document_reference_validator_names_a_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "README.md"
            document.write_text(
                "See [missing](templates/Missing.md).\n",
                encoding="utf-8",
            )
            errors = validate_package.validate_document_references(
                root,
                validate_package.package_inventory(root),
                [document],
            )
        self.assertEqual(len(errors), 1)
        self.assertIn("templates/Missing.md", errors[0])

    def test_runtime_import_audit_rejects_third_party_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime.py"
            runtime.write_text(
                "import json\nimport definitely_external_dependency\n",
                encoding="utf-8",
            )
            errors = audit_runtime_imports.audit_imports([runtime], set())
        self.assertEqual(len(errors), 1)
        self.assertIn("definitely_external_dependency", errors[0])

    def test_runtime_audit_accepts_windows_39_dll_stdlib_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            stdlib = base / "Lib"
            extensions = base / "DLLs"
            site_packages = stdlib / "site-packages"
            self.assertTrue(
                audit_runtime_imports._origin_is_stdlib(
                    extensions / "unicodedata.pyd",
                    (stdlib, extensions),
                    (site_packages,),
                )
            )
            self.assertFalse(
                audit_runtime_imports._origin_is_stdlib(
                    site_packages / "external.pyd",
                    (stdlib, extensions),
                    (site_packages,),
                )
            )

    def test_shipped_runtime_imports_and_isolated_startup_validate(self) -> None:
        self.assertEqual(audit_runtime_imports.validate(PLUGIN_ROOT), [])

    def test_controller_loader_names_a_missing_runtime_part(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(
                PLUGIN_ROOT / "scripts" / "dev_flow.py",
                scripts / "dev_flow.py",
            )
            shutil.copytree(
                PLUGIN_ROOT / "scripts" / "dev_flow_parts",
                scripts / "dev_flow_parts",
            )
            (scripts / "dev_flow_parts" / "cli.py").unlink()
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(scripts / "dev_flow.py"),
                    "--help",
                ],
                cwd=root,
                env=audit_runtime_imports._isolated_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, b"")
        self.assertIn(
            b"incomplete dev-flow installation: missing runtime part cli.py",
            completed.stderr,
        )

    def test_candidate_snapshot_digest_changes_with_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate.txt"
            candidate.write_text("before\n", encoding="utf-8")
            before, before_count = run_bundled_validators.snapshot_digest(root)
            candidate.write_text("after\n", encoding="utf-8")
            after, after_count = run_bundled_validators.snapshot_digest(root)
        self.assertEqual(before_count, after_count)
        self.assertNotEqual(before, after)

    def test_missing_auto_discovered_bundled_validators_are_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary)
            environment = {
                "CODEX_HOME": str(codex_home),
                "HOME": str(codex_home),
                "USERPROFILE": str(codex_home),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                with contextlib.redirect_stdout(io.StringIO()):
                    errors = run_bundled_validators.validate_with_bundled_tools(
                        PLUGIN_ROOT,
                        require_available=False,
                    )
        self.assertEqual(errors, [])

    def test_required_missing_bundled_validators_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary)
            environment = {
                "CODEX_HOME": str(codex_home),
                "HOME": str(codex_home),
                "USERPROFILE": str(codex_home),
            }
            output = io.StringIO()
            with mock.patch.dict(os.environ, environment, clear=True):
                with contextlib.redirect_stdout(output):
                    errors = run_bundled_validators.validate_with_bundled_tools(
                        PLUGIN_ROOT,
                        require_available=True,
                    )
        self.assertEqual(len(errors), 2)
        records = [
            json.loads(line)
            for line in output.getvalue().splitlines()
            if line.strip()
        ]
        unavailable = {
            record.get("validator")
            for record in records
            if record.get("event") == "bundled_validator"
            and record.get("status") == "unavailable"
        }
        self.assertEqual(unavailable, {"skill", "plugin-manifest"})

    def test_required_ci_uses_pinned_official_bundled_validators(self) -> None:
        workflow = (
            PLUGIN_ROOT / ".github" / "workflows" / "cross-platform.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            workflow.count(
                "run: python scripts/run_bundled_validators.py --require-available"
            ),
            1,
        )
        for required in (
            "actions/github-script@60a0d83039c74a4aee543508d2ffcb1c3799cdea",
            "owner: \"openai\"",
            "repo: \"codex\"",
            "f61b51ddd924643514b33234816a8a2772b1aec7",
            "0547b4041a5f58fa19892079a114a1df98286406",
            "6cc9dc3199c935916cf6f73fcbbbb0e3bb1b58c8f5109fefa499978908164f51",
            "88fae0fd00998ea32fa2393869042f0231a2b43b",
            "ebda00d55d7518b127f675f062fb5c6e7a1ffdc0a99df1a55ac594400d7d3228",
            "DEV_FLOW_SKILL_VALIDATOR",
            "DEV_FLOW_PLUGIN_VALIDATOR",
            "PyYAML==6.0.3",
        ):
            self.assertIn(required, workflow)

    def test_missing_explicit_bundled_validator_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing-validator.py"
            environment = {
                "DEV_FLOW_SKILL_VALIDATOR": str(missing),
                "DEV_FLOW_PLUGIN_VALIDATOR": str(missing),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                with contextlib.redirect_stdout(io.StringIO()):
                    errors = run_bundled_validators.validate_with_bundled_tools(
                        PLUGIN_ROOT,
                        require_available=False,
                    )
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("does not name a file" in error for error in errors))

    def test_validator_python_keeps_virtual_environment_launcher_path(self) -> None:
        configured = os.path.abspath(sys.executable)
        with mock.patch.dict(
            os.environ,
            {"DEV_FLOW_VALIDATOR_PYTHON": configured},
            clear=True,
        ), mock.patch.object(
            Path,
            "resolve",
            side_effect=AssertionError(
                "validator interpreter symlinks must not be resolved"
            ),
        ):
            interpreter, error = run_bundled_validators._validator_python()
        self.assertIsNone(error)
        self.assertEqual(interpreter, Path(configured))

    def test_explicit_bundled_validators_run_for_every_skill_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validator = root / "validator.py"
            validator.write_text(
                "import pathlib, sys\n"
                "target = pathlib.Path(sys.argv[1])\n"
                "raise SystemExit(0 if target.is_dir() else 4)\n",
                encoding="utf-8",
            )
            environment = {
                "DEV_FLOW_SKILL_VALIDATOR": str(validator),
                "DEV_FLOW_PLUGIN_VALIDATOR": str(validator),
                "DEV_FLOW_VALIDATOR_PYTHON": sys.executable,
            }
            output = io.StringIO()
            with mock.patch.dict(os.environ, environment, clear=True):
                with contextlib.redirect_stdout(output):
                    errors = run_bundled_validators.validate_with_bundled_tools(
                        PLUGIN_ROOT,
                        require_available=True,
                    )
        self.assertEqual(errors, [])
        records = [
            json.loads(line)
            for line in output.getvalue().splitlines()
            if line.strip()
        ]
        passed = [
            record
            for record in records
            if record.get("event") == "bundled_validator"
            and record.get("status") == "passed"
        ]
        self.assertEqual(len(passed), 4)


if __name__ == "__main__":
    unittest.main()
