from __future__ import annotations

import argparse
import contextlib
import errno
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case

SCRIPT = test_case.SCRIPT
SUPPORT = test_case.SUPPORT
dev_flow = test_case.dev_flow
git = test_case.git


class DevFlowScopeTest(test_case.DevFlowTestCase):
    def test_absent_scope_configuration_stays_active_everywhere(self) -> None:
        elsewhere = self.root / "unrelated"
        elsewhere.mkdir()
        response = self.cli("scope", "--check", str(elsewhere))
        self.assertEqual(response["effective"]["mode"], "all")
        self.assertEqual(response["summary"], "active in every directory")
        self.assertFalse(response["changed"])
        self.assertTrue(response["check"]["in_scope"])
        self.assertEqual(response["check"]["rule"], "default")
        # Reading the scope must not create configuration the user never asked for.
        self.assertFalse(Path(response["config_path"]).exists())

    def test_first_included_directory_activates_the_allowlist(self) -> None:
        included = self.root / "included"
        included.mkdir()
        excluded = self.root / "elsewhere"
        excluded.mkdir()
        response = self.cli("scope", "--add", str(included))
        self.assertTrue(response["changed"])
        self.assertEqual(response["scope"]["mode"], "allowlist")
        self.assertEqual(response["scope"]["include"], self.canonical(included))
        self.assertEqual(response["missing_paths"], [])
        self.assertTrue(
            self.cli("scope", "--check", str(included / "nested" / "deep"))["check"][
                "in_scope"
            ]
        )
        self.assertFalse(self.cli("scope", "--check", str(excluded))["check"]["in_scope"])
        # A second addition must not silently flip the mode back.
        second = self.cli("scope", "--add", str(excluded))
        self.assertEqual(second["scope"]["mode"], "allowlist")
        self.assertEqual(second["scope"]["include"], self.canonical(included, excluded))
        repeated = self.cli("scope", "--add", str(included))
        self.assertFalse(repeated["changed"])

    def test_scope_matching_prefers_the_deepest_configured_directory(self) -> None:
        work = self.root / "work"
        vendor = work / "vendor"
        mine = vendor / "mine"
        mine.mkdir(parents=True)
        self.cli(
            "scope",
            "--add",
            str(work),
            "--add-exclude",
            str(vendor),
            "--add",
            str(mine),
        )
        for path, expected, rule in (
            (work / "app", True, "include"),
            (vendor / "other", False, "exclude"),
            (mine / "deep", True, "include"),
            (self.root / "outside", False, "default"),
        ):
            with self.subTest(path=path):
                check = self.cli("scope", "--check", str(path))["check"]
                self.assertEqual(check["in_scope"], expected)
                self.assertEqual(check["rule"], rule)
        # An exactly overlapping pair resolves to the exclusion.
        self.cli("scope", "--add-exclude", str(work))
        self.assertFalse(self.cli("scope", "--check", str(work / "app"))["check"]["in_scope"])

    def test_denylist_mode_excludes_without_an_allowlist(self) -> None:
        skipped = self.root / "skipped"
        skipped.mkdir()
        response = self.cli("scope", "--mode", "all", "--add-exclude", str(skipped))
        self.assertEqual(response["scope"]["mode"], "all")
        self.assertEqual(response["summary"], "active in every directory except the excluded ones")
        self.assertFalse(self.cli("scope", "--check", str(skipped / "a"))["check"]["in_scope"])
        self.assertTrue(self.cli("scope", "--check", str(self.root))["check"]["in_scope"])

    def test_environment_overrides_the_stored_scope(self) -> None:
        stored = self.root / "stored"
        stored.mkdir()
        override = self.root / "override"
        override.mkdir()
        self.cli("scope", "--add", str(stored))
        with mock.patch.dict(os.environ, {dev_flow.SCOPE_INCLUDE_ENV: str(override)}):
            response = self.cli("scope", "--check", str(stored))
            self.assertEqual(response["overrides"], {"include": dev_flow.SCOPE_INCLUDE_ENV})
            self.assertEqual(response["effective"]["include"], self.canonical(override))
            # The stored configuration is reported unchanged next to the override.
            self.assertEqual(response["scope"]["include"], self.canonical(stored))
            self.assertFalse(response["check"]["in_scope"])
            self.assertTrue(self.cli("scope", "--check", str(override))["check"]["in_scope"])
        with mock.patch.dict(
            os.environ,
            {dev_flow.SCOPE_EXCLUDE_ENV: str(stored / "vendor")},
        ):
            response = self.cli("scope", "--check", str(stored / "vendor" / "x"))
            self.assertEqual(response["effective"]["mode"], "allowlist")
            self.assertFalse(response["check"]["in_scope"])
        self.assertTrue(self.cli("scope", "--check", str(stored))["check"]["in_scope"])

    def test_scope_edits_are_validated_and_reversible(self) -> None:
        included = self.root / "included"
        included.mkdir()
        self.cli("scope", "--add", str(included))
        missing = self.cli("scope", "--add", str(self.root / "not-created"))
        self.assertEqual(missing["missing_paths"], self.canonical(self.root / "not-created"))
        unknown = self.cli("scope", "--remove", str(self.root / "never"), expected_code=2)
        self.assertEqual(unknown["error"]["code"], "SCOPE_PATH_NOT_CONFIGURED")
        invalid = self.cli("scope", "--mode", "sometimes", expected_code=2)
        self.assertEqual(invalid["error"]["code"], "INVALID_ARGUMENT")
        muted = self.cli(
            "scope",
            "--remove",
            str(included),
            "--remove",
            str(self.root / "not-created"),
            "--check",
            str(included),
        )
        self.assertEqual(muted["summary"], "inactive in every directory")
        self.assertFalse(muted["check"]["in_scope"])
        cleared = self.cli("scope", "--clear", "--check", str(self.root / "anywhere"))
        self.assertEqual(cleared["scope"], {"mode": "all", "include": [], "exclude": []})
        self.assertTrue(cleared["check"]["in_scope"])

    def test_unusable_scope_configuration_is_reported(self) -> None:
        config = self.data / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("{ not json", encoding="utf-8")
        unreadable = self.cli("scope", expected_code=2)
        self.assertEqual(unreadable["error"]["code"], "CONFIG_INVALID")
        config.write_text(
            json.dumps({"schema_version": 1, "scope": {"mode": "sometimes"}}),
            encoding="utf-8",
        )
        bad_mode = self.cli("scope", expected_code=2)
        self.assertEqual(bad_mode["error"]["code"], "CONFIG_INVALID")
        blocked = self.cli("scope", "--add", str(self.root), expected_code=2)
        self.assertEqual(blocked["error"]["code"], "CONFIG_INVALID")
        # Clearing is the recovery path and must not need a readable file.
        recovered = self.cli("scope", "--clear")
        self.assertTrue(recovered["changed"])
        self.assertEqual(recovered["scope"], {"mode": "all", "include": [], "exclude": []})

    def test_start_refuses_a_repository_outside_the_configured_scope(self) -> None:
        repo, _ = self.make_repo("scoped")
        included = self.root / "included"
        included.mkdir()
        self.cli("scope", "--add", str(included))
        rejected = self.cli(
            "start",
            "--task-id",
            "out-of-scope",
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "Implement deterministic flow",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(rejected["error"]["code"], "OUT_OF_SCOPE")
        self.assertEqual(rejected["error"]["details"]["path"], str(repo.resolve()))
        self.assertEqual(
            rejected["error"]["details"]["config_path"],
            str(dev_flow.config_path(self.data)),
        )
        self.assertFalse((self.data / "tasks" / "out-of-scope").exists())
        self.cli("scope", "--add", str(repo))
        accepted = self.start(repo, task_id="in-scope")
        self.assertEqual(accepted["task"]["status"], "INTAKE")

    def test_cli_help_is_english_and_protected_branch_extends_defaults(
        self,
    ) -> None:
        parser = dev_flow.build_parser()
        command_action = next(
            action
            for action in parser._actions
            if action.dest == "command"
        )
        parser_help = {"root": parser.format_help()}
        parser_help.update(
            {
                command: command_parser.format_help()
                for command, command_parser in command_action.choices.items()
            }
        )
        for command, help_text in parser_help.items():
            with self.subTest(command=command):
                self.assertFalse(
                    any(
                        "\u3400" <= character <= "\u9fff"
                        or "\uf900" <= character <= "\ufaff"
                        for character in help_text
                    ),
                    help_text,
                )

        start_help = " ".join(parser_help["start"].split())
        self.assertIn(
            "additional protected branch name; repeat to extend, never "
            "replace, the default main/master/trunk set",
            start_help,
        )



if __name__ == "__main__":
    unittest.main()
