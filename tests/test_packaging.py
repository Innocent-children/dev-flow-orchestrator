from __future__ import annotations

import ast
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

from scripts import windows_native_validation


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
        references = (
            PLUGIN_ROOT
            / "skills"
            / "follow-dev-flow"
            / "references"
        )
        common = (references / "state-machine-common.md").read_text(
            encoding="utf-8"
        )
        lite = (references / "flow-lite.md").read_text(encoding="utf-8")
        full = (references / "flow-full.md").read_text(encoding="utf-8")
        preflight = (references / "gates" / "preflight.md").read_text(
            encoding="utf-8"
        )
        baseline_impact_route = (
            references / "gates" / "baseline-impact-route.md"
        ).read_text(encoding="utf-8")
        workspace_plan = (
            references / "gates" / "workspace-plan.md"
        ).read_text(encoding="utf-8")
        verification_review = (
            references / "gates" / "verification-review.md"
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
        impact_interface = (
            PLUGIN_ROOT
            / "skills"
            / "analyze-change-impact"
            / "agents"
            / "openai.yaml"
        ).read_text(encoding="utf-8")
        review_interface = (
            PLUGIN_ROOT
            / "skills"
            / "review-dev-flow-change"
            / "agents"
            / "openai.yaml"
        ).read_text(encoding="utf-8")

        for label in (
            "使用当前分支（精简流程）",
            "新建并切换分支（精简流程）",
            "创建独立工作树（完整流程）",
        ):
            self.assertIn(label, skill)
            self.assertIn(label, common)
        command_owners = {
            "preflight --confirm-preview": preflight,
            "baseline": baseline_impact_route,
            "record-index --role baseline": baseline_impact_route,
            "set-route": baseline_impact_route,
            "approve --gate route": baseline_impact_route,
            "prepare-workspace --execute": workspace_plan,
            "review-snapshot": verification_review,
            "transition": common,
            "cancel": common,
        }
        for status_changing_command, owner in command_owners.items():
            self.assertIn(status_changing_command, owner)
        self.assertIn("一次确认不得授权后续状态边", skill)
        self.assertIn("git switch -c <branch>", skill)
        self.assertIn("git switch -c <branch>", common)
        self.assertIn("task-next", skill)
        self.assertIn("node-description", skill)
        self.assertIn("--profile agent-v1", skill)
        self.assertIn("Do not preload unrelated", skill)
        self.assertNotIn("Run the controller's `--help`", skill)
        self.assertIn("PREFLIGHT_PREVIEW_STALE", preflight)
        self.assertIn(
            "`start` rejects a\nmissing `--workspace-strategy",
            common,
        )
        self.assertIn("show --compact", common)
        self.assertIn("workflow.remaining", common)
        self.assertIn("DONE` is irreversible", common)
        self.assertIn("DONE` is irreversible", verification_review)
        self.assertNotIn("flow-full.md", lite)
        self.assertIn("gates/preflight.md", lite)
        self.assertIn("gates/preflight.md", full)
        self.assertIn("language the user explicitly selects", openspec_route)
        self.assertIn("repository's unambiguous dominant language", openspec_route)
        self.assertIn("stop and ask the user", openspec_route)
        self.assertIn("执行开发流程", interface)
        self.assertNotIn('value: "dev-flow"', interface)
        self.assertNotIn('value: "dev-flow-posix"', interface)
        self.assertNotIn('value: "dev-flow-windows"', interface)
        self.assertIn('value: "codebase-memory-mcp"', interface)
        self.assertIn("allow_implicit_invocation: true", interface)
        self.assertIn(
            "allow_implicit_invocation: false", impact_interface
        )
        self.assertIn(
            "allow_implicit_invocation: false", review_interface
        )

    def test_controller_hook_and_document_workflow_names_stay_in_sync(self) -> None:
        controller = load_script(
            "dev_flow_name_sync",
            PLUGIN_ROOT / "scripts" / "dev_flow.py",
        )
        hook = load_script(
            "dev_flow_hook_name_sync",
            PLUGIN_ROOT / "hooks" / "dev_flow_hook.py",
        )
        hook_source = (
            PLUGIN_ROOT / "hooks" / "dev_flow_hook.py"
        ).read_text(encoding="utf-8")
        hook_tree = ast.parse(hook_source)
        common = (
            PLUGIN_ROOT
            / "skills"
            / "follow-dev-flow"
            / "references"
            / "state-machine-common.md"
        ).read_text(encoding="utf-8")
        readmes = [
            (PLUGIN_ROOT / name).read_text(encoding="utf-8")
            for name in ("README.md", "README.zh-CN.md")
        ]

        workflow_view = next(
            node
            for node in hook_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_controller_workflow_view"
        )
        imported = {
            alias.name
            for node in ast.walk(workflow_view)
            if isinstance(node, ast.ImportFrom)
            and node.module == "dev_flow"
            for alias in node.names
        }
        called = {
            node.func.id
            for node in ast.walk(workflow_view)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        projection_apis = {
            "build_task_next",
            "resolve_loaded_task_workflow",
            "workflow_node_description",
            "workflow_progress_projection",
            "workflow_runtime_services",
        }
        self.assertTrue(projection_apis <= imported)
        self.assertTrue(projection_apis <= called)

        assigned_names = {
            target.id
            for node in hook_tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets
                if isinstance(node, ast.Assign)
                else (node.target,)
            )
            if isinstance(target, ast.Name)
        }
        self.assertTrue(
            {
                "FLOW_NAMES_ZH",
                "STATE_NAMES_ZH",
                "ORDERED_STATES",
                "LITE_ORDERED_STATES",
                "STAGES",
                "LITE_STAGES",
                "FULL_GATES",
                "LITE_GATE",
                "APPROVAL_GATES",
            }.isdisjoint(assigned_names)
        )

        catalog = controller.workflow_runtime_services().catalog
        full = catalog.resolve("full", 3)
        lite = catalog.resolve("lite", 3)
        for bundle in (full, lite):
            flow_id = bundle.graph["flow"]
            display_name = bundle.graph["labels"]["zh-CN"]
            self.assertEqual(
                controller.FLOW_NAMES_ZH[flow_id],
                display_name,
            )
            self.assertIn(
                f"| `{flow_id}` | {display_name} |",
                common,
            )
            for readme in readmes:
                self.assertIn(flow_id, readme)
                self.assertIn(display_name, readme)
        for stable_id, display_name in controller.STATE_NAMES_ZH.items():
            self.assertEqual(
                full.node(stable_id)["labels"]["zh-CN"],
                display_name,
            )
            self.assertIn(
                f"| `{stable_id}` | {display_name} |",
                common,
            )

        state = {
            "schema_version": 3,
            "task_id": "hook-projection-sync",
            "revision": 1,
            "status": "PLANNING",
            "flow": "full",
            "execution_profile": "single-repository",
            "workflow_ref": {
                "id": full.workflow_id,
                "version": full.workflow_version,
                "schema": full.graph["schema"],
                "graph_sha256": full.graph_sha256,
                "bundle_sha256": full.bundle_sha256,
            },
            "node_instances": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            view = hook._controller_workflow_view(
                state,
                Path(temporary),
                PLUGIN_ROOT,
            )
        description = controller.workflow_node_description(state)
        expected_action_ids = []
        for action in description["legal_actions"]:
            action_id = action["action_id"]
            if action_id not in expected_action_ids:
                expected_action_ids.append(action_id)

        self.assertEqual(view.task_next["contract"], "agent-v1")
        self.assertEqual(
            view.task_next["workflow"]["bundle_sha256"],
            full.bundle_sha256,
        )
        self.assertEqual(
            hook._workflow_name(view, "fallback"),
            full.graph["labels"]["zh-CN"],
        )
        self.assertEqual(
            hook._node_label(view, "fallback"),
            full.node("PLANNING")["labels"]["zh-CN"],
        )
        self.assertEqual(
            view.task_next["frontier"][0]["label"],
            full.node("PLANNING")["labels"]["zh-CN"],
        )
        self.assertEqual(
            hook._projected_next_action(state, view),
            ", ".join(expected_action_ids),
        )

    def test_state_machine_references_are_routed_and_bounded(self) -> None:
        skill_root = PLUGIN_ROOT / "skills" / "follow-dev-flow"
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        references = skill_root / "references"
        router = (references / "state-machine.md").read_text(encoding="utf-8")
        common = references / "state-machine-common.md"
        lite = references / "flow-lite.md"
        preflight = references / "gates" / "preflight.md"

        for required_link in (
            "references/state-machine-common.md",
            "references/flow-lite.md",
            "references/flow-full.md",
        ):
            self.assertIn(required_link, skill)
        self.assertNotIn(
            "references/state-machine.md#",
            skill,
        )
        self.assertIn("## Per-transition confirmation", router)
        self.assertIn("## Lite flow", router)
        self.assertLess(len(router.encode("utf-8")), 2048)
        self.assertLess(len(lite.read_bytes()), 8192)
        self.assertLess(
            len(common.read_bytes())
            + len(lite.read_bytes())
            + len(preflight.read_bytes()),
            24576,
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

    def test_identity_inventory_covers_v4_runtime_and_release_inputs(
        self,
    ) -> None:
        inventory = validate_package.package_inventory(PLUGIN_ROOT)
        self.assertEqual(
            validate_package.validate_identity_inventory(
                PLUGIN_ROOT, inventory
            ),
            [],
        )
        inventory.remove(
            "scripts/dev_flow_parts/workflow_action_transaction.py"
        )
        errors = validate_package.validate_identity_inventory(
            PLUGIN_ROOT, inventory
        )
        self.assertTrue(
            any(
                "workflow_action_transaction.py" in item
                for item in errors
            )
        )

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

    def test_manifest_and_mcp_configuration_use_official_companion_shape(
        self,
    ) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text(
                encoding="utf-8"
            )
        )
        document = json.loads(
            (PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8")
        )
        inventory = validate_package.package_inventory(PLUGIN_ROOT)

        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(
            validate_package.validate_mcp_configuration(
                document, inventory
            ),
            [],
        )
        self.assertEqual(
            set(document),
            {"mcpServers"},
        )
        self.assertEqual(
            set(document["mcpServers"]),
            {"dev-flow-posix", "dev-flow-windows"},
        )
        posix = document["mcpServers"]["dev-flow-posix"]
        windows = document["mcpServers"]["dev-flow-windows"]
        self.assertEqual(
            posix["command"],
            "/bin/sh",
        )
        self.assertEqual(
            posix["args"],
            [
                "./scripts/dev_flow_python_launcher",
                "./scripts/dev_flow_mcp.py",
            ],
        )
        self.assertEqual(windows["command"], "cmd.exe")
        self.assertEqual(
            windows["args"],
            [
                "/d",
                "/c",
                ".\\scripts\\dev_flow_mcp_launcher.cmd",
            ],
        )
        for server in (posix, windows):
            self.assertEqual(
                server["default_tools_approval_mode"], "writes"
            )
            self.assertFalse(server["enabled"])
            self.assertFalse(server["required"])
            self.assertNotIn("env", server)

    def test_mcp_configuration_rejects_nonportable_or_unsafe_defaults(
        self,
    ) -> None:
        document = json.loads(
            (PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8")
        )
        inventory = validate_package.package_inventory(PLUGIN_ROOT)
        posix = document["mcpServers"]["dev-flow-posix"]
        posix["command"] = "/absolute/unsupported-shell"
        posix["enabled"] = True
        document["mcpServers"]["dev-flow-windows"]["enabled"] = True
        posix[
            "default_tools_approval_mode"
        ] = "auto"
        posix["env"] = {
            "manager_secret": "forbidden"
        }

        errors = validate_package.validate_mcp_configuration(
            document, inventory
        )

        self.assertTrue(
            any("command must be" in error for error in errors), errors
        )
        self.assertTrue(
            any("default disabled" in error for error in errors), errors
        )
        self.assertTrue(
            any("prompt for write tools" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("secret material" in error for error in errors), errors
        )

    def test_mcp_profiles_use_explicit_host_launchers_without_pathext(
        self,
    ) -> None:
        posix_launcher = (
            PLUGIN_ROOT / "scripts" / "dev_flow_mcp_launcher"
        )
        windows_launcher = (
            PLUGIN_ROOT / "scripts" / "dev_flow_mcp_launcher.cmd"
        )
        self.assertTrue(posix_launcher.is_file())
        self.assertTrue(windows_launcher.is_file())
        windows = windows_launcher.read_text(encoding="utf-8")
        self.assertIn('"%~dp0dev_flow_mcp.py"', windows)
        self.assertIn("3.14 3.13 3.12 3.11 3.10 3.9", windows)
        document = json.loads(
            (PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8")
        )
        windows_profile = document["mcpServers"]["dev-flow-windows"]
        self.assertEqual(windows_profile["command"], "cmd.exe")
        self.assertTrue(
            windows_profile["args"][-1].endswith(
                "dev_flow_mcp_launcher.cmd"
            )
        )
        self.assertNotIn("PATHEXT", json.dumps(document))

        if os.name != "nt":
            posix_profile = document["mcpServers"]["dev-flow-posix"]
            command = [
                posix_profile["command"],
                *posix_profile["args"],
            ]
            cwd = (PLUGIN_ROOT / posix_profile["cwd"]).resolve()
            completed = subprocess.run(
                command,
                cwd=cwd,
                input=windows_native_validation._mcp_probe_input(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                timeout=30,
            )
            observed = windows_native_validation._validate_mcp_probe(
                completed,
                label="packaged POSIX profile",
            )
            self.assertEqual(
                observed["tool_names"],
                list(windows_native_validation.MCP_EXPECTED_TOOLS),
            )
            self.assertEqual(
                command,
                [
                    "/bin/sh",
                    "./scripts/dev_flow_python_launcher",
                    "./scripts/dev_flow_mcp.py",
                ],
            )
            self.assertEqual(cwd, PLUGIN_ROOT)

    def test_current_codex_bundle_proves_plugin_relative_mcp_convention(
        self,
    ) -> None:
        candidates = (
            Path(
                "/Applications/ChatGPT.app/Contents/Resources/plugins/"
                "openai-bundled/plugins/computer-use/.mcp.json"
            ),
            Path.home()
            / ".codex"
            / ".tmp"
            / "bundled-marketplaces"
            / "openai-bundled"
            / "plugins"
            / "computer-use"
            / ".mcp.json",
        )
        companion = next(
            (candidate for candidate in candidates if candidate.is_file()),
            None,
        )
        if companion is None:
            self.skipTest(
                "current Codex bundled-plugin MCP evidence is unavailable"
            )
        document = json.loads(companion.read_text(encoding="utf-8"))
        self.assertEqual(set(document), {"mcpServers"})
        relative_servers = [
            server
            for server in document["mcpServers"].values()
            if isinstance(server, dict)
            and server.get("cwd") == "."
            and isinstance(server.get("command"), str)
            and server["command"].startswith("./")
        ]
        self.assertTrue(relative_servers, document)
        for server in relative_servers:
            self.assertTrue(
                (companion.parent / server["command"]).is_file(),
                server,
            )

    def test_mcp_profiles_are_optional_mutually_exclusive_acceleration(
        self,
    ) -> None:
        english = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        chinese = (PLUGIN_ROOT / "README.zh-CN.md").read_text(
            encoding="utf-8"
        )
        install = (PLUGIN_ROOT / "INSTALL.md").read_text(encoding="utf-8")
        for document in (english, install):
            self.assertIn("Never enable both", document)
            self.assertIn("optional acceleration layer", document)
            self.assertIn("optional/OR", document)
        self.assertIn("绝不能同时启用", chinese)
        self.assertIn("可选加速层", chinese)
        self.assertIn("optional/OR", chinese)

    def test_current_bundled_plugin_validator_accepts_companion_mcp(
        self,
    ) -> None:
        validator, _, discovery_error = (
            run_bundled_validators._validator_path(
                "DEV_FLOW_PLUGIN_VALIDATOR",
                run_bundled_validators.PLUGIN_VALIDATOR_RELATIVE,
            )
        )
        if discovery_error is not None:
            self.fail(discovery_error)
        if validator is None:
            self.skipTest("Codex-bundled plugin validator is unavailable")
        interpreter, interpreter_error = (
            run_bundled_validators._validator_python()
        )
        if interpreter_error is not None or interpreter is None:
            self.fail(
                interpreter_error or "validator interpreter is unavailable"
            )
        with contextlib.redirect_stdout(io.StringIO()):
            status, detail = run_bundled_validators._run_validator(
                validator_kind="plugin-manifest-regression",
                validator_path=validator,
                interpreter=interpreter,
                target=PLUGIN_ROOT,
            )
        if status == "unavailable":
            self.skipTest(detail or "validator dependencies are unavailable")
        self.assertEqual(status, "passed", detail)

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
            shutil.copy2(
                PLUGIN_ROOT / "scripts" / "workflow_bundle_identity.py",
                scripts / "workflow_bundle_identity.py",
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
