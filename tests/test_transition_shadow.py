from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "transition_engine.py"
)
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_transition_shadow", ENGINE_PATH
)
assert SPEC is not None and SPEC.loader is not None
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


def graph(*, with_reducer: bool = False) -> dict:
    return {
        "schema": "dev-flow-workflow/v1",
        "workflow_id": "legacy",
        "workflow_version": 2,
        "legacy_adapter": "legacy-v2",
        "edges": [
            {
                "id": "legacy.intake.ready",
                "source": "INTAKE",
                "target": "READY",
                "trigger": {"kind": "action", "id": "transition"},
                "confirmation": "explicit",
                "priority": 1,
                "guards": [],
                "reducers": (
                    ["reducer.note/v1"] if with_reducer else []
                ),
                "side_effects": ["task-state"],
                "allowed_state_writes": (
                    ["/status", "/nested"]
                    if with_reducer
                    else ["/status"]
                ),
            }
        ],
    }


def state() -> dict:
    return {
        "schema_version": 2,
        "task_id": "legacy-task",
        "revision": 8,
        "status": "INTAKE",
        "nested": {"notes": []},
    }


class TransitionShadowTests(unittest.TestCase):
    def make_engine(
        self, *, with_reducer: bool = False, missing: bool = False
    ) -> object:
        def reducer(
            projected: object,
            _edge: object,
            _action: object,
            _approval: object,
            _capability: object,
        ) -> object:
            candidate = {
                key: engine._thaw_contract_value(value)
                for key, value in projected.items()
            }
            candidate["nested"]["notes"].append("shadow")
            return engine.ReducerResult(candidate)

        reducers = (
            {}
            if missing
            else {"reducer.note/v1": reducer}
        )
        return engine.TransitionEngine(
            graph(with_reducer=with_reducer),
            guard_resolver=lambda identifier, _version: {}[identifier],
            reducer_resolver=lambda identifier, _version: reducers[
                identifier
            ],
        )

    def arguments(self) -> dict:
        return {
            "expected_revision": 8,
            "action_id": "transition",
            "action_parameters": {"note": "shadow"},
            "evidence": {"fingerprint": "a" * 64},
            "preview": True,
        }

    def test_shadow_match_runs_on_copies_and_preserves_all_inputs(
        self,
    ) -> None:
        workflow = self.make_engine(with_reducer=True)
        current = state()
        legacy = copy.deepcopy(current)
        legacy["nested"]["notes"].append("shadow")
        legacy["status"] = "READY"
        current_before = copy.deepcopy(current)
        legacy_before = copy.deepcopy(legacy)
        arguments = self.arguments()
        arguments_before = copy.deepcopy(arguments)

        first = workflow.evaluate_shadow(
            legacy, current, **arguments
        )
        second = engine.evaluate_transition_shadow(
            workflow, legacy, current, **arguments
        )

        self.assertTrue(first["matched"])
        self.assertTrue(first["input_unchanged"])
        self.assertIsNone(first["blocker"])
        self.assertEqual(
            first["diagnostic_sha256"],
            second["diagnostic_sha256"],
        )
        self.assertEqual(current, current_before)
        self.assertEqual(legacy, legacy_before)
        self.assertEqual(arguments, arguments_before)

    def test_shadow_mismatch_diagnostics_are_deterministic_and_bounded(
        self,
    ) -> None:
        legacy = {
            f"field-{index}-{'x' * 200}": index
            for index in range(100)
        }
        current = {key: -value for key, value in legacy.items()}

        first = engine.compare_shadow_outcomes(legacy, current)
        second = engine.compare_shadow_outcomes(
            dict(reversed(list(legacy.items()))),
            dict(reversed(list(current.items()))),
        )

        self.assertFalse(first["matched"])
        self.assertEqual(first["difference_count"], 99)
        self.assertTrue(first["differences_truncated"])
        self.assertLessEqual(len(first["differences"]), 16)
        self.assertEqual(
            first["diagnostic_sha256"],
            second["diagnostic_sha256"],
        )
        self.assertLess(
            len(
                json.dumps(
                    first, ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
            ),
            4096,
        )

    def test_shadow_returns_stable_blocker_instead_of_resolver_keyerror(
        self,
    ) -> None:
        workflow = self.make_engine(
            with_reducer=True, missing=True
        )
        current = state()
        legacy = {**current, "status": "READY"}

        first = workflow.evaluate_shadow(
            legacy, current, **self.arguments()
        )
        second = workflow.evaluate_shadow(
            legacy, current, **self.arguments()
        )

        self.assertFalse(first["matched"])
        self.assertTrue(first["input_unchanged"])
        self.assertEqual(
            first["blocker"]["code"],
            "WORKFLOW_CONTRACT_UNAVAILABLE",
        )
        self.assertEqual(
            first["diagnostic_sha256"],
            second["diagnostic_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
