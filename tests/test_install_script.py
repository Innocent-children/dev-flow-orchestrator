"""Source and rendering contracts for the version-specific installer assets."""

from __future__ import annotations

import base64
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INSTALLER = SCRIPTS / "install.sh"
sys.path.insert(0, str(SCRIPTS))

import build_release  # noqa: E402
import release_artifact  # noqa: E402


class VersionedBootstrapSourceTests(unittest.TestCase):
    def test_checked_in_posix_file_is_a_release_only_template(self) -> None:
        source = INSTALLER.read_text(encoding="utf-8")
        for token in (
            "@DEV_FLOW_RELEASE_VERSION@",
            "@DEV_FLOW_ARCHIVE_NAME@",
            "@DEV_FLOW_INDEX_SHA256@",
            "@DEV_FLOW_PHASE_A_B64@",
            "DEV_FLOW_SOURCE_ROOT is not supported",
            '"$phase_a_python" -I -S "$phase_a_path" bootstrap',
        ):
            self.assertIn(token, source)
        for obsolete in ("git clone", "git fetch", "refs/heads", "--ff-only"):
            self.assertNotIn(obsolete, source.casefold())

    def test_rendered_bootstraps_embed_the_same_phase_a_bytes(self) -> None:
        verifier = (SCRIPTS / "release_artifact.py").read_bytes()
        digest = "a" * 64
        rendered = build_release.render_bootstrap_assets(
            verifier,
            index_sha256=digest,
            version="1.2.3",
        )
        shell = rendered["install.sh"].decode("utf-8")
        powershell = rendered["install.ps1"].decode("utf-8")
        shell_match = re.search(r"DEV_FLOW_PHASE_A_B64='([A-Za-z0-9+/=]+)'", shell)
        powershell_match = re.search(
            r"\$PhaseABase64 = '([A-Za-z0-9+/=]+)'", powershell
        )
        self.assertIsNotNone(shell_match)
        self.assertIsNotNone(powershell_match)
        self.assertEqual(shell_match.group(1), powershell_match.group(1))
        self.assertEqual(base64.b64decode(shell_match.group(1)), verifier)
        for document in (shell, powershell):
            self.assertIn(release_artifact.CANONICAL_REPOSITORY, document)
            self.assertIn(digest, document)
            self.assertIn("DEV_FLOW_SOURCE_ROOT", document)
            self.assertNotIn("git clone", document.casefold())

    @unittest.skipUnless(sys.platform == "darwin", "POSIX bootstrap test targets macOS")
    def test_unrendered_template_refuses_without_creating_product_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            state = work / "state"
            environment = {"PATH": "/usr/bin:/bin", "DEV_FLOW_RUNTIME_HOME": str(state)}
            completed = subprocess.run(
                ["/bin/sh", str(INSTALLER)],
                cwd=work,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("release template", completed.stderr)
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
