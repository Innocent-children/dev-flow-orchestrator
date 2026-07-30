from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ROOT / "workflows" / "bundles"
ENGINE_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "transition_engine.py"
)
ENGINE_SPEC = importlib.util.spec_from_file_location(
    "dev_flow_v3_approval_matrix_engine", ENGINE_PATH
)
assert ENGINE_SPEC is not None and ENGINE_SPEC.loader is not None
engine = importlib.util.module_from_spec(ENGINE_SPEC)
sys.modules[ENGINE_SPEC.name] = engine
ENGINE_SPEC.loader.exec_module(engine)

BUILTIN_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "workflow_builtin_handlers.py"
)
BUILTIN_SPEC = importlib.util.spec_from_file_location(
    "dev_flow_v3_approval_matrix_builtins", BUILTIN_PATH
)
assert BUILTIN_SPEC is not None and BUILTIN_SPEC.loader is not None
builtins = importlib.util.module_from_spec(BUILTIN_SPEC)
sys.modules[BUILTIN_SPEC.name] = builtins
BUILTIN_SPEC.loader.exec_module(builtins)

WORKFLOW_REF = {
    "id": "approval-matrix",
    "version": 3,
    "schema": "dev-flow-workflow/v1",
}


def _contract(registry: str, identifier: str) -> dict[str, str]:
    return {
        "registry": registry,
        "id": identifier,
        "version": "v1",
    }


