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
    "dev_flow_transition_kernel_invariants", ENGINE_PATH
)
assert SPEC is not None and SPEC.loader is not None
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


WORKFLOW_REF = {
    "id": "full",
    "version": 3,
    "schema": "dev-flow-workflow/v1",
    "graph_sha256": "a" * 64,
    "bundle_sha256": "b" * 64,
}


def contract(registry: str, identifier: str) -> dict:
    return {
        "registry": registry,
        "id": identifier,
        "version": "v1",
    }


def canonical_graph(
    *,
    side_effects: tuple[str, ...] = ("task-state",),
    gate: dict | None = None,
    target_kind: str = "state",
) -> dict:
    edge = {
        "id": "full.intake.ready",
        "source": "INTAKE",
        "target": "READY",
        "policy": "forward",
        "trigger": {"kind": "action", "id": "transition"},
        "confirmation": "explicit",
        "priority": 10,
        "guards": [contract("guards", "guard.current/v1")],
        "reducers": [contract("reducers", "reducer.status/v1")],
        "handler": contract(
            "executors", "executor.deterministic/v1"
        ),
        "gate": gate,
        "side_effects": list(side_effects),
        "allowed_state_writes": ["/status"],
    }
    return {
        "schema": "dev-flow-workflow/v1",
        "workflow_id": "full",
        "workflow_version": 3,
        "nodes": [
            {"id": "INTAKE", "kind": "state"},
            {"id": "READY", "kind": target_kind},
        ],
        "edges": [edge],
    }


def task_state() -> dict:
    return {
        "schema_version": 3,
        "task_id": "task-v3",
        "revision": 4,
        "status": "INTAKE",
        "flow": "full",
        "workflow_ref": dict(WORKFLOW_REF),
        "approvals": {},
    }


def passing_guard(
    _state: object, _evidence: object, _capability: object
) -> object:
    return engine.GuardResult(True, {"current": True})


def status_reducer(
    projected: object,
    _edge: object,
    _action: object,
    _approval: object,
    _capability: object,
) -> object:
    return engine.ReducerResult(
        {
            key: engine._thaw_contract_value(value)
            for key, value in projected.items()
        }
    )


