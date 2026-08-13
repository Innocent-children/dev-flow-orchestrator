"""Source and rendering contracts for the installer assets."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INSTALLER = SCRIPTS / "install.sh"
VERSIONED = SCRIPTS / "install-versioned.sh"
sys.path.insert(0, str(SCRIPTS))

import build_release  # noqa: E402
import release_artifact  # noqa: E402
import release_resolver  # noqa: E402


class UniversalInstallEntrySourceTests(unittest.TestCase):
    def test_checked_in_posix_entry_is_a_release_only_template(self) -> None:
        source = INSTALLER.read_text(encoding="utf-8")
        for token in (
            "@DEV_FLOW_RESOLVER_B64@",
            "@DEV_FLOW_REPOSITORY@",
            "DEV_FLOW_SOURCE_ROOT is not supported",
            "MAJOR.MINOR.PATCH|latest",
            '"$resolver_python" -I -S "$resolver_path" install',
        ):
            self.assertIn(token, source)
        for obsolete in ("git clone", "git fetch", "refs/heads", "--ff-only"):
            self.assertNotIn(obsolete, source.casefold())

    def test_checked_in_posix_versioned_file_is_a_release_only_template(self) -> None:
        source = VERSIONED.read_text(encoding="utf-8")
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

    def test_rendered_universal_entries_embed_the_same_resolver_bytes(self) -> None:
        resolver = (SCRIPTS / "release_resolver.py").read_bytes()
        rendered = build_release.render_universal_assets(
            resolver,
            repository=release_artifact.CANONICAL_REPOSITORY,
            schema=release_resolver.RESOLVER_SCHEMA,
        )
        shell = rendered["install.sh"].decode("utf-8")
        powershell = rendered["install.ps1"].decode("utf-8")
        shell_match = re.search(r"DEV_FLOW_RESOLVER_B64='([A-Za-z0-9+/=]+)'", shell)
        powershell_match = re.search(
            r"\$ResolverBase64 = '([A-Za-z0-9+/=]+)'", powershell
        )
        self.assertIsNotNone(shell_match)
        self.assertIsNotNone(powershell_match)
        self.assertEqual(shell_match.group(1), powershell_match.group(1))
        self.assertEqual(base64.b64decode(shell_match.group(1)), resolver)
        for document in (shell, powershell):
            self.assertIn(release_artifact.CANONICAL_REPOSITORY, document)
            self.assertIn(release_resolver.RESOLVER_SCHEMA, document)
            self.assertIn("DEV_FLOW_SOURCE_ROOT", document)
            self.assertNotIn("git clone", document.casefold())

    def test_rendered_versioned_bootstraps_embed_the_same_phase_a_bytes(self) -> None:
        verifier = (SCRIPTS / "release_artifact.py").read_bytes()
        digest = "a" * 64
        rendered = build_release.render_bootstrap_assets(
            verifier,
            index_sha256=digest,
            version="1.2.3",
        )
        shell = rendered["install-1.2.3.sh"].decode("utf-8")
        powershell = rendered["install-1.2.3.ps1"].decode("utf-8")
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
            self.assertIn("1.2.3", document)
            self.assertIn(digest, document)
            self.assertIn("DEV_FLOW_SOURCE_ROOT", document)
            self.assertNotIn("git clone", document.casefold())

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_rendered_shell_preserves_phase_b_argument_boundaries(self) -> None:
        verifier = (
            "import json,sys\n"
            "print(json.dumps(sys.argv[1:], ensure_ascii=False))\n"
        ).encode("utf-8")
        rendered = build_release.render_bootstrap_assets(
            verifier,
            index_sha256="a" * 64,
            version="1.2.3",
        )
        with tempfile.TemporaryDirectory(prefix="Dev Flow shell's 数据 ") as temporary:
            work = Path(temporary).resolve()
            installer = work / "install-1.2.3.sh"
            installer.write_bytes(rendered["install-1.2.3.sh"])
            installer.chmod(0o755)
            values = (
                "--runtime-root=" + str(work / "runtime root's 数据"),
                "--bin-dir",
                str(work / "bin root's 数据"),
            )
            completed = subprocess.run(
                ["/bin/sh", str(installer), *values],
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

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_universal_entry_forwards_version_and_phase_b_arguments(self) -> None:
        resolver = (
            "import json,sys\n"
            "print(json.dumps(sys.argv[1:], ensure_ascii=False))\n"
        ).encode("utf-8")
        rendered = build_release.render_universal_assets(
            resolver,
            repository=release_artifact.CANONICAL_REPOSITORY,
            schema=release_resolver.RESOLVER_SCHEMA,
        )
        with tempfile.TemporaryDirectory(prefix="Dev Flow entry's 数据 ") as temporary:
            work = Path(temporary).resolve()
            installer = work / "install.sh"
            installer.write_bytes(rendered["install.sh"])
            installer.chmod(0o755)
            values = (
                "--runtime-root=" + str(work / "runtime root's 数据"),
                "--bin-dir",
                str(work / "bin root's 数据"),
            )
            completed = subprocess.run(
                ["/bin/sh", str(installer), "latest", *values],
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

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_universal_entry_requires_a_version_argument(self) -> None:
        rendered = build_release.render_universal_assets(
            b"# resolver\n",
            repository=release_artifact.CANONICAL_REPOSITORY,
            schema=release_resolver.RESOLVER_SCHEMA,
        )
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            installer = work / "install.sh"
            installer.write_bytes(rendered["install.sh"])
            installer.chmod(0o755)
            completed = subprocess.run(
                ["/bin/sh", str(installer)],
                cwd=work,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("Usage: install.sh", completed.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "POSIX bootstrap test targets macOS")
    def test_unrendered_templates_refuse_without_creating_product_state(self) -> None:
        for template in (INSTALLER, VERSIONED):
            with tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary).resolve()
                state = work / "state"
                environment = {
                    "PATH": "/usr/bin:/bin",
                    "DEV_FLOW_RUNTIME_HOME": str(state),
                }
                completed = subprocess.run(
                    ["/bin/sh", str(template)],
                    cwd=work,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("release template", completed.stderr)
                self.assertFalse(state.exists())


class ResolverSourceContractTests(unittest.TestCase):
    def test_installer_and_support_share_version_grammar_and_hosts(self) -> None:
        self.assertEqual(
            release_resolver.CANONICAL_REPOSITORY,
            release_artifact.CANONICAL_REPOSITORY,
        )
        self.assertIn("github.com", release_resolver._ALLOWED_HOSTS)
        self.assertIn("api.github.com", release_resolver._ALLOWED_HOSTS)
        for invalid in ("", "1.2", "1.2.3-with-prefix", "1.2.3-rc1", " 1.2.3", "1.2.3\n"):
            with self.assertRaises(release_resolver.ReleaseResolveError):
                release_resolver.parse_version_request(invalid)
        for valid in ("latest", "1.2.3", "10.20.30"):
            self.assertTrue(release_resolver.parse_version_request(valid))


if __name__ == "__main__":
    unittest.main()
