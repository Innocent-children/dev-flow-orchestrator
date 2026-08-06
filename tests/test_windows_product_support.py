"""Host-neutral checks for the native Windows product integration assets."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsProductSupportTests(unittest.TestCase):
    def test_every_command_hook_has_one_windows_override(self) -> None:
        document = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        for event, groups in document["hooks"].items():
            for group in groups:
                for hook in group["hooks"]:
                    with self.subTest(event=event):
                        self.assertEqual(hook["type"], "command")
                        self.assertIn("dev_flow_python_launcher", hook["command"])
                        self.assertEqual(
                            hook["commandWindows"],
                            '"%PLUGIN_ROOT%\\scripts\\dev_flow_python_launcher.cmd" '
                            '"%PLUGIN_ROOT%\\hooks\\dev_flow_hook.py"',
                        )

    def test_windows_launcher_is_bounded_and_isolated(self) -> None:
        launcher = (ROOT / "scripts" / "dev_flow_python_launcher.cmd").read_text(encoding="utf-8")
        for token in (
            "DisableDelayedExpansion",
            "DEV_FLOW_PYTHON",
            "py.exe -3",
            "python.exe",
            "python3.exe",
            "struct.calcsize('P') == 8",
            "-X utf8 -I -S",
            "exit /b 127",
        ):
            self.assertIn(token, launcher)

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
            "/hooks",
            "does not establish Hook trust",
        ):
            self.assertIn(token, install)
        for token in (
            "[switch]$KeepSource",
            "status', '--ignored', '--porcelain",
            "--remotes=origin",
            "[IO.File]::Replace",
            "codex plugin remove",
            "TASK DATA",
            "preserved",
        ):
            self.assertIn(token, uninstall)

    def test_windows_support_does_not_fork_product_identity(self) -> None:
        combined = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "scripts/install.ps1",
                "scripts/uninstall.ps1",
                "scripts/dev_flow_python_launcher.cmd",
            )
        )
        self.assertNotIn("windows-product-version", combined.casefold())
        self.assertNotIn("windows workflow", combined.casefold())
        self.assertNotIn("windows namespace", combined.casefold())


if __name__ == "__main__":
    unittest.main()
