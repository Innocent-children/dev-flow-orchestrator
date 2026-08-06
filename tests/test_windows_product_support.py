"""Host-neutral checks for the native Windows product integration assets."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsProductSupportTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "requires native cmd.exe")
    def test_windows_launcher_preserves_arguments_flags_and_exit_code(self) -> None:
        launcher = ROOT / "scripts" / "dev_flow_python_launcher.cmd"
        with tempfile.TemporaryDirectory(prefix="dev flow 雪 ") as temporary:
            handler = Path(temporary) / "handler with spaces.py"
            handler.write_text(
                "import json,sys\n"
                "print(json.dumps({'argv': sys.argv[1:], "
                "'utf8': sys.flags.utf8_mode, 'isolated': sys.flags.isolated, "
                "'no_site': sys.flags.no_site, "
                "'no_bytecode': sys.dont_write_bytecode}))\n"
                "raise SystemExit(int(sys.argv[1]))\n",
                encoding="utf-8",
            )
            environment = {**os.environ, "DEV_FLOW_PYTHON": sys.executable}
            result = subprocess.run(
                [str(launcher), str(handler), "7", "a value", "雪", "bang!value"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )

        self.assertEqual(result.returncode, 7, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["argv"], ["7", "a value", "雪", "bang!value"])
        self.assertEqual(payload["utf8"], 1)
        self.assertEqual(payload["isolated"], 1)
        self.assertEqual(payload["no_site"], 1)
        self.assertTrue(payload["no_bytecode"])

    @unittest.skipUnless(sys.platform == "win32", "requires native cmd.exe")
    def test_invalid_python_override_falls_back_to_supported_launcher(self) -> None:
        environment = {
            **os.environ,
            "DEV_FLOW_PYTHON": str(ROOT / "missing python.exe"),
        }
        result = subprocess.run(
            [
                str(ROOT / "scripts" / "dev_flow_python_launcher.cmd"),
                str(ROOT / "scripts" / "dev_flow.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: dev-flow", result.stdout)

    @unittest.skipUnless(sys.platform == "win32", "requires native cmd.exe")
    def test_missing_python_returns_bounded_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as empty_path:
            environment = {
                **os.environ,
                "DEV_FLOW_PYTHON": str(ROOT / "missing python.exe"),
                "PATH": empty_path,
            }
            result = subprocess.run(
                [
                    str(ROOT / "scripts" / "dev_flow_python_launcher.cmd"),
                    str(ROOT / "scripts" / "dev_flow.py"),
                    "--help",
                ],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
        self.assertEqual(result.returncode, 127)
        self.assertIn("supported 64-bit Python 3.9-3.14 was not found", result.stderr)

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
