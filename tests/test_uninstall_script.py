"""Source-independent uninstall entry and deletion-containment contracts."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
UNINSTALLER = ROOT / "scripts" / "uninstall.sh"


class StableUninstallEntryTests(unittest.TestCase):
    def test_repository_entry_points_do_not_run_checkout_lifecycle(self) -> None:
        for relative in ("scripts/uninstall.sh", "scripts/uninstall.ps1"):
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("dev-flow-uninstall", source)
                self.assertIn("requires neither Git nor a source checkout", source)
                self.assertNotIn("KeepSource", source)
                self.assertNotIn("RemoveSource", source)
                self.assertNotIn("git clone", source.casefold())

    def test_stable_dispatcher_copies_verified_uninstall_driver(self) -> None:
        source = (ROOT / "scripts" / "stable_dispatcher.py").read_text(
            encoding="utf-8"
        )
        for token in (
            "uninstall_driver_sha256",
            "copied uninstall driver",
            "dev-flow-uninstall",
            "tempfile.mkdtemp",
        ):
            self.assertIn(token, source)

    @unittest.skipUnless(sys.platform == "darwin", "POSIX wrapper test targets macOS")
    def test_repository_posix_entry_refuses_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            marker = work / "must-not-exist"
            environment = {"PATH": "/usr/bin:/bin", "DEV_FLOW_RUNTIME_HOME": str(marker)}
            completed = subprocess.run(
                ["/bin/sh", str(UNINSTALLER)],
                cwd=work,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("dev-flow-uninstall", completed.stderr)
            self.assertFalse(marker.exists())


class RuntimeDeletionContainmentStaticTests(unittest.TestCase):
    def test_uninstall_paths_do_not_use_broad_recursive_deletion(self) -> None:
        sources = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "scripts/uninstall.sh",
                "scripts/uninstall.ps1",
                "scripts/uninstall_driver.py",
                "scripts/runtime_integrity.py",
            )
        )
        for forbidden in (
            "rm -rf",
            "Remove-Item -LiteralPath $RuntimeRoot -Recurse",
            "shutil.rmtree",
        ):
            self.assertNotIn(forbidden, sources)


if __name__ == "__main__":
    unittest.main()
