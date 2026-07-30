from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support import ROOT, runtime_services


class V4StaticClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = runtime_services()

    def test_exact_bundle_and_activation_contract(self) -> None:
        bundles = self.services.catalog.bundles
        self.assertEqual(set(bundles), {("full", 4), ("lite", 4)})
        activation = json.loads(
            (ROOT / "workflows/activation.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                f"{profile['workflow_id']}-{profile['execution_profile']}"
                for profile in activation["profiles"]
            },
            {
                "full-single-repository",
                "full-multi-repository",
                "lite-single-repository",
            },
        )
        self.assertEqual(
            {
                suite
                for profile in activation["profiles"]
                for suite in profile["required_suites"]
            },
            {
                "v4-static-closure",
                "v4-core-runtime",
                "v4-effect-recovery",
                "v4-external-tools",
                "v4-multi-repository",
            },
        )

    def test_every_action_has_one_complete_direct_identity(self) -> None:
        required_roles = {
            "dispatch",
            "observation",
            "settlement",
            "reattachment",
            "control",
            "accepted",
            "abandoned",
            "unresolved",
            "compensation",
            "containment",
            "archive",
            "unblock",
        }
        placements = set()
        for key, bundle in self.services.catalog.bundles.items():
            for edge in bundle.action_edges:
                handler = edge["handler"]
                closure = edge["handler_closure"]
                self.assertEqual({item["role"] for item in closure}, required_roles)
                identity = (
                    key,
                    edge["id"],
                    handler["registry"],
                    handler["id"],
                    handler["version"],
                )
                self.assertNotIn(identity, placements)
                placements.add(identity)
        self.assertTrue(placements)

    def test_package_has_no_predecessor_workflow_identity(self) -> None:
        needles = (
            "V" + "2",
            "V" + "3",
            "v" + "3",
            "leg" + "acy",
            "task schema v" + "2",
            "schema-v" + "2 tasks",
            "a v" + "2 risk contract",
            "get(\"schema_version\", " + "1)",
            "get('schema_version', " + "1)",
        )
        roots = [
            ROOT / ".codex-plugin",
            ROOT / "hooks",
            ROOT / "scripts",
            ROOT / "skills",
            ROOT / "templates",
            ROOT / "workflows",
        ]
        offenders = []
        noninstallable_validators = {
            "scripts/audit_runtime_imports.py",
            "scripts/candidate_identity.py",
            "scripts/run_bundled_validators.py",
            "scripts/validate_package.py",
        }
        for root in roots:
            for path in ([root] if root.is_file() else root.rglob("*")):
                if not path.is_file() or path.suffix == ".pyc":
                    continue
                if (
                    path.relative_to(ROOT).as_posix()
                    in noninstallable_validators
                ):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeError:
                    continue
                if any(needle in text for needle in needles):
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_runtime_import_audit_covers_all_shipped_entrypoints(self) -> None:
        namespace = runpy.run_path(
            str(ROOT / "scripts/audit_runtime_imports.py"),
            run_name="v4_runtime_import_audit",
        )
        result = namespace["audit"](ROOT)
        self.assertTrue(result["ok"], result["violations"])
        self.assertTrue(
            {
                "scripts/dev_flow.py",
                "scripts/dev_flow_mcp.py",
                "hooks/dev_flow_hook.py",
            }.issubset(set(result["files"]))
        )

        fake_paths = {
            "stdlib": "/opt/python/lib/python3.13",
            "platstdlib": "/opt/python/lib/python3.13",
            "purelib": "/opt/python/lib/python3.13/site-packages",
            "platlib": "/opt/python/lib/python3.13/site-packages",
        }
        fake_spec = SimpleNamespace(
            origin="/opt/python/lib/python3.13/site-packages/probe.py"
        )
        with (
            mock.patch.object(
                namespace["importlib"].util,
                "find_spec",
                return_value=fake_spec,
            ),
            mock.patch.object(
                namespace["sysconfig"],
                "get_paths",
                return_value=fake_paths,
            ),
        ):
            self.assertFalse(
                namespace["_is_stdlib"]("third_party_probe", set())
            )


if __name__ == "__main__":
    unittest.main()
