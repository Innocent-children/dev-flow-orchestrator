from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path
from types import MappingProxyType

from scripts import dev_flow


ROOT = Path(__file__).resolve().parents[1]
V3_IDENTITIES = {
    ("full", 3): (
        "46b18d375f3159d9fef1d9f5f6fb19c06663edf49949952cce3d4d189fbb7423",
        "31b82d3774c56546b9d28237a0dd68226ff0516d247cc0b18457294a0d3b4a12",
    ),
    ("lite", 3): (
        "9bfd642610f6ff6eca9e164ea3544044f979606e2d36a9a6543d5a13e0a929f2",
        "111791bb7dd660dbb22842411cd8af87b8bc103478d0d6414900a993ef326bf3",
    ),
}
V4_CLOSURE_ROLES = (
    "abandoned",
    "accepted",
    "archive",
    "compensation",
    "containment",
    "control",
    "dispatch",
    "observation",
    "reattachment",
    "settlement",
    "unblock",
    "unresolved",
)


class V4PreviewBundleTests(unittest.TestCase):
    def test_v4_bundles_keep_task_schema_v3_and_all_profiles_active(
        self,
    ) -> None:
        services = dev_flow.workflow_runtime_services()

        self.assertEqual(
            set(services.catalog.bundles),
            {
                ("full", 3),
                ("full", 4),
                ("lite", 3),
                ("lite", 4),
                ("full-legacy", 2),
                ("lite-legacy", 2),
            },
        )
        for key, profiles in (
            (("full", 4), ("single-repository", "multi-repository")),
            (("lite", 4), ("single-repository",)),
        ):
            with self.subTest(key=key):
                bundle = services.catalog.resolve(*key)
                self.assertEqual(
                    bundle.graph["task_schema_versions"], (3,)
                )
                self.assertEqual(bundle.execution_profiles, profiles)
                self.assertEqual(
                    set(bundle.active_profiles),
                    set(profiles),
                )
                matching = [
                    item
                    for item in services.catalog.activations
                    if (
                        item["workflow_id"],
                        item["workflow_version"],
                    )
                    == key
                ]
                self.assertEqual(
                    {
                        item["execution_profile"]
                        for item in matching
                        if item["active"]
                    },
                    set(profiles),
                )
        for flow, repository_count, expected_profile in (
            ("lite", 1, "single-repository"),
            ("full", 1, "single-repository"),
            ("full", 2, "multi-repository"),
        ):
            with self.subTest(
                flow=flow,
                repository_count=repository_count,
            ):
                selection = dev_flow.select_task_creation_workflow(
                    flow,
                    repository_count,
                    require_schema_v3=True,
                    services=services,
                )
                self.assertEqual(selection["schema_version"], 3)
                self.assertEqual(
                    selection["execution_profile"],
                    expected_profile,
                )
                self.assertEqual(
                    selection["bundle"].key,
                    (flow, 4),
                )

    def test_v3_identities_and_release_prefix_remain_exact(self) -> None:
        services = dev_flow.workflow_runtime_services()
        for key, expected in V3_IDENTITIES.items():
            with self.subTest(key=key):
                bundle = services.catalog.resolve(*key)
                self.assertEqual(
                    (bundle.graph_sha256, bundle.bundle_sha256),
                    expected,
                )

        ledger = json.loads(
            (ROOT / "workflows" / "release-ledger.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(ledger["reservations"]), 6)
        self.assertEqual(
            [
                (item["workflow_id"], item["workflow_version"])
                for item in ledger["reservations"][4:]
            ],
            [("full", 4), ("lite", 4)],
        )
        self.assertEqual(
            [
                path.relative_to(
                    ROOT / "workflows" / "release-provenance"
                ).as_posix()
                for path in sorted(
                    (
                        ROOT
                        / "workflows"
                        / "release-provenance"
                    ).rglob("*")
                )
                if path.is_file()
            ],
            [
                "first-introduction.json",
                "introduction-epochs/introduction-epoch-1.json",
                "reserved-v3-activation.json",
            ],
        )

    def test_each_v4_action_has_the_exact_versioned_closure(self) -> None:
        services = dev_flow.workflow_runtime_services()
        for key in (("full", 4), ("lite", 4)):
            bundle = services.catalog.resolve(*key)
            for edge in bundle.action_edges:
                with self.subTest(key=key, edge=edge["id"]):
                    closure = edge["handler_closure"]
                    self.assertEqual(
                        tuple(item["role"] for item in closure),
                        V4_CLOSURE_ROLES,
                    )
                    self.assertEqual(
                        tuple(
                            (
                                item["handler"]["registry"],
                                item["handler"]["id"],
                                item["handler"]["version"],
                            )
                            for item in closure
                        ),
                        tuple(
                            (
                                "executors",
                                f"executor.v4-{role}/v2",
                                "v2",
                            )
                            for role in V4_CLOSURE_ROLES
                        ),
                    )

    def test_inactive_v4_creation_falls_back_or_fails_closed(self) -> None:
        fallback = dev_flow.select_task_creation_workflow("full", 1)
        self.assertEqual(fallback["kind"], "legacy")
        self.assertEqual(
            fallback["schema_version"], dev_flow.TASK_SCHEMA_VERSION
        )

        with self.assertRaises(dev_flow.WorkflowCatalogError) as raised:
            dev_flow.select_task_creation_workflow(
                "full", 1, require_schema_v3=True
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_CREATION_INACTIVE"
        )
        self.assertEqual(
            raised.exception.details["workflow_version"], 4
        )

    def test_isolated_v4_activation_readiness_closes_every_handler_role(
        self,
    ) -> None:
        services = dev_flow.workflow_runtime_services()
        bundle = services.catalog.resolve("lite", 4)
        required_suites = sorted(
            {
                *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                    "single-repository"
                ],
                *(
                    str(suite)
                    for edge in bundle.action_edges
                    for suite in edge["required_suites"]
                ),
            }
        )
        activations = []
        selected_found = False
        for frozen in services.catalog.activations:
            item = dict(frozen)
            selected = (
                item["workflow_id"] == "lite"
                and item["workflow_version"] == 4
                and item["execution_profile"] == "single-repository"
            )
            selected_found = selected_found or selected
            item["active"] = selected
            item["required_suites"] = (
                required_suites if selected else []
            )
            activations.append(MappingProxyType(item))
        if not selected_found:
            activations.append(
                MappingProxyType(
                    {
                        "workflow_id": "lite",
                        "workflow_version": 4,
                        "bundle_sha256": bundle.bundle_sha256,
                        "execution_profile": "single-repository",
                        "active": True,
                        "required_suites": required_suites,
                    }
                )
            )
        isolated = dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog,
                activations=tuple(activations),
            ),
        )

        selection = dev_flow.select_task_creation_workflow(
            "lite",
            1,
            require_schema_v3=True,
            services=isolated,
        )

        self.assertEqual(selection["schema_version"], 3)
        self.assertEqual(selection["bundle"].workflow_version, 4)


if __name__ == "__main__":
    unittest.main()