def _read_bundle(name: str) -> dict[str, object]:
    value = json.loads(
        (BUNDLES / name / "workflow.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def _expanded_movements(bundle: dict[str, object]) -> list[dict[str, object]]:
    policies = {
        str(item["id"]): item
        for item in bundle["edge_policies"]
        if isinstance(item, dict)
    }
    result: list[dict[str, object]] = []
    for declared in bundle["edges"]:
        assert isinstance(declared, dict)
        expanded = copy.deepcopy(policies[str(declared["policy"])])
        expanded.update(copy.deepcopy(declared))
        result.append(expanded)
    for family in bundle["edge_families"]:
        assert isinstance(family, dict)
        for source in family["sources"]:
            for target in family["targets"]:
                expanded = copy.deepcopy(
                    policies[str(family["policy"])]
                )
                expanded.update(
                    {
                        "id": (
                            f"{family['id_prefix']}."
                            f"{str(source).lower()}."
                            f"{str(target).lower()}"
                        ),
                        "source": source,
                        "target": target,
                        "policy": family["policy"],
                    }
                )
                result.append(expanded)
    identifiers = [str(item["id"]) for item in result]
    if len(identifiers) != len(set(identifiers)):
        raise AssertionError("expanded movement identifiers are not unique")
    return result


def _node_actions(bundle: dict[str, object]) -> list[dict[str, object]]:
    return [
        copy.deepcopy(action)
        for node in bundle["nodes"]
        if isinstance(node, dict)
        for action in node.get("actions", ())
        if isinstance(action, dict)
    ]


def _reference_ids(
    item: dict[str, object], field: str
) -> tuple[str, ...]:
    values = item.get(field, ())
    assert isinstance(values, list)
    return tuple(
        str(reference["id"])
        for reference in values
        if isinstance(reference, dict)
    )


def _engine_state(
    *,
    source: str,
    blocked_from: str | None = None,
    flow: str = "full",
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "task_id": "approval-matrix-task",
        "revision": 7,
        "status": source,
        "flow": flow,
        "workflow_ref": dict(WORKFLOW_REF),
        "approvals": {},
        "marker": "unchanged",
        "blocked": (
            {
                "phase": "manual",
                "from_status": blocked_from,
                "reason": "matrix",
                "details": [],
            }
            if blocked_from is not None
            else None
        ),
    }


def _engine_graph(*edges: dict[str, object]) -> dict[str, object]:
    node_ids = sorted(
        {
            str(item[field])
            for item in edges
            for field in ("source", "target")
        }
    )
    return {
        "schema": "dev-flow-workflow/v1",
        "workflow_id": WORKFLOW_REF["id"],
        "workflow_version": WORKFLOW_REF["version"],
        "nodes": [
            {"id": node_id, "kind": "state"} for node_id in node_ids
        ],
        "edges": list(edges),
    }


def _kernel_context(
    evidence: dict[str, object],
    edge: dict[str, object],
    *,
    approval_current: bool = False,
    approval_intent_id: str | None = None,
) -> object:
    supported: dict[str, tuple[str, ...]] = {}
    for field, registry in (
        ("guards", "guards"),
        ("reducers", "reducers"),
    ):
        values = edge.get(field, ())
        assert isinstance(values, list)
        for reference in values:
            assert isinstance(reference, dict)
            supported[
                f"{registry}:{reference['id']}"
            ] = (str(reference["version"]),)
    for field, registry in (
        ("gate", "gates"),
        ("handler", "executors"),
    ):
        reference = edge.get(field)
        if isinstance(reference, dict):
            supported[
                f"{registry}:{reference['id']}"
            ] = (str(reference["version"]),)
    return engine.KernelTransitionContext(
        task_id="approval-matrix-task",
        workflow_ref=WORKFLOW_REF,
        task_lock_held=True,
        workspace_lock_held=True,
        ownership_lock_held=True,
        evidence_sha256=engine._sha256_contract(evidence),
        evidence_authentic=True,
        evidence_current=True,
        approval_current=approval_current,
        approval_intent_id=approval_intent_id,
        supported_node_contracts={"state": ("v1",)},
        supported_contract_versions=supported,
        authorized_effects=tuple(edge.get("side_effects", ())),
    )


def _thawed_state(projected: object) -> dict[str, object]:
    value = engine._thaw_contract_value(projected)
    assert isinstance(value, dict)
    return value


class V3ApprovalOutcomeMatrixTests(unittest.TestCase):
    def test_full_and_lite_expand_to_the_exact_109_edge_matrix(
        self,
    ) -> None:
        expected = {
            "full-v3": {
                "movement_count": 79,
                "action_count": 27,
                "movement_confirmation": {
                    "action-explicit": 4,
                    "automatic": 4,
                    "explicit": 67,
                    "preflight-preview": 4,
                },
                "action_confirmation": {
                    "action-explicit": 25,
                    "preflight-preview": 2,
                },
                "movement_gates": 6,
                "action_gates": 11,
                "note_edges": 49,
                "resume_edges": 13,
                "movement_invalidations": 20,
                "action_invalidations": 4,
            },
            "lite-v3": {
                "movement_count": 30,
                "action_count": 5,
                "movement_confirmation": {
                    "automatic": 1,
                    "explicit": 23,
                    "preflight-preview": 4,
                    "safety-block": 2,
                },
                "action_confirmation": {
                    "action-explicit": 3,
                    "preflight-preview": 2,
                },
                "movement_gates": 2,
                "action_gates": 1,
                "note_edges": 16,
                "resume_edges": 5,
                "movement_invalidations": 5,
                "action_invalidations": 0,
            },
        }
        total_movements = 0
        for bundle_name, matrix in expected.items():
            with self.subTest(bundle=bundle_name):
                bundle = _read_bundle(bundle_name)
                movements = _expanded_movements(bundle)
                actions = _node_actions(bundle)
                total_movements += len(movements)
                self.assertEqual(
                    len(movements), matrix["movement_count"]
                )
                self.assertEqual(len(actions), matrix["action_count"])
                self.assertEqual(
                    dict(
                        sorted(
                            Counter(
                                str(item.get("confirmation"))
                                for item in movements
                            ).items()
                        )
                    ),
                    matrix["movement_confirmation"],
                )
                self.assertEqual(
                    dict(
                        sorted(
                            Counter(
                                str(item.get("confirmation"))
                                for item in actions
                            ).items()
                        )
                    ),
                    matrix["action_confirmation"],
                )
                self.assertEqual(
                    sum(item.get("gate") is not None for item in movements),
                    matrix["movement_gates"],
                )
                self.assertEqual(
                    sum(item.get("gate") is not None for item in actions),
                    matrix["action_gates"],
                )
                self.assertEqual(
                    sum(
                        item.get("requires_note") is True
                        for item in movements
                    ),
                    matrix["note_edges"],
                )
                self.assertEqual(
                    sum(
                        item.get("class") == "resume"
                        for item in movements
                    ),
                    matrix["resume_edges"],
                )
                self.assertEqual(
                    sum(
                        bool(item.get("kernel_invalidates"))
                        for item in movements
                    ),
                    matrix["movement_invalidations"],
                )
                self.assertEqual(
                    sum(
                        bool(item.get("kernel_invalidates"))
                        for item in actions
                    ),
                    matrix["action_invalidations"],
                )
        self.assertEqual(total_movements, 109)

    def test_every_declared_gate_note_resume_and_invalidation_is_pinned(
        self,
    ) -> None:
        for bundle_name in ("full-v3", "lite-v3"):
            bundle = _read_bundle(bundle_name)
            movements = _expanded_movements(bundle)
            actions = _node_actions(bundle)
            for item in (*movements, *actions):
                with self.subTest(bundle=bundle_name, item=item["id"]):
                    gate = item.get("gate")
                    if gate is not None:
                        self.assertIsInstance(gate, dict)
                        assert isinstance(gate, dict)
                        self.assertEqual(gate.get("registry"), "gates")
                        self.assertEqual(gate.get("version"), "v1")
                        self.assertTrue(
                            str(gate.get("id")).endswith("-outcome/v1")
                        )
                    if item.get("requires_note") is True:
                        self.assertIn(
                            "guard.note-required/v1",
                            _reference_ids(item, "guards"),
                        )
                    if item.get("class") == "resume":
                        self.assertIn(
                            "guard.blocked-resume/v1",
                            _reference_ids(item, "guards"),
                        )
                        self.assertIn(
                            "reducer.resume/v1",
                            _reference_ids(item, "reducers"),
                        )
                    if item.get("kernel_invalidates"):
                        reducers = _reference_ids(item, "reducers")
                        self.assertTrue(reducers)
                        paths = tuple(item["kernel_invalidates"])
                        if "/impact_generation" in paths:
                            self.assertIn(
                                "reducer.v3-impact-reassess/v1",
                                reducers,
                            )
                        elif "/planning_generation" in paths:
                            self.assertIn(
                                "reducer.v3-invalidate-plan/v1",
                                reducers,
                            )
                        elif paths == (
                            "/approvals/review",
                            "/review_snapshots",
                        ):
                            self.assertIn(
                                "reducer.v3-invalidate-review/v1",
                                reducers,
                            )
                        else:
                            self.assertIn(
                                "reducer.action-outcome/v1", reducers
                            )
            if bundle_name == "lite-v3":
                generic_resumes = [
                    item
                    for item in movements
                    if item.get("class") == "resume"
                    and (
                        isinstance(item.get("trigger"), dict)
                        and item["trigger"].get("id") == "transition"
                    )
                ]
                self.assertEqual(len(generic_resumes), 4)
                for item in generic_resumes:
                    self.assertIn(
                        "guard.lite-risk-safe/v1",
                        _reference_ids(item, "guards"),
                    )

    def _evaluate_note_edge(
        self,
        declared: dict[str, object],
        note: object,
    ) -> tuple[list[str], list[str]]:
        edge = copy.deepcopy(declared)
        edge["side_effects"] = ["task-state"]
        reducer_calls: list[str] = []
        effect_calls: list[str] = []

        def resolve_guard(
            identifier: str, _version: str | None
        ) -> object:
            def evaluate(
                _state: object,
                _evidence: object,
                _capability: object,
            ) -> object:
                if identifier == "guard.note-required/v1":
                    passed = builtins._guard_note_required(
                        {"requires_note": True, "note": note}, None
                    )
                else:
                    passed = True
                return engine.GuardResult(
                    passed,
                    {"guard_id": identifier},
                    (
                        ()
                        if passed
                        else ({"code": "NOTE_REQUIRED"},)
                    ),
                )

            return evaluate

        def resolve_reducer(
            identifier: str, _version: str | None
        ) -> object:
            def apply(
                projected: object,
                _edge: object,
                _action: object,
                _approval: object,
                _capability: object,
            ) -> object:
                reducer_calls.append(identifier)
                return engine.ReducerResult(
                    _thawed_state(projected)
                )

            return apply

        def apply_effect(
            candidate: object,
            _edge: object,
            _action: object,
            _approval: object,
            _parameters: object,
        ) -> object:
            effect_calls.append(str(edge["id"]))
            return engine.KernelEffectResult(
                _thawed_state(candidate)
            )

        state = _engine_state(source=str(edge["source"]))
        before = copy.deepcopy(state)
        evidence: dict[str, object] = {}
        workflow = engine.TransitionEngine(
            _engine_graph(edge),
            guard_resolver=resolve_guard,
            reducer_resolver=resolve_reducer,
            kernel_effect_applier=apply_effect,
        )
        with self.assertRaises(
            engine.TransitionEngineError
        ) as raised:
            workflow.evaluate(
                state,
                expected_revision=7,
                action_id=str(edge["trigger"]["id"]),
                action_parameters=(
                    {} if note is None else {"note": note}
                ),
                evidence=evidence,
                edge_id=str(edge["id"]),
                preview=True,
                kernel_context=_kernel_context(
                    evidence, edge
                ),
            )
        self.assertEqual(
            raised.exception.code, "TRANSITION_GUARD_BLOCKED"
        )
        self.assertEqual(state, before)
        return reducer_calls, effect_calls

    def test_all_65_note_edges_reject_missing_empty_and_whitespace_first(
        self,
    ) -> None:
        note_edges = [
            item
            for bundle_name in ("full-v3", "lite-v3")
            for item in _expanded_movements(_read_bundle(bundle_name))
            if item.get("requires_note") is True
        ]
        self.assertEqual(len(note_edges), 65)
        for edge in note_edges:
            for label, note in (
                ("missing", None),
                ("empty", ""),
                ("spaces", "   "),
                ("whitespace", "\t\r\n"),
            ):
                with self.subTest(edge=edge["id"], note=label):
                    reducer_calls, effect_calls = (
                        self._evaluate_note_edge(edge, note)
                    )
                    self.assertEqual(reducer_calls, [])
                    self.assertEqual(effect_calls, [])

    def _approval_edge(
        self,
        *,
        identifier: str = "approval.edge",
        gate_id: str | None = "gate.route-outcome/v1",
    ) -> dict[str, object]:
        return {
            "id": identifier,
            "source": "INTAKE",
            "target": "READY",
            "class": "forward",
            "trigger": {"kind": "transition", "id": "transition"},
            "handler": _contract(
                "executors", "executor.deterministic/v1"
            ),
            "guards": [],
            "reducers": [
                _contract("reducers", "reducer.probe/v1")
            ],
            "gate": (
                _contract("gates", gate_id)
                if gate_id is not None
                else None
            ),
            "confirmation": "explicit",
            "automatic": False,
            "requires_note": False,
            "kernel_effects": [],
            "side_effects": ["task-state"],
            "allowed_state_writes": ["/status", "/marker"],
            "kernel_invalidates": [],
            "priority": 10,
        }

    def _approval_engine(
        self,
        *edges: dict[str, object],
        calls: list[str],
    ) -> object:
        def reducer(
            projected: object,
            _edge: object,
            _action: object,
            _approval: object,
            _capability: object,
        ) -> object:
            calls.append("reducer")
            candidate = _thawed_state(projected)
            candidate["marker"] = "reduced"
            return engine.ReducerResult(candidate)

        return engine.TransitionEngine(
            _engine_graph(*edges),
            guard_resolver=lambda _identifier, _version: None,
            reducer_resolver=lambda _identifier, _version: reducer,
        )

    def test_gated_engine_requires_exact_typed_approval_before_reducer(
        self,
    ) -> None:
        edge = self._approval_edge()
        state = _engine_state(source="INTAKE")
        before = copy.deepcopy(state)
        evidence: dict[str, object] = {}
        calls: list[str] = []
        workflow = self._approval_engine(edge, calls=calls)

        failures = (
            (
                "missing",
                None,
                "APPROVAL_OUTCOME_REQUIRED",
            ),
            (
                "untyped",
                {
                    "gate_id": "gate.route-outcome/v1",
                    "proposed_edge_id": str(edge["id"]),
                    "approval": {"approval_id": "approval-1"},
                },
                "APPROVAL_OUTCOME_INVALID",
            ),
            (
                "wrong-gate",
                engine.ApprovalOutcome(
                    "gate.review-outcome/v1",
                    str(edge["id"]),
                    {"approval_id": "approval-1"},
                ),
                "APPROVAL_OUTCOME_MISMATCH",
            ),
        )
        for label, outcome, code in failures:
            with self.subTest(case=label):
                calls.clear()
                with self.assertRaises(
                    engine.TransitionEngineError
                ) as raised:
                    workflow.evaluate(
                        state,
                        expected_revision=7,
                        action_id="transition",
                        action_parameters={},
                        evidence=evidence,
                        edge_id=str(edge["id"]),
                        approval_outcome=outcome,
                        preview=True,
                        kernel_context=_kernel_context(
                            evidence, edge
                        ),
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(calls, [])
                self.assertEqual(state, before)

        ungated = self._approval_edge(
            identifier="approval.ungated", gate_id=None
        )
        ungated_workflow = self._approval_engine(
            ungated, calls=calls
        )
        calls.clear()
        with self.assertRaises(
            engine.TransitionEngineError
        ) as raised:
            ungated_workflow.evaluate(
                state,
                expected_revision=7,
                action_id="transition",
                action_parameters={},
                evidence=evidence,
                edge_id=str(ungated["id"]),
                approval_outcome=engine.ApprovalOutcome(
                    "gate.route-outcome/v1",
                    str(ungated["id"]),
                    {"approval_id": "approval-1"},
                ),
                preview=True,
                kernel_context=_kernel_context(
                    evidence, ungated
                ),
            )
        self.assertEqual(
            raised.exception.code, "APPROVAL_OUTCOME_MISMATCH"
        )
        self.assertEqual(calls, [])
        self.assertEqual(state, before)

    def test_gate_currentness_confirmation_cross_edge_and_replay_are_exact(
        self,
    ) -> None:
        edge = self._approval_edge()
        other = self._approval_edge(
            identifier="approval.other",
            gate_id="gate.review-outcome/v1",
        )
        state = _engine_state(source="INTAKE")
        before = copy.deepcopy(state)
        evidence: dict[str, object] = {}
        calls: list[str] = []
        workflow = self._approval_engine(edge, other, calls=calls)
        seed = engine.ApprovalOutcome(
            "gate.route-outcome/v1",
            str(edge["id"]),
            {"approval_id": "approval-1"},
        )
        preview = workflow.evaluate(
            state,
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence=evidence,
            edge_id=str(edge["id"]),
            approval_outcome=seed,
            preview=True,
            kernel_context=_kernel_context(evidence, edge),
        )
        intent_id = str(preview.intent["intent_id"])

        def assert_apply_rejected(
            code: str,
            *,
            outcome: object,
            context: object,
            confirm_intent: str = intent_id,
            edge_id: str = str(edge["id"]),
        ) -> None:
            calls.clear()
            with self.assertRaises(
                engine.TransitionEngineError
            ) as raised:
                workflow.evaluate(
                    state,
                    expected_revision=7,
                    action_id="transition",
                    action_parameters={},
                    evidence=evidence,
                    edge_id=edge_id,
                    approval_outcome=outcome,
                    confirm_intent=confirm_intent,
                    preview=False,
                    kernel_context=context,
                )
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(calls, [])
            self.assertEqual(state, before)

        current = _kernel_context(
            evidence,
            edge,
            approval_current=True,
            approval_intent_id=intent_id,
        )
        exact = engine.ApprovalOutcome(
            "gate.route-outcome/v1",
            str(edge["id"]),
            {
                "approval_id": "approval-1",
                "intent_id": intent_id,
            },
        )
        assert_apply_rejected(
            "KERNEL_APPROVAL_STALE",
            outcome=exact,
            context=_kernel_context(
                evidence,
                edge,
                approval_current=False,
                approval_intent_id=intent_id,
            ),
        )
        assert_apply_rejected(
            "KERNEL_APPROVAL_INTENT_MISMATCH",
            outcome=engine.ApprovalOutcome(
                "gate.route-outcome/v1",
                str(edge["id"]),
                {
                    "approval_id": "approval-1",
                    "intent_id": "wrong-intent",
                },
            ),
            context=current,
        )
        assert_apply_rejected(
            "INTENT_STALE",
            outcome=exact,
            context=current,
            confirm_intent="wrong-confirmation",
        )
        assert_apply_rejected(
            "APPROVAL_OUTCOME_MISMATCH",
            outcome=engine.ApprovalOutcome(
                "gate.review-outcome/v1",
                str(other["id"]),
                {
                    "approval_id": "approval-2",
                    "intent_id": intent_id,
                },
            ),
            context=current,
            edge_id=str(edge["id"]),
        )

        calls.clear()
        evaluation = workflow.evaluate(
            state,
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence=evidence,
            edge_id=str(edge["id"]),
            approval_outcome=exact,
            confirm_intent=intent_id,
            preview=False,
            kernel_context=current,
        )
        self.assertEqual(calls, ["reducer"])
        self.assertEqual(evaluation.target, "READY")
        self.assertEqual(evaluation.candidate_state["marker"], "reduced")
        engine._transition_engine_consume_evaluation_issuance(
            evaluation
        )
        with self.assertRaises(
            engine.TransitionEngineError
        ) as replayed:
            engine._transition_engine_consume_evaluation_issuance(
                evaluation
            )
        self.assertEqual(
            replayed.exception.code,
            "V3_ENGINE_EVALUATION_UNREGISTERED",
        )
        self.assertEqual(state, before)

    def _resume_edge(
        self,
        *,
        identifier: str,
        target: str,
        action_id: str = "transition",
        lite: bool = False,
    ) -> dict[str, object]:
        guards = [
            _contract("guards", "guard.blocked-resume/v1")
        ]
        if lite:
            guards.append(
                _contract("guards", "guard.lite-risk-safe/v1")
            )
        return {
            "id": identifier,
            "source": "BLOCKED",
            "target": target,
            "class": "resume",
            "trigger": {"kind": "transition", "id": action_id},
            "handler": _contract(
                "executors", "executor.deterministic/v1"
            ),
            "guards": guards,
            "reducers": [
                _contract("reducers", "reducer.resume/v1")
            ],
            "gate": None,
            "confirmation": "explicit",
            "automatic": False,
            "requires_note": False,
            "kernel_effects": [],
            "side_effects": ["task-state"],
            "allowed_state_writes": ["/status", "/blocked"],
            "kernel_invalidates": [],
            "priority": 40,
        }

    def _resume_engine(
        self,
        edge: dict[str, object],
        state: dict[str, object],
        *,
        lite_safe: bool = True,
    ) -> object:
        def resolve_guard(
            identifier: str, _version: str | None
        ) -> object:
            def evaluate(
                _state: object,
                _evidence: object,
                _capability: object,
            ) -> object:
                if identifier == "guard.blocked-resume/v1":
                    passed = builtins._guard_blocked_resume_target(
                        {
                            "blocked": state.get("blocked"),
                            "target_status": edge.get("target"),
                        },
                        None,
                    )
                    blocker = "INVALID_TRANSITION"
                elif identifier == "guard.lite-risk-safe/v1":
                    passed = lite_safe
                    blocker = "LITE_REPLACEMENT_REQUIRED"
                else:
                    passed = True
                    blocker = "CURRENT_EVIDENCE_REQUIRED"
                return engine.GuardResult(
                    passed,
                    {"guard_id": identifier},
                    (() if passed else ({"code": blocker},)),
                )

            return evaluate

        def reducer(
            projected: object,
            _edge: object,
            _action: object,
            _approval: object,
            _capability: object,
        ) -> object:
            candidate = _thawed_state(projected)
            candidate["blocked"] = None
            return engine.ReducerResult(candidate)

        return engine.TransitionEngine(
            _engine_graph(edge),
            guard_resolver=resolve_guard,
            reducer_resolver=lambda _identifier, _version: reducer,
        )

    def test_all_18_resume_edges_bind_the_recorded_target(self) -> None:
        resume_edges = [
            item
            for bundle_name in ("full-v3", "lite-v3")
            for item in _expanded_movements(_read_bundle(bundle_name))
            if item.get("class") == "resume"
        ]
        self.assertEqual(len(resume_edges), 18)
        for edge in resume_edges:
            with self.subTest(edge=edge["id"]):
                target = str(edge["target"])
                self.assertTrue(
                    builtins._guard_blocked_resume_target(
                        {
                            "blocked": {"from_status": target},
                            "target_status": target,
                        },
                        None,
                    )
                )
                self.assertFalse(
                    builtins._guard_blocked_resume_target(
                        {
                            "blocked": {"from_status": "WRONG"},
                            "target_status": target,
                        },
                        None,
                    )
                )
                self.assertFalse(
                    builtins._guard_blocked_resume_target(
                        {"blocked": None, "target_status": target},
                        None,
                    )
                )

    def test_resume_guard_binds_generic_and_preflight_targets_exactly(
        self,
    ) -> None:
        cases = (
            self._resume_edge(
                identifier="resume.generic.wrong",
                target="INTAKE",
            ),
            self._resume_edge(
                identifier="resume.preflight.wrong",
                target="PREFLIGHTED",
                action_id="preflight",
            ),
        )
        blocked_from = ("PREFLIGHTED", "INTAKE")
        for edge, recorded in zip(cases, blocked_from):
            with self.subTest(edge=edge["id"]):
                state = _engine_state(
                    source="BLOCKED", blocked_from=recorded
                )
                before = copy.deepcopy(state)
                workflow = self._resume_engine(
                    edge,
                    state,
                )
                with self.assertRaises(
                    engine.TransitionEngineError
                ) as raised:
                    workflow.evaluate(
                        state,
                        expected_revision=7,
                        action_id=str(edge["trigger"]["id"]),
                        action_parameters={},
                        evidence={},
                        edge_id=str(edge["id"]),
                        preview=True,
                        kernel_context=_kernel_context({}, edge),
                    )
                self.assertEqual(
                    raised.exception.code, "TRANSITION_GUARD_BLOCKED"
                )
                self.assertEqual(
                    raised.exception.details["blockers"][0]["code"],
                    "INVALID_TRANSITION",
                )
                self.assertEqual(state, before)

        exact_edge = self._resume_edge(
            identifier="resume.generic.exact",
            target="INTAKE",
        )
        exact_state = _engine_state(
            source="BLOCKED", blocked_from="INTAKE"
        )
        exact_workflow = self._resume_engine(
            exact_edge,
            exact_state,
        )
        preview = exact_workflow.evaluate(
            exact_state,
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence={},
            edge_id=str(exact_edge["id"]),
            preview=True,
            kernel_context=_kernel_context({}, exact_edge),
        )
        evaluation = exact_workflow.evaluate(
            exact_state,
            expected_revision=7,
            action_id="transition",
            action_parameters={},
            evidence={},
            edge_id=str(exact_edge["id"]),
            confirm_intent=str(preview.intent["intent_id"]),
            preview=False,
            kernel_context=_kernel_context({}, exact_edge),
        )
        self.assertEqual(evaluation.target, "INTAKE")
        self.assertEqual(evaluation.candidate_state["status"], "INTAKE")
        self.assertIsNone(evaluation.candidate_state["blocked"])
        engine._transition_engine_consume_evaluation_issuance(
            evaluation
        )

    def test_unresolved_lite_risk_blocks_cannot_use_generic_resume(
        self,
    ) -> None:
        edge = self._resume_edge(
            identifier="resume.lite.risk",
            target="IMPLEMENTING",
            lite=True,
        )
        state = _engine_state(
            source="BLOCKED",
            blocked_from="IMPLEMENTING",
            flow="lite",
        )
        assert isinstance(state["blocked"], dict)
        state["blocked"]["phase"] = "lite-risk"
        before = copy.deepcopy(state)

        workflow = self._resume_engine(
            edge,
            state,
            lite_safe=False,
        )
        with self.assertRaises(
            engine.TransitionEngineError
        ) as raised:
            workflow.evaluate(
                state,
                expected_revision=7,
                action_id="transition",
                action_parameters={},
                evidence={},
                edge_id=str(edge["id"]),
                preview=True,
                kernel_context=_kernel_context({}, edge),
            )
        self.assertEqual(
            raised.exception.code, "TRANSITION_GUARD_BLOCKED"
        )
        self.assertEqual(state, before)

    def test_service_wires_resume_guard_and_fail_closes_legacy_gate_candidate(
        self,
    ) -> None:
        source = (
            ROOT
            / "scripts"
            / "dev_flow_parts"
            / "workflow_transition_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "if not _guard_blocked_resume_target(", source
        )
        start = source.index("def evaluate_v3_gate_approval_candidate(")
        end = source.index(
            "\ndef workflow_transition_audit_events(", start
        )
        candidate_adapter = source[start:end]
        schema_rejection = candidate_adapter.index(
            '"V3_TRANSITION_SERVICE_REQUIRED"'
        )
        legacy_rejection = candidate_adapter.index(
            '"V3_LEGACY_GATE_CANDIDATE_FORBIDDEN"'
        )
        self.assertLess(schema_rejection, legacy_rejection)
        self.assertNotIn("pseudo_edge = {", candidate_adapter)
        self.assertGreaterEqual(
            source.count('"V3_LEGACY_GATE_CANDIDATE_FORBIDDEN"'),
            2,
        )


if __name__ == "__main__":
    unittest.main()
