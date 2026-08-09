"""Host-neutral static checks; these are not native Windows execution evidence."""

from __future__ import annotations

from pathlib import Path
import os
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsProductSupportTests(unittest.TestCase):
    def test_legacy_hook_launcher_and_assets_are_absent(self) -> None:
        for relative in (
            "scripts/dev_flow_python_launcher.cmd",
            "hooks/hooks.json",
            "hooks/dev_flow_hook.py",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_powershell_lifecycle_preserves_authority_boundaries(self) -> None:
        install = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        uninstall = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")
        for token in (
            "Set-StrictMode -Version Latest",
            "refs/heads/$RepositoryRef",
            "--ff-only",
            "--no-overwrite-ignore",
            "scripts\\validate_package.py",
            "ConvertFrom-Json",
            "[IO.File]::Replace",
            "codex plugin add",
            "scripts\\manage_runtime.py",
            "dev-flow-mcp.cmd",
            "managed MCP runtime",
        ):
            self.assertIn(token, install)
        for token in (
            "[switch]$KeepSource",
            "[IO.File]::Replace",
            "codex plugin remove",
            "OUTCOME        partial",
            "SOURCE PATH",
            "no verifiable exact-ownership manifest",
            "MANUAL ACTION",
            "independently confirm ownership",
            "TASK DATA",
            "preserved",
            "runtime_integrity.py",
            "remove-owned",
            "RUNTIME RETAINED",
            "dev-flow-mcp.cmd",
        ):
            self.assertIn(token, uninstall)

    def test_powershell_source_and_runtime_containment_are_target_precise(self) -> None:
        uninstall = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")
        self.assertEqual(
            [
                line
                for line in uninstall.splitlines()
                if "Remove-Item" in line and "$SourceRoot" in line
            ],
            [],
        )
        self.assertNotIn("$RemoveSource", uninstall)
        self.assertNotIn("[switch]$RemoveSource", uninstall)
        self.assertNotIn("status', '--ignored', '--porcelain", uninstall)
        self.assertNotIn("--remotes=origin", uninstall)
        self.assertNotIn(
            "Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force",
            uninstall,
        )
        self.assertNotIn("Remove-Item -LiteralPath $RuntimeRoot -Recurse", uninstall)

    def test_windows_installer_builds_native_managed_launcher(self) -> None:
        install = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        for token in (
            "[Environment]::Is64BitProcess",
            "venv\\Scripts\\python.exe",
            "DEV_FLOW_RUNTIME_HOME",
            "DEV_FLOW_BIN_DIR",
            "MCP",
            "runtime_integrity.py",
            "Seal-Commit",
            "launcher_path",
            "launcher_sha256",
            "Set-McpLauncher",
            "$CandidateReleaseId",
            "$PersistentPluginRoot",
            "PYTHONDONTWRITEBYTECODE",
            "-B",
        ):
            self.assertIn(token, install)
        launcher_template = (
            ROOT / "scripts" / "dev_flow_mcp_launcher.cmd"
        ).read_text(encoding="utf-8")
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", launcher_template)
        self.assertIn("-B -I", launcher_template)
        self.assertIn("launch-mcp", launcher_template)
        self.assertIn("--release-id", launcher_template)
        self.assertNotIn("-m dev_flow_orchestrator.mcp", launcher_template)
        self.assertNotIn("dev_flow_python_launcher.cmd", install)
        self.assertNotIn("hooks\\", install.casefold())

    def test_native_launcher_templates_have_one_bounded_placeholder(self) -> None:
        posix = ROOT / "scripts" / "dev_flow_mcp_launcher"
        windows = ROOT / "scripts" / "dev_flow_mcp_launcher.cmd"
        posix_text = posix.read_text(encoding="utf-8")
        windows_text = windows.read_text(encoding="utf-8")
        placeholders = (
            "__DEV_FLOW_RUNTIME_PYTHON__",
            "__DEV_FLOW_RUNTIME_VERIFIER__",
            "__DEV_FLOW_RUNTIME_DIR__",
            "__DEV_FLOW_RELEASE_ID__",
        )
        for placeholder in placeholders:
            self.assertEqual(posix_text.count(placeholder), 1)
            self.assertEqual(windows_text.count(placeholder), 1)
        self.assertTrue(posix_text.startswith("#!/bin/sh\n"))
        self.assertIn('"$@"', posix_text)
        self.assertTrue(windows_text.startswith("@echo off\n"))
        self.assertIn("%*", windows_text)
        self.assertNotIn("/bin/sh", windows_text)
        runtime_path = r"C:\Program Files\Dev Flow 雪\O'Brien\100%\python.exe"
        generated = windows_text.replace(
            "__DEV_FLOW_RUNTIME_PYTHON__", runtime_path.replace("%", "%%")
        )
        generated = generated.replace(
            "__DEV_FLOW_RUNTIME_VERIFIER__", r"C:\Program Files\Dev Flow\verifier.py"
        )
        generated = generated.replace(
            "__DEV_FLOW_RUNTIME_DIR__", r"C:\Program Files\Dev Flow\release"
        )
        generated = generated.replace("__DEV_FLOW_RELEASE_ID__", "r-test-release")
        self.assertIn(
            "\"C:\\Program Files\\Dev Flow 雪\\O'Brien\\100%%\\python.exe\"",
            generated,
        )
        for placeholder in placeholders:
            self.assertNotIn(placeholder, generated)
        if os.name != "nt":
            self.assertTrue(posix.stat().st_mode & 0o100)

    def test_windows_receipt_duplicate_and_rollback_checks_are_present(self) -> None:
        install = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        uninstall = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")
        integrity = (ROOT / "scripts" / "runtime_integrity.py").read_text(
            encoding="utf-8"
        )
        for token in (
            "Test-OwnedMcpRegistration",
            "duplicate Dev Flow entries",
            "Previous plugin activation was restored and verified",
            "Write-InstallTransaction",
            "blind_retry_safe",
            "candidate_release",
            "previous_release",
            "rollback-incomplete",
            "validate_installed_stage1.py",
        ):
            self.assertIn(token, install + "\n" + uninstall)
        for token in (
            "dev-flow-runtime-receipt/2.0.0",
            "executable_sha256",
            "ownership_manifest_sha256",
            "dependency_lock_sha256",
        ):
            self.assertIn(token, integrity)
        self.assertIn("Standalone Dev Flow MCP registration(s)", uninstall)
        self.assertIn("launcher/runtime selected for removal", uninstall)

    def test_windows_installer_distinguishes_bundled_and_standalone_mcp(self) -> None:
        install = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        for token in (
            "Test-McpRegistrationEnabled",
            "Test-BundledMcpRegistration",
            "Get-ExplicitOwnedMcpRegistrationNames",
            "$PluginBundledActive",
            "$CanonicalBundled.Count -eq 1",
            "$Canonical.Count -eq 1",
            "$Owned.Count -eq 1",
            "Join-Path $CodexRoot 'config.toml'",
            "'dev-flow'",
            "'stdio'",
            "'dev-flow-mcp'",
            "'--stdio'",
        ):
            self.assertIn(token, install)
        self.assertLess(
            install.index("$PluginJson = Capture-Checked"),
            install.index("$McpListJson = Capture-Checked"),
        )
        self.assertEqual(install.count("@('mcp', 'list', '--json')"), 1)
        self.assertEqual(install.count("& codex mcp list --json"), 1)

    def test_windows_uninstaller_distinguishes_bundled_and_standalone_mcp(
        self,
    ) -> None:
        uninstall = (ROOT / "scripts" / "uninstall.ps1").read_text(
            encoding="utf-8"
        )
        for token in (
            "Test-McpRegistrationEnabled",
            "Test-BundledMcpRegistration",
            "Get-ExplicitOwnedMcpRegistrationNames",
            "$PluginBundledActive",
            "$CanonicalBundled.Count -ne 1",
            "$OwnedRegistrations.Count -ne 1",
            "Join-Path $CodexRoot 'config.toml'",
            "$Installed[0].PSObject.Properties['enabled']",
            "$InstalledProperty.Value -is [bool]",
            "$EnabledProperty.Value -is [bool]",
            "$ArgsProperty.Value -is [Array]",
            "$Arguments[0] -ceq '--stdio'",
            "$PluginIdProperty.Value -ceq $PluginId",
            "'dev-flow'",
            "'stdio'",
            "'dev-flow-mcp'",
            "'--stdio'",
        ):
            self.assertIn(token, uninstall)
        self.assertLess(
            uninstall.index("$PluginJson = Capture-Checked"),
            uninstall.index("$McpListJson = Capture-Checked"),
        )
        self.assertEqual(
            uninstall.count(
                "@('plugin', 'list', '--marketplace', 'personal', '--json')"
            ),
            1,
        )
        self.assertEqual(uninstall.count("@('mcp', 'list', '--json')"), 1)

    def test_this_suite_is_explicitly_static_not_native_evidence(self) -> None:
        self.assertIn("not native Windows execution evidence", __doc__ or "")

    def test_windows_support_does_not_fork_product_identity(self) -> None:
        combined = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in ("scripts/install.ps1", "scripts/uninstall.ps1")
        )
        self.assertNotIn("windows-product-version", combined.casefold())
        self.assertNotIn("windows workflow", combined.casefold())
        self.assertNotIn("windows namespace", combined.casefold())


if __name__ == "__main__":
    unittest.main()
