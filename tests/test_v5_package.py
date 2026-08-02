"""Package validation covers installed entrypoints and public metadata."""

from __future__ import annotations

from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_package import validate


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".codebase-memory", ".pytest_cache", "__pycache__"}
    return set(names) & ignored


class PackageValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.candidate = Path(self.temporary.name) / "candidate with spaces"
        shutil.copytree(ROOT, self.candidate, ignore=_ignore)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_current_candidate_is_valid(self) -> None:
        self.assertEqual(validate(self.candidate)["errors"], [])

    def test_missing_hook_bootstrap_is_reported(self) -> None:
        (self.candidate / "hooks" / "dev_flow_hook.py").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn("missing hooks/dev_flow_hook.py", result["errors"])

    def test_non_executable_launcher_is_reported(self) -> None:
        launcher = self.candidate / "scripts" / "dev_flow_python_launcher"
        launcher.chmod(stat.S_IRUSR | stat.S_IWUSR)
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn(
            "scripts/dev_flow_python_launcher is not executable",
            result["errors"],
        )

    def test_stale_public_selector_is_reported(self) -> None:
        for name in ("README.md", "README_CN.md"):
            with self.subTest(name=name):
                readme = self.candidate / name
                original = readme.read_text(encoding="utf-8")
                readme.write_text(original + "\nUse lite@4.\n", encoding="utf-8")
                result = validate(self.candidate)
                self.assertFalse(result["ok"])
                self.assertIn(
                    "stale public workflow selector remains: " + name,
                    result["errors"],
                )
                readme.write_text(original, encoding="utf-8")

    def test_missing_canonical_chinese_readme_is_reported(self) -> None:
        (self.candidate / "README_CN.md").unlink()
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn("missing README_CN.md", result["errors"])

    def test_foreign_candidate_uses_its_own_workflow(self) -> None:
        workflow = self.candidate / "workflows" / "lite.yaml"
        workflow.write_text("schema: [\n", encoding="utf-8")
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(
                "built-in workflow 'lite' failed to load" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    def test_stale_main_skill_agent_guidance_is_reported(self) -> None:
        metadata = (
            self.candidate
            / "skills"
            / "follow-dev-flow"
            / "agents"
            / "openai.yaml"
        )
        current = metadata.read_text(encoding="utf-8")
        stale_variants = (
            current.replace("V5", "V4"),
            current.replace("单个 Git 仓库", "单仓库或多仓库"),
        )
        for stale in stale_variants:
            with self.subTest(stale=stale):
                metadata.write_text(stale, encoding="utf-8")
                result = validate(self.candidate)
                self.assertFalse(result["ok"])
                self.assertIn(
                    "follow-dev-flow agent metadata contains stale V4 or "
                    "multi-repository guidance",
                    result["errors"],
                )

    def test_main_skill_default_prompt_invokes_skill(self) -> None:
        metadata = (
            self.candidate
            / "skills"
            / "follow-dev-flow"
            / "agents"
            / "openai.yaml"
        )
        metadata.write_text(
            metadata.read_text(encoding="utf-8").replace(
                "$follow-dev-flow", "follow-dev-flow"
            ),
            encoding="utf-8",
        )
        result = validate(self.candidate)
        self.assertFalse(result["ok"])
        self.assertIn(
            "follow-dev-flow default_prompt does not invoke $follow-dev-flow",
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
