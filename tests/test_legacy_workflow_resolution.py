from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "scripts" / "dev_flow_parts" / "workflow_state.py"
FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "task_state"
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_legacy_workflow_state_tests", STATE_PATH
)
assert SPEC is not None and SPEC.loader is not None
workflow_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workflow_state
SPEC.loader.exec_module(workflow_state)


LEGACY = {
    (1, "full"): {
        "workflow_id": "full-legacy",
        "workflow_version": 2,
        "adapter": "full@legacy-v2",
    },
    (1, "lite"): {
        "workflow_id": "lite-legacy",
        "workflow_version": 2,
        "adapter": "lite@legacy-v2",
    },
    (2, "full"): {
        "workflow_id": "full-legacy",
        "workflow_version": 2,
        "adapter": "full@legacy-v2",
    },
    (2, "lite"): {
        "workflow_id": "lite-legacy",
        "workflow_version": 2,
        "adapter": "lite@legacy-v2",
    },
}


def resolve(state: object, *, purpose: str):
    return workflow_state.resolve_task_workflow(
        state,
        legacy_resolver=LEGACY,
        bundle_resolver={},
        purpose=purpose,
    )


class LegacyWorkflowResolutionTests(unittest.TestCase):
    def test_clean_legacy_inspection_preserves_exact_file_bytes(self) -> None:
        fixture = FIXTURE_ROOT / "schema_v1_full.json"
        original = fixture.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "state.json"
            state_path.write_bytes(original)
            state = json.loads(state_path.read_text(encoding="utf-8"))

            inspection = workflow_state.inspect_task_state(
                state, resolver=resolve
            )

            self.assertTrue(inspection["supported"])
            self.assertTrue(inspection["valid"])
            self.assertTrue(inspection["mutation_ready"])
            self.assertEqual(
                inspection["workflow"]["adapter"], "full@legacy-v2"
            )
            self.assertNotIn("workflow_ref", state)
            self.assertEqual(state_path.read_bytes(), original)

    def test_legacy_selection_is_exactly_schema_and_flow_determined(
        self,
    ) -> None:
        cases = (
            (1, "full", "full@legacy-v2"),
            (1, "lite", "lite@legacy-v2"),
            (2, "full", "full@legacy-v2"),
            (2, "lite", "lite@legacy-v2"),
        )
        for schema_version, flow, adapter in cases:
            with self.subTest(schema_version=schema_version, flow=flow):
                state = {
                    "schema_version": schema_version,
                    "task_id": "legacy",
                    "flow": flow,
                }
                resolution = resolve(state, purpose="mutation")
                self.assertEqual(resolution["adapter"], adapter)
                self.assertEqual(
                    resolution["schema_version"], schema_version
                )
                self.assertEqual(resolution["flow"], flow)
                self.assertEqual(resolution["kind"], "legacy")

    def test_callable_legacy_resolver_receives_only_schema_and_flow(
        self,
    ) -> None:
        calls = []

        def legacy_resolver(schema_version: int, flow: str):
            calls.append((schema_version, flow))
            return LEGACY[(schema_version, flow)]

        resolution = workflow_state.resolve_task_workflow(
            {
                "schema_version": 2,
                "task_id": "legacy",
                "flow": "lite",
            },
            legacy_resolver=legacy_resolver,
            bundle_resolver={},
            purpose="inspection",
        )

        self.assertEqual(calls, [(2, "lite")])
        self.assertEqual(resolution["adapter"], "lite@legacy-v2")

    def test_legacy_resolution_is_immutable_and_never_migrates_state(
        self,
    ) -> None:
        state = json.loads(
            (FIXTURE_ROOT / "schema_v2_lite.json").read_text(
                encoding="utf-8"
            )
        )
        original = json.loads(json.dumps(state))

        resolution = workflow_state.validate_task_state_for_mutation(
            state, resolver=resolve
        )

        with self.assertRaises(TypeError):
            resolution["adapter"] = "current-default"
        self.assertEqual(state, original)
        self.assertNotIn("workflow_ref", state)
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["revision"], 11)

    def test_current_default_or_catalog_order_cannot_affect_legacy_selection(
        self,
    ) -> None:
        state = {
            "schema_version": 2,
            "task_id": "legacy",
            "flow": "full",
        }
        first = dict(reversed(tuple(LEGACY.items())))
        second = dict(LEGACY)

        one = workflow_state.resolve_task_workflow(
            state,
            legacy_resolver=first,
            bundle_resolver={
                "current-default": {"adapter": "full@current"}
            },
            purpose="inspection",
        )
        two = workflow_state.resolve_task_workflow(
            state,
            legacy_resolver=second,
            bundle_resolver={
                "current-default": {"adapter": "full@new-default"}
            },
            purpose="inspection",
        )

        self.assertEqual(dict(one), dict(two))
        self.assertEqual(one["adapter"], "full@legacy-v2")

    def test_missing_or_ambiguous_legacy_identity_fails_closed(self) -> None:
        states = (
            {"schema_version": 2, "task_id": "missing-flow"},
            {
                "schema_version": 2,
                "task_id": "unknown-flow",
                "flow": "experimental",
            },
        )
        for state in states:
            with self.subTest(state=state):
                with self.assertRaises(
                    workflow_state.WorkflowStateError
                ) as raised:
                    workflow_state.validate_task_state_for_mutation(
                        state, resolver=resolve
                    )
                self.assertEqual(
                    raised.exception.code, "LEGACY_WORKFLOW_AMBIGUOUS"
                )

        with self.assertRaises(workflow_state.WorkflowStateError) as raised:
            workflow_state.resolve_task_workflow(
                {
                    "schema_version": 1,
                    "task_id": "ambiguous",
                    "flow": "full",
                },
                legacy_resolver={
                    (1, "full"): [
                        {"adapter": "first"},
                        {"adapter": "second"},
                    ]
                },
                bundle_resolver={},
                purpose="mutation",
            )
        self.assertEqual(
            raised.exception.code, "LEGACY_WORKFLOW_AMBIGUOUS"
        )

    def test_recovery_and_inspection_require_explicit_resolution_purpose(
        self,
    ) -> None:
        state = {
            "schema_version": 1,
            "task_id": "legacy",
            "flow": "full",
        }
        recovery = workflow_state.resolve_task_workflow(
            state,
            legacy_resolver=LEGACY,
            bundle_resolver={},
            purpose="recovery",
        )
        self.assertEqual(recovery["adapter"], "full@legacy-v2")

        with self.assertRaises(workflow_state.WorkflowStateError) as raised:
            workflow_state.resolve_task_workflow(
                state,
                legacy_resolver=LEGACY,
                bundle_resolver={},
                purpose="maybe",
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_RESOLUTION_PURPOSE_INVALID",
        )

    def test_direct_future_inspection_returns_identity_without_resolver(self):
        state = json.loads(
            (FIXTURE_ROOT / "schema_v4_future.json").read_text(
                encoding="utf-8"
            )
        )

        resolution = workflow_state.resolve_task_workflow(
            state,
            legacy_resolver=None,
            bundle_resolver=None,
            purpose="inspection",
        )

        self.assertFalse(resolution["supported"])
        self.assertEqual(resolution["schema_version"], 4)
        self.assertEqual(
            resolution["workflow_ref"]["bundle_sha256"], "f" * 64
        )
        with self.assertRaises(TypeError):
            resolution["workflow_ref"]["bundle_sha256"] = "0" * 64


if __name__ == "__main__":
    unittest.main()
