from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "transition_engine.py"
)
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_transition_engine", ENGINE_PATH
)
assert SPEC is not None and SPEC.loader is not None
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


def graph(*edges: dict) -> dict:
    return {
        "schema": "dev-flow-workflow/v1",
        "workflow_id": "test",
        "workflow_version": 1,
        "legacy_adapter": "test-v2",
        "edges": list(edges),
    }


def edge(
    identifier: str = "test.intake.ready/v1",
    *,
    source: str = "INTAKE",
    target: str = "READY",
    action: str = "transition",
    confirmation: str = "explicit",
    priority: int = 0,
    guards: tuple[str, ...] = (),
    reducers: tuple[str, ...] = (),
    allowed: tuple[str, ...] = ("/status",),
) -> dict:
    return {
        "id": identifier,
        "from": source,
        "to": target,
        "trigger": {"action_id": action},
        "confirmation": confirmation,
        "priority": priority,
        "guards": list(guards),
        "reducers": list(reducers),
        "side_effects": ["task-state"],
        "allowed_state_writes": list(allowed),
    }


def state() -> dict:
    return {
        "schema_version": 2,
        "task_id": "task-1",
        "revision": 7,
        "status": "INTAKE",
        "flow": "full",
        "notes": [],
        "approvals": {},
    }


def passing_guard(
    _state: object, _evidence: object, _capability: object
) -> object:
    return engine.GuardResult(
        passed=True,
        evidence={"current": True},
    )


