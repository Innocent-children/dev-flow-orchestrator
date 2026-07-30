from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow


class WorkflowActionServiceTests(DevFlowTestCase):
    def _persist_v3(
        self,
        task_id: str,
        *,
        status: str,
    ) -> tuple[Path, dict[str, object]]:
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        state = {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 0,
            "status": status,
            "flow": "full",
            "repositories": [],
            "route": None,
            **copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    task_id,
                    bundle,
                    execution_profile="single-repository",
                )
            ),
        }
        task_dir = dev_flow._task_dir(task_id, self.data)
        dev_flow._ensure_private_dir(task_dir)
        dev_flow._persist_state_transaction(
            None,
            state,
            task_dir,
            "task_started",
            {"status": status},
        )
        return task_dir, dev_flow.load_state(task_id, self.data)

    def _locks(self, task_dir: Path) -> tuple[object, object]:
        return (
            dev_flow._task_lock(task_dir),
            dev_flow._workspace_registry_lock(
                dev_flow.resolve_data_dir(self.data)
            ),
        )

    @staticmethod
    def _action_outcome(
        edge: object,
        delta: dict[str, object],
    ) -> object:
        return dev_flow.ActionOutcome(
            edge["trigger"]["id"],
            edge["id"],
            evidence_records=({"validator": "test/v1"},),
            proposed_state_delta=delta,
            audit_facts=(
                dev_flow.AuditFact(
                    "specialized-validator-accepted",
                    {"validator": "test/v1"},
                ),
            ),
        )

    @staticmethod
    def _event_records(task_dir: Path) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (task_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]

    def _prepared_receipt_context(
        self,
        state: dict[str, object],
        edge: object,
        *,
        promoted: bool = True,
        action_edge_id: str | None = None,
    ) -> object:
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "action_execution_journal"
            / "journal-core.json"
        )
        core = json.loads(fixture.read_text(encoding="utf-8"))
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        core["task_id"] = state["task_id"]
        core["execution_id"] = (
            "execution-" + str(state["task_id"]).replace("_", "-")
        )
        bindings = core["bindings"]
        bindings.update(
            {
                "task_revision": state["revision"],
                "pre_effect_state_sha256": dev_flow._sha256_contract(
                    state
                ),
                "workflow_id": bundle.workflow_id,
                "workflow_version": str(bundle.workflow_version),
                "workflow_bundle_sha256": bundle.bundle_sha256,
                "action_edge_id": (
                    edge["id"]
                    if action_edge_id is None
                    else action_edge_id
                ),
                "authorization_action_edge_id": (
                    edge["id"]
                    if action_edge_id is None
                    else action_edge_id
                ),
                "completion_edge_id": (
                    edge["id"]
                    if action_edge_id is None
                    else action_edge_id
                ),
                "handler_id": edge["handler"]["id"],
                "authorization_kind": "operator",
                "capability_sha256": None,
                "principal": "operator:test",
            }
        )
        record = dev_flow.seal_journal(core, manager_secret=None)
        initial_index = dev_flow.new_index(str(state["task_id"]))
        plan = dev_flow.plan_initial_write(
            initial_index,
            record,
            expected_index=dev_flow.cas_token(initial_index),
            manager_secret=None,
        )
        index = (
            plan.promoted_index if promoted else plan.reserved_index
        )
        return dev_flow.WorkflowActionReceiptContext(
            index=index,
            journal=record,
            expected_index=dev_flow.cas_token(index),
            reauthenticate=lambda: None,
        )

    def _verified_receipt_context(
        self,
        state: dict[str, object],
        edge: object,
        evaluation: object,
        task_dir: Path,
        *,
        forge_engine_binding: bool = False,
    ) -> object:
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "action_execution_journal"
            / "journal-core.json"
        )
        core = json.loads(fixture.read_text(encoding="utf-8"))
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        core["task_id"] = state["task_id"]
        core["execution_id"] = (
            "execution-" + str(state["task_id"]).replace("_", "-")
        )
        core["bindings"].update(
            {
                "task_revision": state["revision"],
                "pre_effect_state_sha256": dev_flow._sha256_contract(
                    state
                ),
                "workflow_id": bundle.workflow_id,
                "workflow_version": str(bundle.workflow_version),
                "workflow_bundle_sha256": bundle.bundle_sha256,
                "action_edge_id": edge["id"],
                "authorization_action_edge_id": edge["id"],
                "completion_edge_id": edge["id"],
                "handler_id": edge["handler"]["id"],
                "authorization_kind": "operator",
                "capability_sha256": None,
                "principal": "operator:test",
                "candidate_after_sha256": dev_flow._sha256_contract(
                    evaluation.candidate_state
                ),
            }
        )
        effect_id = core["effects"][0]["effect_id"]
        effect_receipt_sha256 = dev_flow._sha256_contract(
            {
                "schema": "test-effect-receipt/v1",
                "task_id": state["task_id"],
                "effect_id": effect_id,
            }
        )
        journal = dev_flow.seal_journal(core, manager_secret=None)
        initial_index = dev_flow.new_index(str(state["task_id"]))
        initial = dev_flow.plan_initial_write(
            initial_index,
            journal,
            expected_index=dev_flow.cas_token(initial_index),
            manager_secret=None,
        )
        index = initial.promoted_index

        def promote(updated: object) -> None:
            nonlocal index, journal
            plan = dev_flow.plan_journal_update(
                index,
                journal,
                updated,
                expected_index=dev_flow.cas_token(index),
                expected_journal=dev_flow.cas_token(journal),
                manager_secret=None,
            )
            index = plan.promoted_index
            journal = updated

        claim = dev_flow.plan_effect_claim(
            journal,
            effect_id,
            "claim-" + str(state["task_id"]).replace("_", "-"),
            index=index,
            expected_index=dev_flow.cas_token(index),
            manager_secret=None,
        )
        promote(claim.journal)
        containment = dev_flow.new_containment(
            journal,
            effect_id,
            index=index,
            expected_index=dev_flow.cas_token(index),
            manager_secret=None,
        )
        promote(
            dev_flow.advance_effect_phase(
                journal,
                effect_id,
                "RUNNING",
                manager_secret=None,
                containment_record_sha256=containment["record_sha256"],
            )
        )
        containment = dev_flow.advance_containment(
            containment,
            "QUIESCED",
            receipt_sha256=effect_receipt_sha256,
        )
        promote(
            dev_flow.advance_effect_phase(
                journal,
                effect_id,
                "QUIESCED",
                manager_secret=None,
                containment_record_sha256=containment["record_sha256"],
            )
        )
        promote(
            dev_flow.advance_effect_phase(
                journal,
                effect_id,
                "VERIFIED",
                manager_secret=None,
                containment_record_sha256=containment["record_sha256"],
                receipt_sha256=effect_receipt_sha256,
            )
        )
        promote(
            dev_flow.advance_global_settlement(
                journal, manager_secret=None
            )
        )
        receipt = dev_flow.build_v3_workflow_action_receipt(
            state,
            evaluation,
            task_dir,
            execution_id=str(core["execution_id"]),
            effect_receipt_sha256=effect_receipt_sha256,
        )
        if forge_engine_binding:
            receipt["engine_proof_sha256"] = "f" * 64
        promote(
            dev_flow.verify_receipt_intent(
                journal, receipt, manager_secret=None
            )
        )
        return dev_flow.WorkflowActionReceiptContext(
            index=index,
            journal=journal,
            expected_index=dev_flow.cas_token(index),
            reauthenticate=lambda: None,
        )

    def test_same_node_action_commits_field_and_pinned_audit_once(
        self,
    ) -> None:
        task_dir, current = self._persist_v3(
            "action-same-node", status="INDEXED"
        )
        task_lock, workspace_lock = self._locks(task_dir)
        with task_lock, workspace_lock:
            current = dev_flow.load_state(current["task_id"], self.data)
            edge = dev_flow.resolve_v3_node_action_edge(
                current, "set-route"
            )
            outcome = self._action_outcome(
                edge,
                {
                    "set": {
                        "/route": {
                            "value": "direct",
                            "reason": "bounded action service test",
                        }
                    },
                    "remove": [],
                    "operations": [],
                },
            )
            before_state = (task_dir / "state.json").read_bytes()
            before_events = (task_dir / "events.jsonl").read_bytes()
            preview = dev_flow.evaluate_v3_node_action(
                current,
                public_command="set-route",
                action_outcome=outcome,
                action_parameters={
                    "route": "direct",
                    "reason": "bounded action service test",
                },
                evidence={"validator": "test/v1"},
                preview=True,
            )
            self.assertEqual(
                (task_dir / "state.json").read_bytes(), before_state
            )
            self.assertEqual(
                (task_dir / "events.jsonl").read_bytes(), before_events
            )
            evaluation = dev_flow.evaluate_v3_node_action(
                current,
                public_command="set-route",
                action_outcome=outcome,
                action_parameters={
                    "route": "direct",
                    "reason": "bounded action service test",
                },
                evidence={"validator": "test/v1"},
                confirm_intent=preview.intent["intent_id"],
            )
            forged = dataclasses.replace(evaluation)
            with self.assertRaises(
                dev_flow.TransitionEngineError
            ) as forged_error:
                dev_flow.commit_v3_workflow_action(
                    current, forged, task_dir
                )
            self.assertEqual(
                forged_error.exception.code,
                "V3_ENGINE_EVALUATION_UNREGISTERED",
            )
            committed = dev_flow.commit_v3_workflow_action(
                current, evaluation, task_dir
            )
            committed_state_bytes = (
                task_dir / "state.json"
            ).read_bytes()
            committed_event_bytes = (
                task_dir / "events.jsonl"
            ).read_bytes()
            with self.assertRaises(
                dev_flow.TransitionEngineError
            ) as replay:
                dev_flow.commit_v3_workflow_action(
                    current, evaluation, task_dir
                )
            self.assertEqual(
                replay.exception.code,
                "V3_ENGINE_EVALUATION_UNREGISTERED",
            )
            self.assertEqual(
                (task_dir / "state.json").read_bytes(),
                committed_state_bytes,
            )
            self.assertEqual(
                (task_dir / "events.jsonl").read_bytes(),
                committed_event_bytes,
            )

        self.assertEqual(committed["status"], "INDEXED")
        self.assertEqual(committed["route"]["value"], "direct")
        self.assertEqual(
            committed["revision"], current["revision"] + 1
        )
        records = self._event_records(task_dir)
        route_events = [
            item for item in records if item["type"] == "route_set"
        ]
        self.assertEqual(len(route_events), 1)
        audit = [
            item["payload"]
            for item in records
            if item["type"] == "workflow_audit_fact"
        ]
        handler_fact = next(
            item
            for item in audit
            if item["fact_type"] == "pinned-action-handler-resolved"
        )
        self.assertEqual(
            handler_fact["fact"]["handler"]["id"],
            edge["handler"]["id"],
        )
        self.assertEqual(
            handler_fact["fact"]["handler"]["version"],
            edge["handler"]["version"],
        )
        self.assertFalse(
            handler_fact["fact"]["handler"]["executed"]
        )
        self.assertIn(
            "guard.index-current/v1",
            dict(evaluation.guard_results),
        )
        self.assertEqual(
            evaluation.intent["handlers"]["reducers"],
            edge["reducers"],
        )

    def test_movement_uses_same_engine_and_proof_boundary(self) -> None:
        task_dir, current = self._persist_v3(
            "action-movement", status="INTAKE"
        )
        task_lock, workspace_lock = self._locks(task_dir)
        with task_lock, workspace_lock:
            current = dev_flow.load_state(current["task_id"], self.data)
            edge = dev_flow.resolve_v3_movement_action_edge(
                current, "transition", target="BLOCKED"
            )
            blocked = {
                "phase": "manual",
                "from_status": "INTAKE",
                "reason": "wait for an operator",
                "details": [],
                "at": current["updated_at"],
            }
            outcome = self._action_outcome(
                edge,
                {
                    "set": {"/blocked": blocked},
                    "remove": [],
                    "operations": [],
                },
            )
            parameters = {
                "from": "INTAKE",
                "to": "BLOCKED",
                "note": "wait for an operator",
                "blocked": blocked,
            }
            preview = dev_flow.evaluate_v3_movement_action(
                current,
                public_command="transition",
                target="BLOCKED",
                action_outcome=outcome,
                action_parameters=parameters,
                preview=True,
            )
            evaluation = dev_flow.evaluate_v3_movement_action(
                current,
                public_command="transition",
                target="BLOCKED",
                action_outcome=outcome,
                action_parameters=parameters,
                confirm_intent=preview.intent["intent_id"],
            )
            committed = dev_flow.commit_v3_workflow_action(
                current, evaluation, task_dir
            )

        self.assertEqual(committed["status"], "BLOCKED")
        self.assertEqual(
            committed["blocked"]["from_status"], "INTAKE"
        )
        records = self._event_records(task_dir)
        movement = [
            item
            for item in records
            if item["type"] == "state_transitioned"
        ]
        self.assertEqual(len(movement), 1)
        self.assertEqual(
            movement[0]["payload"]["edge_id"], edge["id"]
        )

    def test_selection_failures_and_legacy_ids_are_zero_write(
        self,
    ) -> None:
        task_dir, current = self._persist_v3(
            "action-rejections", status="INDEXED"
        )
        state_bytes = (task_dir / "state.json").read_bytes()
        event_bytes = (task_dir / "events.jsonl").read_bytes()
        dummy = dev_flow.ActionOutcome(
            "set-route",
            "legacy.same-node.set-route",
        )
        cases = (
            (
                {**current, "status": "IMPACT_REVIEW"},
                "set-route",
                None,
                "WORKFLOW_ACTION_PLACEMENT_INVALID",
            ),
            (
                current,
                "unknown-command",
                None,
                "WORKFLOW_ACTION_UNDECLARED",
            ),
            (
                current,
                "record-artifact",
                None,
                "WORKFLOW_ACTION_SELECTOR_UNDECLARED",
            ),
            (
                current,
                "record-artifact",
                "free-form",
                "WORKFLOW_ACTION_SELECTOR_UNDECLARED",
            ),
            (
                {**current, "status": "BASELINED"},
                "approve-baseline-fetch",
                None,
                "WORKFLOW_ACTION_UNDECLARED",
            ),
        )
        for state, command, selector, code in cases:
            with self.subTest(command=command, selector=selector):
                with self.assertRaises(
                    dev_flow.TransitionEngineError
                ) as raised:
                    dev_flow.evaluate_v3_node_action(
                        state,
                        public_command=command,
                        selector=selector,
                        action_outcome=dummy,
                        preview=True,
                    )
                self.assertEqual(raised.exception.code, code)

        edge = dev_flow.resolve_v3_node_action_edge(
            current, "set-route"
        )
        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as old_outcome:
            dev_flow.evaluate_v3_node_action(
                current,
                public_command="set-route",
                action_outcome=dummy,
                preview=True,
            )
        self.assertEqual(
            old_outcome.exception.code,
            "WORKFLOW_ACTION_OUTCOME_MISMATCH",
        )
        self.assertNotEqual(dummy.action_id, edge["trigger"]["id"])

        bundle_type = type(
            dev_flow.workflow_runtime_services().catalog.resolve(
                "full", 3
            )
        )
        original = bundle_type.resolve_public_action

        def ambiguous(
            bundle: object,
            source: str,
            command: str,
            *,
            selector: str | None = None,
        ) -> object:
            if command == "set-route":
                raise dev_flow.WorkflowCatalogError(
                    "WORKFLOW_ACTION_SELECTION_AMBIGUOUS",
                    "fixture ambiguity",
                )
            return original(
                bundle, source, command, selector=selector
            )

        with mock.patch.object(
            bundle_type, "resolve_public_action", ambiguous
        ):
            with self.assertRaises(
                dev_flow.TransitionEngineError
            ) as raised:
                dev_flow.evaluate_v3_node_action(
                    current,
                    public_command="set-route",
                    action_outcome=dummy,
                    preview=True,
                )
            self.assertEqual(
                raised.exception.code,
                "WORKFLOW_ACTION_SELECTION_AMBIGUOUS",
            )

        self.assertEqual(
            (task_dir / "state.json").read_bytes(), state_bytes
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), event_bytes
        )

    def test_side_effect_action_is_plan_only_without_receipt(
        self,
    ) -> None:
        task_dir, current = self._persist_v3(
            "action-plan-only", status="INTAKE"
        )
        task_lock, workspace_lock = self._locks(task_dir)
        with task_lock, workspace_lock:
            current = dev_flow.load_state(current["task_id"], self.data)
            edge = dev_flow.resolve_v3_node_action_edge(
                current, "preflight", selector="initial"
            )
            outcome = self._action_outcome(
                edge,
                {
                    "set": {
                        "/preflight": {"result": "ready"},
                        "/repositories": [],
                        "/risk_assessment": {"result": "safe"},
                    },
                    "remove": [],
                    "operations": [],
                },
            )
            before_state = (task_dir / "state.json").read_bytes()
            before_events = (task_dir / "events.jsonl").read_bytes()
            preview = dev_flow.evaluate_v3_node_action(
                current,
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters={"mode": "initial"},
                preview=True,
            )
            with self.assertRaises(
                dev_flow.TransitionEngineError
            ) as raised:
                dev_flow.evaluate_v3_node_action(
                    current,
                    public_command="preflight",
                    selector="initial",
                    action_outcome=outcome,
                    action_parameters={"mode": "initial"},
                    confirm_intent=preview.intent["intent_id"],
                )
            self.assertEqual(
                raised.exception.code,
                "WORKFLOW_ACTION_RECEIPT_REQUIRED",
            )
            with self.assertRaises(
                dev_flow.TransitionEngineError
            ) as preview_commit:
                dev_flow.commit_v3_workflow_action(
                    current, preview, task_dir
                )
            self.assertEqual(
                preview_commit.exception.code,
                "WORKFLOW_ACTION_RECEIPT_REQUIRED",
            )
            self.assertEqual(
                (task_dir / "state.json").read_bytes(), before_state
            )
            self.assertEqual(
                (task_dir / "events.jsonl").read_bytes(),
                before_events,
            )

    def test_verified_receipt_binds_restart_stable_engine_intent(
        self,
    ) -> None:
        task_dir, current = self._persist_v3(
            "action-verified-receipt", status="INTAKE"
        )
        task_lock, workspace_lock = self._locks(task_dir)
        with task_lock, workspace_lock:
            current = dev_flow.load_state(current["task_id"], self.data)
            edge = dev_flow.resolve_v3_node_action_edge(
                current, "preflight", selector="initial"
            )
            outcome = self._action_outcome(
                edge,
                {
                    "set": {
                        "/preflight": {"status": "ready"},
                        "/repositories": [],
                        "/risk_assessment": {"level": "low"},
                    },
                    "remove": [],
                    "operations": [],
                },
            )
            preview = dev_flow.evaluate_v3_node_action(
                current,
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters={"mode": "initial"},
                evidence={"validator": "test/v1"},
                preview=True,
            )
            context = self._verified_receipt_context(
                current, edge, preview, task_dir
            )
            evaluation = dev_flow.evaluate_v3_node_action(
                current,
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters={"mode": "initial"},
                evidence={"validator": "test/v1"},
                confirm_intent=preview.intent["intent_id"],
                receipt_context=context,
            )
            self.assertEqual(
                evaluation.intent["intent_id"],
                preview.intent["intent_id"],
            )
            committed = dev_flow.commit_v3_workflow_action(
                current,
                evaluation,
                task_dir,
                receipt_context=context,
            )
        self.assertEqual(committed["preflight"]["status"], "ready")
        self.assertEqual(committed["revision"], current["revision"] + 1)
        recorded = next(
            item
            for item in self._event_records(task_dir)
            if item["type"] == "preflight_recorded"
        )
        self.assertEqual(
            recorded["payload"]["execution"]["execution_id"],
            context.journal["execution_id"],
        )
        self.assertEqual(
            recorded["payload"]["execution"]["receipt_sha256"],
            context.journal["receipt"]["receipt_sha256"],
        )

    def test_forged_engine_binding_receipt_is_zero_write(self) -> None:
        task_dir, current = self._persist_v3(
            "action-forged-proof-receipt", status="INTAKE"
        )
        task_lock, workspace_lock = self._locks(task_dir)
        with task_lock, workspace_lock:
            current = dev_flow.load_state(current["task_id"], self.data)
            edge = dev_flow.resolve_v3_node_action_edge(
                current, "preflight", selector="initial"
            )
            outcome = self._action_outcome(
                edge,
                {
                    "set": {
                        "/preflight": {"status": "ready"},
                        "/repositories": [],
                        "/risk_assessment": {"level": "low"},
                    },
                    "remove": [],
                    "operations": [],
                },
            )
            preview = dev_flow.evaluate_v3_node_action(
                current,
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters={"mode": "initial"},
                evidence={"validator": "test/v1"},
                preview=True,
            )
            context = self._verified_receipt_context(
                current,
                edge,
                preview,
                task_dir,
                forge_engine_binding=True,
            )
            evaluation = dev_flow.evaluate_v3_node_action(
                current,
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters={"mode": "initial"},
                evidence={"validator": "test/v1"},
                confirm_intent=preview.intent["intent_id"],
                receipt_context=context,
            )
            before_state = (task_dir / "state.json").read_bytes()
            before_events = (task_dir / "events.jsonl").read_bytes()
            with self.assertRaises(
                dev_flow.TransitionEngineError
            ) as raised:
                dev_flow.commit_v3_workflow_action(
                    current,
                    evaluation,
                    task_dir,
                    receipt_context=context,
                )
            self.assertEqual(
                raised.exception.code,
                "WORKFLOW_ACTION_JOURNAL_PROOF_MISMATCH",
            )
            self.assertEqual(
                (task_dir / "state.json").read_bytes(), before_state
            )
            self.assertEqual(
                (task_dir / "events.jsonl").read_bytes(), before_events
            )

    def test_journal_phase_promotion_and_action_binding_fail_zero_write(
        self,
    ) -> None:
        task_dir, current = self._persist_v3(
            "action-journal-gates", status="INTAKE"
        )
        task_lock, workspace_lock = self._locks(task_dir)
        with task_lock, workspace_lock:
            current = dev_flow.load_state(current["task_id"], self.data)
            edge = dev_flow.resolve_v3_node_action_edge(
                current, "preflight", selector="initial"
            )
            outcome = self._action_outcome(
                edge,
                {
                    "set": {
                        "/preflight": {"status": "ready"},
                        "/repositories": [],
                        "/risk_assessment": {"level": "low"},
                    },
                    "remove": [],
                    "operations": [],
                },
            )
            before_state = (task_dir / "state.json").read_bytes()
            before_events = (task_dir / "events.jsonl").read_bytes()
            cases = (
                (
                    {"receipt": {"receipt_sha256": "0" * 64}},
                    "WORKFLOW_ACTION_JOURNAL_CONTEXT_INVALID",
                ),
                (
                    self._prepared_receipt_context(
                        current, edge, promoted=False
                    ),
                    "ACTION_JOURNAL_NOT_PROMOTED",
                ),
                (
                    self._prepared_receipt_context(current, edge),
                    "WORKFLOW_ACTION_JOURNAL_PHASE_INVALID",
                ),
                (
                    self._prepared_receipt_context(
                        current,
                        edge,
                        action_edge_id="full.action.intake.other.v1",
                    ),
                    "WORKFLOW_ACTION_JOURNAL_BINDING_MISMATCH",
                ),
            )
            for context, code in cases:
                with self.subTest(code=code):
                    with self.assertRaises(
                        dev_flow.TransitionEngineError
                    ) as error:
                        dev_flow.evaluate_v3_node_action(
                            current,
                            public_command="preflight",
                            selector="initial",
                            action_outcome=outcome,
                            action_parameters={"mode": "initial"},
                            evidence={"validator": "test/v1"},
                            preview=True,
                            receipt_context=context,
                        )
                    self.assertEqual(error.exception.code, code)
                    self.assertEqual(
                        (task_dir / "state.json").read_bytes(),
                        before_state,
                    )
                    self.assertEqual(
                        (task_dir / "events.jsonl").read_bytes(),
                        before_events,
                    )


if __name__ == "__main__":
    import unittest

    unittest.main()
