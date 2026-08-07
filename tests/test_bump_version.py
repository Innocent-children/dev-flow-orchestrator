"""Release bumps must not churn persisted model authorities."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump_version.py"
RELEASE_FILES = (
    "src/dev_flow_orchestrator/_version.py",
    ".codex-plugin/plugin.json",
    "pyproject.toml",
    "uv.lock",
)
MODEL_FILES = (
    "src/dev_flow_orchestrator/product.py",
    "workflows/bugfix.yaml",
    "workflows/feature.yaml",
    "workflows/full.yaml",
    "workflows/investigation.yaml",
    "workflows/lite.yaml",
    "workflows/refactor.yaml",
)


class BumpVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in RELEASE_FILES + MODEL_FILES:
            source = ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-S", str(SCRIPT), "--root", str(self.root), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_patch_release_changes_only_four_metadata_files(self) -> None:
        model_before = {
            relative: (self.root / relative).read_bytes()
            for relative in MODEL_FILES
        }
        completed = self.run_script("0.4.1")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(set(result["changed"]), set(RELEASE_FILES))
        self.assertEqual(result["release_version"], "0.4.1")
        self.assertEqual(
            model_before,
            {relative: (self.root / relative).read_bytes() for relative in MODEL_FILES},
        )
        self.assertEqual(self.run_script("--check").returncode, 0)

    def test_invalid_or_partial_release_metadata_fails_closed(self) -> None:
        self.assertNotEqual(self.run_script("v" + "0.4.1").returncode, 0)
        manifest_path = self.root / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "9.9.9"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assertNotEqual(self.run_script("--check").returncode, 0)


if __name__ == "__main__":
    unittest.main()
