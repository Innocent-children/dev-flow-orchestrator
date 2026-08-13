"""Host-neutral Windows product checks; never native Windows or real Codex evidence."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VersionedWindowsProductContractTests(unittest.TestCase):
    def test_plugin_and_mcp_identity_remain_platform_neutral(self) -> None:
        manifest = json.loads(
            (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        registration = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "dev-flow-orchestrator")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(
            registration,
            {"mcpServers": {"dev-flow": {"command": "dev-flow-mcp", "args": ["--stdio"]}}},
        )

    def test_powershell_template_has_no_checkout_or_source_retention_interface(self) -> None:
        install = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        versioned = (ROOT / "scripts" / "install-versioned.ps1").read_text(encoding="utf-8")
        uninstall = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")
        self.assertIn("@DEV_FLOW_RESOLVER_B64@", install)
        self.assertIn("MAJOR.MINOR.PATCH|latest", install)
        self.assertIn("DEV_FLOW_SOURCE_ROOT is not supported", install)
        self.assertIn("@DEV_FLOW_INDEX_SHA256@", versioned)
        self.assertIn("@DEV_FLOW_PHASE_A_B64@", versioned)
        self.assertIn("DEV_FLOW_SOURCE_ROOT is not supported", versioned)
        self.assertIn("dev-flow-uninstall", uninstall)
        for obsolete in (
            "refs/heads/$RepositoryRef",
            "--ff-only",
            "--no-overwrite-ignore",
            "[switch]$KeepSource",
            "[switch]$RemoveSource",
        ):
            self.assertNotIn(obsolete, install + versioned + uninstall)

    def test_native_dispatcher_names_are_closed_and_source_independent(self) -> None:
        renderer = (ROOT / "scripts" / "render_dispatchers.py").read_text(
            encoding="utf-8"
        )
        dispatcher = (ROOT / "scripts" / "stable_dispatcher.py").read_text(
            encoding="utf-8"
        )
        for name in ("dev-flow.cmd", "dev-flow-mcp.cmd", "dev-flow-uninstall.cmd"):
            self.assertIn(name, renderer + dispatcher)
        self.assertIn("dev-flow-dispatcher/1.0.0", renderer)
        self.assertIn("dev-flow-runtime-receipt/3.0.0", dispatcher)

    def test_legacy_hook_launcher_and_assets_are_absent(self) -> None:
        for relative in (
            "scripts/dev_flow_python_launcher.cmd",
            "hooks/hooks.json",
            "hooks/dev_flow_hook.py",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_static_suite_is_not_native_or_real_host_evidence(self) -> None:
        self.assertIn("never native Windows or real Codex evidence", __doc__ or "")


if __name__ == "__main__":
    unittest.main()
