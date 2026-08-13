"""Windows lifecycle contracts; static checks are not native final-artifact evidence."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VersionedWindowsLifecycleStaticTests(unittest.TestCase):
    def test_powershell_asset_is_a_pinned_phase_a_template(self) -> None:
        source = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        for token in (
            "Set-StrictMode -Version Latest",
            "@DEV_FLOW_RELEASE_VERSION@",
            "@DEV_FLOW_ARCHIVE_NAME@",
            "@DEV_FLOW_INDEX_SHA256@",
            "@DEV_FLOW_PHASE_A_B64@",
            "DEV_FLOW_SOURCE_ROOT is not supported",
            "-I -S $PhaseAPath bootstrap",
        ):
            self.assertIn(token, source)
        for obsolete in ("refs/heads", "--ff-only", "--no-overwrite-ignore"):
            self.assertNotIn(obsolete, source)

    def test_versioned_driver_uses_shared_lock_cas_and_terminal_contract(self) -> None:
        lifecycle = (ROOT / "scripts" / "release_lifecycle.py").read_text(
            encoding="utf-8"
        )
        machine = (ROOT / "scripts" / "lifecycle_machine.py").read_text(
            encoding="utf-8"
        )
        state = (ROOT / "scripts" / "lifecycle_state.py").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((lifecycle, machine, state))
        for token in (
            "lifecycle.lock",
            "expected_active",
            "public_proof",
            "committed",
            "rolled_back",
            "partial",
        ):
            self.assertIn(token, combined)

    def test_native_dispatcher_names_are_closed(self) -> None:
        sources = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "scripts/release_lifecycle.py",
                "scripts/render_dispatchers.py",
                "scripts/stable_dispatcher.py",
            )
        )
        for name in ("dev-flow.cmd", "dev-flow-mcp.cmd", "dev-flow-uninstall.cmd"):
            self.assertIn(name, sources)

    def test_repository_uninstaller_has_no_checkout_retention_switch(self) -> None:
        source = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")
        self.assertIn("dev-flow-uninstall", source)
        self.assertNotIn("KeepSource", source)
        self.assertNotIn("RemoveSource", source)

    def test_this_suite_is_explicitly_static(self) -> None:
        self.assertIn("not native final-artifact evidence", __doc__ or "")

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows PowerShell")
    def test_unrendered_template_refusal_executes_in_native_powershell(self) -> None:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "install.ps1"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("release template", completed.stderr)


if __name__ == "__main__":
    unittest.main()
