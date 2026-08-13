"""Windows lifecycle contracts; static checks are not native final-artifact evidence."""

from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_release  # noqa: E402
import release_artifact  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class VersionedWindowsLifecycleStaticTests(unittest.TestCase):
    def test_powershell_asset_is_a_pinned_phase_a_template(self) -> None:
        source = (ROOT / "scripts" / "install-versioned.ps1").read_text(encoding="utf-8")
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

    def test_powershell_install_entry_is_a_canonical_version_template(self) -> None:
        source = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        for token in (
            "Set-StrictMode -Version Latest",
            "@DEV_FLOW_RESOLVER_B64@",
            "@DEV_FLOW_REPOSITORY@",
            "DEV_FLOW_SOURCE_ROOT is not supported",
            "MAJOR.MINOR.PATCH|latest",
            "-I -S $ResolverPath install",
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
        for relative in ("scripts/install.ps1", "scripts/install-versioned.ps1"):
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / relative),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("release template", completed.stderr)

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows PowerShell")
    def test_rendered_powershell_preserves_phase_b_argument_boundaries(self) -> None:
        verifier = (
            "import json,sys\n"
            "print(json.dumps(sys.argv[1:], ensure_ascii=False))\n"
        ).encode("utf-8")
        rendered = build_release.render_bootstrap_assets(
            verifier,
            index_sha256="a" * 64,
            version="1.2.3",
        )
        with tempfile.TemporaryDirectory(prefix="Dev Flow PowerShell's 数据 ") as temporary:
            work = Path(temporary).resolve()
            installer = work / "install-1.2.3.ps1"
            installer.write_bytes(rendered["install-1.2.3.ps1"])
            values = (
                "--runtime-root=" + str(work / "runtime root's 数据"),
                "--bin-dir",
                str(work / "bin root's 数据"),
            )
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(installer),
                    *values,
                ],
                cwd=work,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            captured = json.loads(completed.stdout.strip())
            separator = captured.index("--")
            self.assertEqual(captured[separator + 1 :], list(values))

    @unittest.skipUnless(sys.platform == "win32", "requires native Windows PowerShell")
    def test_rendered_install_entry_forwards_version_and_arguments(self) -> None:
        resolver = (
            "import json,sys\n"
            "print(json.dumps(sys.argv[1:], ensure_ascii=False))\n"
        ).encode("utf-8")
        rendered = build_release.render_universal_assets(
            resolver,
            repository=release_artifact.CANONICAL_REPOSITORY,
            schema="dev-flow-release-resolver/1.0.0",
        )
        with tempfile.TemporaryDirectory(prefix="Dev Flow entry's 数据 ") as temporary:
            work = Path(temporary).resolve()
            installer = work / "install.ps1"
            installer.write_bytes(rendered["install.ps1"])
            values = (
                "--runtime-root=" + str(work / "runtime root's 数据"),
                "--bin-dir",
                str(work / "bin root's 数据"),
            )
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(installer),
                    "latest",
                    *values,
                ],
                cwd=work,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            captured = json.loads(completed.stdout.strip())
            self.assertEqual(captured[0], "install")
            self.assertEqual(captured[4], "latest")
            separator = captured.index("--")
            self.assertEqual(captured[separator + 1 :], list(values))


if __name__ == "__main__":
    unittest.main()