class TransitionEngineTests(unittest.TestCase):
    def make_engine(
        self,
        graph_value: dict,
        *,
        guards: dict | None = None,
        reducers: dict | None = None,
    ) -> object:
        guard_values = guards or {}
        reducer_values = reducers or {}
        return engine.TransitionEngine(
            graph_value,
            guard_resolver=lambda identifier, _version: guard_values[
                identifier
            ],
            reducer_resolver=lambda identifier, _version: reducer_values[
                identifier
            ],
        )

    def test_edge_selection_uses_priority_not_manifest_order(self) -> None:
        low = edge("edge.low/v1", priority=1)
        high = edge("edge.high/v1", priority=9)
        first = self.make_engine(graph(low, high))
        second = self.make_engine(graph(high, low))

        self.assertEqual(
            first.resolve_edge("INTAKE", "transition")["id"],
            "edge.high/v1",
        )
        self.assertEqual(
            second.resolve_edge("INTAKE", "transition")["id"],
            "edge.high/v1",
        )

    def test_equal_priority_requires_explicit_edge_identity(self) -> None:
        workflow = self.make_engine(
            graph(edge("edge.a/v1"), edge("edge.b/v1"))
        )

        with self.assertRaises(engine.TransitionEngineError) as raised:
            workflow.resolve_edge("INTAKE", "transition")
        self.assertEqual(
            raised.exception.code, "EDGE_SELECTION_AMBIGUOUS"
        )
        self.assertEqual(
            workflow.resolve_edge(
                "INTAKE", "transition", edge_id="edge.b/v1"
            )["id"],
            "edge.b/v1",
        )

    def test_explicit_intent_binds_revision_bundle_handlers_and_evidence(
        self,
    ) -> None:
        workflow = self.make_engine(
            graph(
                edge(
                    guards=("guard.current/v1",),
                )
            ),
            guards={"guard.current/v1": passing_guard},
        )
        current = state()
        current["workflow_ref"] = {
            "workflow_id": "full",
            "workflow_version": 3,
            "bundle_sha256": "a" * 64,
        }

        preview = workflow.evaluate(
            current,
            expected_revision=7,
            action_id="transition",
            action_parameters={"note": "approved"},
            evidence={"fingerprint": "b" * 64},
            preview=True,
        )

        self.assertEqual(
            preview.intent["workflow_ref"]["bundle_sha256"], "a" * 64
        )
        self.assertEqual(preview.intent["base_revision"], 7)
        self.assertEqual(
            preview.intent["handlers"]["guards"],
            ("guard.current/v1",),
        )
        self.assertEqual(preview.changed_paths, ("/status",))
        applied = workflow.evaluate(
            current,
            expected_revision=7,
            action_id="transition",
            action_parameters={"note": "approved"},
            evidence={"fingerprint": "b" * 64},
            confirm_intent=preview.intent["intent_id"],
        )
        self.assertEqual(applied.candidate_state["status"], "READY")

        with self.assertRaises(engine.TransitionEngineError) as raised:
            workflow.evaluate(
                {**current, "revision": 8},
                expected_revision=8,
                action_id="transition",
                action_parameters={"note": "approved"},
                evidence={"fingerprint": "b" * 64},
                confirm_intent=preview.intent["intent_id"],
            )
        self.assertEqual(raised.exception.code, "INTENT_STALE")

    def test_terminal_movement_cannot_be_automatic(self) -> None:
        workflow = self.make_engine(
            graph(
                edge(
                    target="DONE",
                    confirmation="automatic",
                )
            )
        )

        with self.assertRaises(engine.TransitionEngineError) as raised:
            workflow.evaluate(
                state(),
                expected_revision=7,
                action_id="transition",
                action_parameters={},
                evidence={},
                preview=True,
            )
        self.assertEqual(
            raised.exception.code, "TERMINAL_CONFIRMATION_REQUIRED"
        )

    def test_guard_inputs_are_immutable_and_blockers_are_structured(
        self,
    ) -> None:
        def mutating_guard(
            projected: object, _evidence: object, _capability: object
        ) -> object:
            with self.assertRaises(TypeError):
                projected["status"] = "READY"
            return engine.GuardResult(
                passed=False,
                evidence={"current": False},
                blockers=({"code": "NOT_CURRENT"},),
            )

        workflow = self.make_engine(
            graph(edge(guards=("guard.current/v1",))),
            guards={"guard.current/v1": mutating_guard},
        )

        with self.assertRaises(engine.TransitionEngineError) as raised:
            workflow.evaluate(
                state(),
                expected_revision=7,
                action_id="transition",
                action_parameters={},
                evidence={},
                preview=True,
            )
        self.assertEqual(
            raised.exception.code, "TRANSITION_GUARD_BLOCKED"
        )
        self.assertEqual(
            raised.exception.details["blockers"],
            [{"code": "NOT_CURRENT"}],
        )

    def test_catalog_registry_reference_objects_resolve_by_stable_id(
        self,
    ) -> None:
        reference = {
            "registry": "guards",
            "id": "guard.current/v1",
            "version": "v1",
        }
        workflow = self.make_engine(
            graph(edge(guards=(reference,))),
            guards={"guard.current/v1": passing_guard},
        )

        result = workflow.evaluate(
            state(),
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence={},
            preview=True,
        )

        self.assertEqual(
            result.guard_results[0][0], "guard.current/v1"
        )

    def test_registry_resolvers_receive_the_exact_declared_version(
        self,
    ) -> None:
        observed: list[tuple[str, str | None]] = []
        reference = {
            "registry": "guards",
            "id": "guard.current/v1",
            "version": "v9",
        }

        def resolve_guard(
            identifier: str, version: str | None
        ) -> object:
            observed.append((identifier, version))
            return passing_guard

        workflow = engine.TransitionEngine(
            graph(edge(guards=(reference,))),
            guard_resolver=resolve_guard,
            reducer_resolver=lambda identifier, version: {}[
                (identifier, version)
            ],
        )
        workflow.evaluate(
            state(),
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence={},
            preview=True,
        )

        self.assertEqual(
            observed, [("guard.current/v1", "v9")]
        )

    def test_catalog_canonical_edge_shape_is_selected_and_bound(
        self,
    ) -> None:
        canonical_edge = {
            "id": "full.intake.preflighted",
            "source": "INTAKE",
            "target": "PREFLIGHTED",
            "policy": "preflight-forward",
            "trigger": {"kind": "action", "id": "preflight"},
            "confirmation": "explicit",
            "priority": 10,
            "guards": [],
            "reducers": [],
            "handler": {
                "registry": "executors",
                "id": "executor.deterministic/v1",
                "version": "v1",
            },
            "gate": None,
            "side_effects": ["task-state"],
            "allowed_state_writes": ["/status"],
        }
        workflow = self.make_engine(graph(canonical_edge))

        preview = workflow.evaluate(
            state(),
            expected_revision=7,
            action_id="preflight",
            action_parameters={},
            evidence={},
            preview=True,
        )

        self.assertEqual(preview.source, "INTAKE")
        self.assertEqual(preview.target, "PREFLIGHTED")
        self.assertEqual(
            preview.intent["trigger"],
            {"kind": "action", "id": "preflight"},
        )
        self.assertEqual(
            preview.intent["handlers"]["handler"]["id"],
            "executor.deterministic/v1",
        )

    def test_reducer_runs_on_copy_and_may_change_only_declared_paths(
        self,
    ) -> None:
        fact = engine.AuditFact("note_appended", {"note": "bounded"})

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
            candidate["notes"] = ["bounded"]
            return engine.ReducerResult(candidate, (fact,))

        workflow = self.make_engine(
            graph(
                edge(
                    reducers=("reducer.note/v1",),
                    allowed=("/status", "/notes"),
                )
            ),
            reducers={"reducer.note/v1": reducer},
        )
        current = state()

        result = workflow.evaluate(
            current,
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence={},
            preview=True,
        )

        self.assertEqual(current["notes"], [])
        self.assertEqual(result.candidate_state["notes"], ("bounded",))
        self.assertEqual(
            result.changed_paths, ("/notes", "/status")
        )
        self.assertEqual(result.audit_facts, (fact,))

    def test_registered_reducer_kernel_delta_applies_invalidation_algebra(
        self,
    ) -> None:
        transition = edge(
            reducers=("reducer.invalidate/v1",),
            allowed=("/status",),
        )
        transition["kernel_invalidates"] = [
            "/approvals/plan",
            "/approvals/review",
            "/planning_generation",
            "/review_snapshots",
        ]

        def invalidate(
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
            return engine.ReducerResult(
                candidate,
                kernel_state_delta={
                    "set": {"/review_snapshots": []},
                    "remove": [
                        "/approvals/plan",
                        "/approvals/review",
                    ],
                    "operations": [
                        "increment-planning-generation"
                    ],
                },
            )

        current = state()
        current.update(
            {
                "planning_generation": 4,
                "review_snapshots": [{"sha256": "a" * 64}],
                "approvals": {
                    "plan": {"approval_id": "plan"},
                    "review": {"approval_id": "review"},
                },
            }
        )
        workflow = self.make_engine(
            graph(transition),
            reducers={"reducer.invalidate/v1": invalidate},
        )

        result = workflow.evaluate(
            current,
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence={},
            preview=True,
        )

        self.assertEqual(
            result.candidate_state["planning_generation"], 5
        )
        self.assertEqual(result.candidate_state["review_snapshots"], ())
        self.assertNotIn("plan", result.candidate_state["approvals"])
        self.assertNotIn("review", result.candidate_state["approvals"])

    def test_undeclared_or_protected_reducer_writes_fail_closed(self) -> None:
        def mutate_task_id(
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
            candidate["task_id"] = "other"
            return engine.ReducerResult(candidate)

        protected = self.make_engine(
            graph(
                edge(
                    reducers=("reducer.bad/v1",),
                    allowed=("/status", "/task_id"),
                )
            ),
            reducers={"reducer.bad/v1": mutate_task_id},
        )
        with self.assertRaises(engine.TransitionEngineError) as raised:
            protected.evaluate(
                state(),
                expected_revision=7,
                action_id="transition",
                action_parameters={},
                evidence={},
                preview=True,
            )
        self.assertEqual(
            raised.exception.code, "EDGE_PROTECTED_WRITE_GRANT"
        )

        undeclared = self.make_engine(
            graph(
                edge(
                    reducers=("reducer.bad/v1",),
                    allowed=("/status",),
                )
            ),
            reducers={"reducer.bad/v1": mutate_task_id},
        )
        with self.assertRaises(engine.TransitionEngineError) as raised:
            undeclared.evaluate(
                state(),
                expected_revision=7,
                action_id="transition",
                action_parameters={},
                evidence={},
                preview=True,
            )
        self.assertEqual(
            raised.exception.code, "REDUCER_WRITE_OUT_OF_SCOPE"
        )

    def test_reducer_cannot_set_status_directly(self) -> None:
        def direct_status(
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
            candidate["status"] = "READY"
            return engine.ReducerResult(candidate)

        workflow = self.make_engine(
            graph(edge(reducers=("reducer.bad/v1",))),
            reducers={"reducer.bad/v1": direct_status},
        )
        with self.assertRaises(engine.TransitionEngineError) as raised:
            workflow.evaluate(
                state(),
                expected_revision=7,
                action_id="transition",
                action_parameters={},
                evidence={},
                preview=True,
            )
        self.assertEqual(
            raised.exception.code, "REDUCER_STATUS_WRITE_FORBIDDEN"
        )

    def test_action_and_approval_outcomes_are_immutable_and_bound(self) -> None:
        action = engine.ActionOutcome(
            action_id="approve",
            proposed_edge_id="edge.approve/v1",
            evidence_records=({"artifact": "a" * 64},),
            proposed_state_delta={"/route": "direct"},
            audit_facts=(engine.AuditFact("action", {"ok": True}),),
        )
        approval = engine.ApprovalOutcome(
            gate_id="gate.route/v1",
            proposed_edge_id="edge.approve/v1",
            approval={"approval_id": "approval-1"},
        )

        with self.assertRaises(TypeError):
            action.proposed_state_delta["/route"] = "openspec"
        with self.assertRaises(TypeError):
            approval.approval["approval_id"] = "changed"

    def test_json_pointer_diff_escapes_keys_and_shadow_is_stable(self) -> None:
        self.assertEqual(
            engine.json_pointer_diff(
                {"a/b": {"~key": 1}},
                {"a/b": {"~key": 2}},
            ),
            ("/a~1b/~0key",),
        )
        first = engine.compare_shadow_outcomes(
            {"status": "READY", "revision": 8},
            {"status": "READY", "revision": 8},
        )
        second = engine.compare_shadow_outcomes(
            {"revision": 8, "status": "READY"},
            {"status": "READY", "revision": 8},
        )
        self.assertTrue(first["matched"])
        self.assertEqual(
            first["diagnostic_sha256"], second["diagnostic_sha256"]
        )
        mismatch = engine.compare_shadow_outcomes(
            {"status": "READY"},
            {"status": "BLOCKED"},
        )
        self.assertFalse(mismatch["matched"])
        self.assertEqual(mismatch["differences"], ["/status"])


if __name__ == "__main__":
    unittest.main()