class TransitionKernelInvariantTests(unittest.TestCase):
    def make_engine(
        self,
        graph_value: dict,
        *,
        missing_guard: bool = False,
    ) -> object:
        guards = (
            {}
            if missing_guard
            else {"guard.current/v1": passing_guard}
        )
        return engine.TransitionEngine(
            graph_value,
            guard_resolver=lambda identifier, _version: guards[identifier],
            reducer_resolver=lambda identifier, _version: {
                "reducer.status/v1": status_reducer
            }[identifier],
        )

    def context(
        self,
        evidence: dict,
        *,
        graph_value: dict | None = None,
        **overrides: object,
    ) -> object:
        graph_value = graph_value or canonical_graph()
        supported_contracts = {
            "guards:guard.current/v1": ("v1",),
            "reducers:reducer.status/v1": ("v1",),
            "executors:executor.deterministic/v1": ("v1",),
        }
        gate = graph_value["edges"][0].get("gate")
        if gate is not None:
            supported_contracts[
                f"gates:{gate['id']}"
            ] = ("v1",)
        values = {
            "task_id": "task-v3",
            "workflow_ref": WORKFLOW_REF,
            "task_lock_held": True,
            "workspace_lock_held": False,
            "ownership_lock_held": False,
            "evidence_sha256": engine._sha256_contract(evidence),
            "evidence_authentic": True,
            "evidence_current": True,
            "supported_node_contracts": {"state": ("v1",)},
            "supported_contract_versions": supported_contracts,
            "authorized_effects": tuple(
                graph_value["edges"][0]["side_effects"]
            ),
        }
        values.update(overrides)
        return engine.KernelTransitionContext(**values)

    def evaluate(
        self,
        workflow: object,
        evidence: dict,
        context: object | None,
        **overrides: object,
    ) -> object:
        values = {
            "expected_revision": 4,
            "action_id": "transition",
            "action_parameters": {},
            "evidence": evidence,
            "preview": True,
            "kernel_context": context,
        }
        values.update(overrides)
        return workflow.evaluate(task_state(), **values)

    def assert_blocked(
        self,
        code: str,
        callback: object,
    ) -> object:
        with self.assertRaises(engine.TransitionEngineError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_v3_requires_immutable_kernel_context_and_task_lock(
        self,
    ) -> None:
        evidence = {"fingerprint": "c" * 64}
        workflow = self.make_engine(canonical_graph())
        self.assert_blocked(
            "KERNEL_CONTEXT_REQUIRED",
            lambda: self.evaluate(workflow, evidence, None),
        )
        context = self.context(evidence, task_lock_held=False)
        self.assert_blocked(
            "KERNEL_TASK_LOCK_REQUIRED",
            lambda: self.evaluate(workflow, evidence, context),
        )
        with self.assertRaises(TypeError):
            context.workflow_ref["id"] = "lite"

    def test_task_workflow_and_evidence_proofs_are_exact(self) -> None:
        evidence = {"fingerprint": "c" * 64}
        workflow = self.make_engine(canonical_graph())
        wrong_task = self.context(evidence, task_id="another")
        self.assert_blocked(
            "KERNEL_TASK_IDENTITY_MISMATCH",
            lambda: self.evaluate(workflow, evidence, wrong_task),
        )
        wrong_ref = self.context(
            evidence,
            workflow_ref={**WORKFLOW_REF, "bundle_sha256": "d" * 64},
        )
        self.assert_blocked(
            "KERNEL_WORKFLOW_IDENTITY_MISMATCH",
            lambda: self.evaluate(workflow, evidence, wrong_ref),
        )
        stale = self.context(evidence, evidence_current=False)
        self.assert_blocked(
            "KERNEL_EVIDENCE_STALE",
            lambda: self.evaluate(workflow, evidence, stale),
        )
        unauthentic = self.context(
            evidence, evidence_authentic=False
        )
        self.assert_blocked(
            "KERNEL_EVIDENCE_AUTHENTICITY_REQUIRED",
            lambda: self.evaluate(workflow, evidence, unauthentic),
        )
        wrong_digest = self.context(
            evidence, evidence_sha256="e" * 64
        )
        self.assert_blocked(
            "KERNEL_EVIDENCE_IDENTITY_MISMATCH",
            lambda: self.evaluate(workflow, evidence, wrong_digest),
        )

    def test_unknown_nodes_and_contract_versions_are_compatibility_blockers(
        self,
    ) -> None:
        evidence: dict = {}
        unsupported_graph = canonical_graph(target_kind="worker-v2")
        workflow = self.make_engine(unsupported_graph)
        unsupported_node = self.context(
            evidence, graph_value=unsupported_graph
        )
        error = self.assert_blocked(
            "WORKFLOW_NODE_CONTRACT_UNSUPPORTED",
            lambda: self.evaluate(
                workflow, evidence, unsupported_node
            ),
        )
        self.assertTrue(error.details["compatibility_blocker"])

        unsupported_contract = self.context(
            evidence,
            supported_contract_versions={
                "reducers:reducer.status/v1": ("v1",),
                "executors:executor.deterministic/v1": ("v1",),
            },
        )
        error = self.assert_blocked(
            "WORKFLOW_CONTRACT_UNSUPPORTED",
            lambda: self.evaluate(
                self.make_engine(canonical_graph()),
                evidence,
                unsupported_contract,
            ),
        )
        self.assertTrue(error.details["compatibility_blocker"])

    def test_missing_resolver_contract_is_stable_compatibility_blocker(
        self,
    ) -> None:
        evidence: dict = {}
        workflow = self.make_engine(
            canonical_graph(), missing_guard=True
        )
        context = self.context(evidence)
        error = self.assert_blocked(
            "WORKFLOW_CONTRACT_UNAVAILABLE",
            lambda: self.evaluate(workflow, evidence, context),
        )
        self.assertEqual(error.details["registry"], "guards")
        self.assertTrue(error.details["compatibility_blocker"])

    def test_git_effect_requires_both_locks_authority_and_path_scope(
        self,
    ) -> None:
        graph_value = canonical_graph(
            side_effects=("task-state", "git-worktree")
        )
        workflow = self.make_engine(graph_value)
        evidence: dict = {}
        no_workspace_lock = self.context(
            evidence,
            graph_value=graph_value,
            requested_effect_paths=("/work/repo",),
            authorized_paths=("/work/repo",),
        )
        self.assert_blocked(
            "KERNEL_WORKSPACE_LOCK_REQUIRED",
            lambda: self.evaluate(
                workflow, evidence, no_workspace_lock
            ),
        )
        no_ownership_lock = self.context(
            evidence,
            graph_value=graph_value,
            workspace_lock_held=True,
            requested_effect_paths=("/work/repo",),
            authorized_paths=("/work/repo",),
        )
        self.assert_blocked(
            "KERNEL_OWNERSHIP_LOCK_REQUIRED",
            lambda: self.evaluate(
                workflow, evidence, no_ownership_lock
            ),
        )
        out_of_scope = self.context(
            evidence,
            graph_value=graph_value,
            workspace_lock_held=True,
            ownership_lock_held=True,
            requested_effect_paths=("/other/repo",),
            authorized_paths=("/work/repo",),
        )
        self.assert_blocked(
            "KERNEL_EFFECT_PATH_UNAUTHORIZED",
            lambda: self.evaluate(workflow, evidence, out_of_scope),
        )
        allowed = self.context(
            evidence,
            graph_value=graph_value,
            workspace_lock_held=True,
            ownership_lock_held=True,
            requested_effect_paths=("/work/repo/src",),
            authorized_paths=("/work/repo",),
        )
        result = self.evaluate(workflow, evidence, allowed)
        self.assertEqual(result.target, "READY")

    def test_gate_approval_must_be_current_and_intent_bound(
        self,
    ) -> None:
        graph_value = canonical_graph(
            gate=contract("gates", "gate.route/v1")
        )
        workflow = self.make_engine(graph_value)
        evidence: dict = {}
        provisional = engine.ApprovalOutcome(
            "gate.route/v1",
            "full.intake.ready",
            {"intent_id": "pending"},
        )
        preview_context = self.context(
            evidence, graph_value=graph_value
        )
        preview = self.evaluate(
            workflow,
            evidence,
            preview_context,
            approval_outcome=provisional,
        )
        stale_context = self.context(
            evidence,
            graph_value=graph_value,
            approval_current=False,
            approval_intent_id=preview.intent["intent_id"],
        )
        self.assert_blocked(
            "KERNEL_APPROVAL_STALE",
            lambda: self.evaluate(
                workflow,
                evidence,
                stale_context,
                preview=False,
                confirm_intent=preview.intent["intent_id"],
                approval_outcome=provisional,
            ),
        )
        approval = engine.ApprovalOutcome(
            "gate.route/v1",
            "full.intake.ready",
            {"intent_id": preview.intent["intent_id"]},
        )
        current_context = self.context(
            evidence,
            graph_value=graph_value,
            approval_current=True,
            approval_intent_id=preview.intent["intent_id"],
        )
        result = self.evaluate(
            workflow,
            evidence,
            current_context,
            preview=False,
            confirm_intent=preview.intent["intent_id"],
            approval_outcome=approval,
        )
        self.assertEqual(result.target, "READY")

    def test_schema_v2_standalone_behavior_needs_no_kernel_context(
        self,
    ) -> None:
        graph_value = canonical_graph()
        legacy = task_state()
        legacy["schema_version"] = 2
        del legacy["workflow_ref"]
        workflow = self.make_engine(graph_value)
        result = workflow.evaluate(
            legacy,
            expected_revision=4,
            action_id="transition",
            action_parameters={},
            evidence={},
            preview=True,
        )
        self.assertEqual(result.target, "READY")


if __name__ == "__main__":
    unittest.main()
