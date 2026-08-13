from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_dispatchers", ROOT / "scripts" / "render_dispatchers.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class RenderDispatchersTests(unittest.TestCase):
    def test_three_posix_dispatchers_are_stable_across_release_changes(self) -> None:
        root = Path("/tmp/Dev Flow root's/运行")
        first = module.render_dispatchers(root, windows=False)
        second = module.render_dispatchers(root, windows=False)
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"dev-flow", "dev-flow-mcp", "dev-flow-uninstall"})
        combined = b"".join(first.values())
        self.assertNotIn(b"releases/", combined)
        self.assertIn(b"stable_dispatcher.py", combined)
        self.assertIn(b"dev-flow-dispatcher/1.0.0", combined)
        self.assertIn(
            b".dev-flow-uninstall-recovery-", first["dev-flow-uninstall"]
        )
        self.assertNotIn(b".dev-flow-uninstall-recovery-", first["dev-flow"])

    def test_three_native_cmd_dispatchers_quote_spaces_and_unicode(self) -> None:
        root = Path("C:/Users/Test User/Dev Flow 运行")
        rendered = module.render_dispatchers(root, windows=True)
        self.assertEqual(
            set(rendered), {"dev-flow.cmd", "dev-flow-mcp.cmd", "dev-flow-uninstall.cmd"}
        )
        for value in rendered.values():
            self.assertIn(b"@echo off\r\n", value)
            self.assertIn(b'C:\\Users\\Test User\\Dev Flow ', value)
            self.assertNotIn(b"releases/", value)
        self.assertIn(
            b".dev-flow-uninstall-recovery-",
            rendered["dev-flow-uninstall.cmd"],
        )
        self.assertNotIn(
            b".dev-flow-uninstall-recovery-", rendered["dev-flow.cmd"]
        )

    def test_relative_runtime_root_is_rejected(self) -> None:
        with self.assertRaisesRegex(module.DispatcherRenderError, "absolute"):
            module.render_dispatchers(Path("relative"), windows=False)


if __name__ == "__main__":
    unittest.main()
