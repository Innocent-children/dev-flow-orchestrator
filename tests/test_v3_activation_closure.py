from __future__ import annotations

import dataclasses
from types import MappingProxyType
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow


class V3ActivationClosureTests(DevFlowTestCase):
    @staticmethod
    def _services_with_profile(
        flow: str,
        execution_profile: str,
        *,
        active: bool,
    ) -> object:
        services = dev_flow.workflow_runtime_services()
        bundle = services.catalog.resolve(flow, 4)
        action_suites = {
            str(suite)
            for edge in bundle.action_edges
            for suite in edge["required_suites"]
        }
        activations = []
        selected_found = False
        for frozen in services.catalog.activations:
            item = dict(frozen)
            selected = (
                item["workflow_id"] == flow
                and item["workflow_version"] == 4
                and item["execution_profile"] == execution_profile
            )
            selected_found = selected_found or selected
            item["active"] = bool(active and selected)
            item["required_suites"] = (
                sorted(
                    {
                        *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                            execution_profile
                        ],
                        *action_suites,
                    }
                )
                if selected
                else []
            )
            activations.append(MappingProxyType(item))
        if not selected_found:
            activations.append(
                MappingProxyType(
                    {
                        "workflow_id": flow,
                        "workflow_version": 4,
                        "bundle_sha256": bundle.bundle_sha256,
                        "execution_profile": execution_profile,
                        "active": bool(active),
                        "required_suites": sorted(
                            {
                                *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                                    execution_profile
                                ],
                                *action_suites,
                            }
                        ),
                    }
                )
            )
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog, activations=tuple(activations)
            ),
        )

    @staticmethod
    def _replace_bundle(services: object, bundle: object) -> object:
        bundles = dict(services.catalog.bundles)
        bundles[bundle.key] = bundle
        identities = dict(services.catalog.bundles_by_identity)
        identities[bundle.bundle_sha256] = bundle
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog,
                bundles=MappingProxyType(bundles),
                bundles_by_identity=MappingProxyType(identities),
            ),
        )

    @staticmethod
    def _replace_action(
        bundle: object,
        index: int,
        mutate: object,
    ) -> object:
        edges = list(bundle.action_edges)
        value = dict(edges[index])
        assert callable(mutate)
        mutate(value)
        edges[index] = MappingProxyType(value)
        return dataclasses.replace(bundle, action_edges=tuple(edges))

    def _assert_incomplete(
        self, services: object, *, repositories: int = 1
    ) -> None:
        with self.assertRaises(dev_flow.WorkflowCatalogError) as raised:
            dev_flow.select_task_creation_workflow(
                "full",
                repositories,
                require_schema_v3=True,
                services=services,
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_ACTIVATION_INCOMPLETE"
        )

    def test_activation_rechecks_every_compiled_action_contract(self) -> None:
        services = self._services_with_profile(
            "full", "single-repository", active=True
        )
        bundle = services.catalog.resolve("full", 4)
        dispatch_index = next(
            index
            for index, edge in enumerate(bundle.action_edges)
            if edge["effects"][0]["dispatch"] == "single-dispatch"
        )

        def without_event(edge: dict[str, object]) -> None:
            edge.pop("canonical_event")

        def without_reducer(edge: dict[str, object]) -> None:
            edge["reducers"] = ()

        def forged_write_set(edge: dict[str, object]) -> None:
            edge["allowed_state_writes"] = ["/"]

        def incomplete_effect(edge: dict[str, object]) -> None:
            effects = [dict(item) for item in edge["effects"]]
            effects[0]["target_controls"] = ()
            edge["effects"] = tuple(
                MappingProxyType(item) for item in effects
            )

        def replay_dispatch(edge: dict[str, object]) -> None:
            effects = [dict(item) for item in edge["effects"]]
            effects[0]["recovery"] = MappingProxyType(
                {
                    **dict(effects[0]["recovery"]),
                    "redispatch": "allowed",
                }
            )
            edge["effects"] = tuple(
                MappingProxyType(item) for item in effects
            )

        def missing_suite(edge: dict[str, object]) -> None:
            edge["required_suites"] = ("action-policy",)

        cases = (
            self._replace_action(bundle, 0, without_event),
            self._replace_action(bundle, 0, without_reducer),
            self._replace_action(bundle, 0, forged_write_set),
            self._replace_action(
                bundle, dispatch_index, incomplete_effect
            ),
            self._replace_action(
                bundle, dispatch_index, replay_dispatch
            ),
            self._replace_action(bundle, 0, missing_suite),
            dataclasses.replace(
                bundle, action_edges=bundle.action_edges[1:]
            ),
        )
        for index, candidate in enumerate(cases):
            with self.subTest(case=index):
                self._assert_incomplete(
                    self._replace_bundle(services, candidate)
                )

    def test_activation_rejects_ambiguous_public_selector_and_movement_gap(
        self,
    ) -> None:
        services = self._services_with_profile(
            "full", "single-repository", active=True
        )
        bundle = services.catalog.resolve("full", 4)
        by_source: dict[str, list[int]] = {}
        for index, edge in enumerate(bundle.action_edges):
            by_source.setdefault(str(edge["source"]), []).append(index)
        source, indexes = next(
            (source, indexes)
            for source, indexes in by_source.items()
            if len(indexes) >= 2
        )
        first = bundle.action_edges[indexes[0]]

        def duplicate_selector(edge: dict[str, object]) -> None:
            edge["public_command"] = first["public_command"]

        ambiguous = self._replace_action(
            bundle, indexes[1], duplicate_selector
        )
        self._assert_incomplete(
            self._replace_bundle(services, ambiguous)
        )

        incoming = [
            edge
            for edge in bundle.edges
            if edge["target"] == source
            and edge["source"] != source
        ]
        self.assertTrue(incoming)
        disconnected = dataclasses.replace(
            bundle,
            edges=tuple(
                edge for edge in bundle.edges if edge not in incoming
            ),
        )
        self._assert_incomplete(
            self._replace_bundle(services, disconnected)
        )

    def test_deactivation_does_not_strand_pinned_multi_repository_task(
        self,
    ) -> None:
        first, _ = self.make_repo("activation-closure-first")
        second, _ = self.make_repo("activation-closure-second")
        active = self._services_with_profile(
            "full", "multi-repository", active=True
        )
        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", active
        ):
            started = self.cli(
                "start",
                "pinned multi repository task survives deactivation",
                "--repo",
                str(first),
                "--repo",
                str(second),
                "--task-id",
                "activation-closure-multi",
                "--workspace-strategy",
                "worktree",
            )
        self.assertEqual(started["task"]["schema_version"], 3)
        self.assertEqual(
            started["task"]["execution_profile"], "multi-repository"
        )

        inactive = self._services_with_profile(
            "full", "multi-repository", active=False
        )
        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", inactive
        ):
            loaded = dev_flow.load_state(
                "activation-closure-multi", self.data
            )
            resolution = dev_flow.resolve_loaded_task_workflow(
                loaded, purpose="inspection"
            )
        self.assertEqual(
            resolution["bundle_sha256"],
            loaded["workflow_ref"]["bundle_sha256"],
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
