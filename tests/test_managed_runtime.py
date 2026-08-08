"""Focused managed-runtime and wheel asset boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.product import WORKFLOW_IDS
from dev_flow_orchestrator.workflows import load_definition
from scripts import manage_runtime


class ManagedRuntimeTests(unittest.TestCase):
    def test_real_locked_runtime_create_receipt_smoke_and_reuse(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is required for managed-runtime integration")
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status_before = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        with tempfile.TemporaryDirectory(prefix="dev-flow-managed-runtime-") as temporary:
            base = Path(temporary)
            runtime_root = base / "runtime with spaces 雪's"
            data_root = base / "task data"
            data_root.mkdir()
            sentinel = data_root / "existing-task-bytes"
            sentinel.write_bytes(b"unchanged\n")

            created = manage_runtime.build(ROOT, runtime_root, commit, data_root)
            reused = manage_runtime.build(ROOT, runtime_root, commit, data_root)

            self.assertTrue(created["ok"])
            self.assertFalse(created["reused"])
            self.assertTrue(reused["reused"])
            self.assertEqual(created["runtime_dir"], reused["runtime_dir"])
            self.assertEqual(created["receipt"], reused["receipt"])
            self.assertEqual(created["receipt"]["activation_action"], "create")
            self.assertEqual(len(created["receipt"]["runtime_identity"]), 64)
            self.assertEqual(sentinel.read_bytes(), b"unchanged\n")
            self.assertNotIn(str(runtime_root), json.dumps(created["receipt"]))
            self.assertNotIn(str(data_root), json.dumps(created["receipt"]))
            moved_root = base / "moved runtime"
            runtime_root.rename(moved_root)
            with self.assertRaises(manage_runtime.RuntimeBuildError) as moved:
                manage_runtime.build(ROOT, moved_root, commit, data_root)
            self.assertIn("unverified prior release", str(moved.exception))
        status_after = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(status_after, status_before)

    def test_existing_unmarked_runtime_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-unowned-runtime-") as temporary:
            runtime_root = Path(temporary) / "existing"
            runtime_root.mkdir()
            sentinel = runtime_root / "user-owned"
            sentinel.write_bytes(b"preserve\n")
            with self.assertRaises(manage_runtime.RuntimeBuildError) as context:
                manage_runtime.build(ROOT, runtime_root, "a" * 40, None)
            self.assertIn("ownership marker", str(context.exception))
            self.assertEqual(sentinel.read_bytes(), b"preserve\n")
            self.assertFalse((runtime_root / manage_runtime.ROOT_MARKER).exists())

    @unittest.skipIf(os.name == "nt", "ordinary Windows users may lack symlink privilege")
    def test_runtime_root_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-runtime-link-") as temporary:
            base = Path(temporary)
            target = base / "target"
            target.mkdir()
            selected = base / "selected"
            selected.symlink_to(target, target_is_directory=True)
            with self.assertRaises(manage_runtime.RuntimeBuildError) as context:
                manage_runtime.build(ROOT, selected, "a" * 40, None)
            self.assertIn("symbolic link", str(context.exception))
            self.assertEqual(tuple(target.iterdir()), ())

    def test_built_wheel_contains_and_resolves_the_exact_official_workflows(self) -> None:
        expected = {
            workflow_id: load_definition(workflow_id).identity
            for workflow_id in WORKFLOW_IDS
        }
        with tempfile.TemporaryDirectory(prefix="dev-flow-wheel-assets-") as temporary:
            root = Path(temporary)
            wheel_dir = root / "dist"
            completed = subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            wheels = list(wheel_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            extracted = root / "extracted"
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
                for workflow_id in WORKFLOW_IDS:
                    self.assertIn(
                        "dev_flow_orchestrator/workflow_assets/{}.yaml".format(
                            workflow_id
                        ),
                        names,
                    )
                archive.extractall(extracted)

            code = """
import json,sys
sys.path.insert(0, sys.argv[1])
from dev_flow_orchestrator.product import WORKFLOW_IDS
from dev_flow_orchestrator.workflows import BUILTIN_DIR, load_definition
print(json.dumps({
    'builtin_dir': BUILTIN_DIR.name,
    'identities': {item: load_definition(item).identity for item in WORKFLOW_IDS},
}, sort_keys=True))
"""
            probed = subprocess.run(
                [sys.executable, "-I", "-S", "-c", code, str(extracted)],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(probed.returncode, 0, probed.stderr)
            result = json.loads(probed.stdout)
            self.assertEqual(result["builtin_dir"], "workflow_assets")
            self.assertEqual(result["identities"], expected)


if __name__ == "__main__":
    unittest.main()
