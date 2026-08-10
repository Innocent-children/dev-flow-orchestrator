"""Current controller boundary contracts."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
import unittest
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator import assurance as assurance_module
from dev_flow_orchestrator import controller as controller_module
from dev_flow_orchestrator import engine
from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.delivery import seal_record
from dev_flow_orchestrator.model import DevFlowError, freeze_json, json_value
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    IMPACT_CONFIDENCE_VALUES,
    MAX_IMPACT_ENTRIES,
    PLUGIN_DATA_NAMESPACE,
    RECEIPT_SCHEMA,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    TASK_CHANGE_CLAIMS_SCHEMA,
    WORKSPACE_FRESHNESS_SCHEMA,
)
from support import RepositoryTestCase, make_repository


class ControllerContractTests(RepositoryTestCase):
    @staticmethod
    def impact_payload(
        summary: str = "Impact bounded",
        *,
        confidence: object = "unknown",
    ) -> dict:
        return {
            "summary": summary,
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": "degraded",
            },
            "impact_manifest": {
                "confidence": confidence,
                "entries": [],
                "edges": [],
                "risk_triggers": [],
                "public_behavior": False,
                "documentation_required": False,
                "manual_evidence_required": False,
                "executable_reproduction_required": False,
                "overflow": False,
                "limitations": ["Explicit conservative controller test path"],
            },
        }

    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def persist_through_impact(
        self,
        *,
        confidence: object = "unknown",
        historical: bool = False,
    ) -> tuple[str, Path, str]:
        task_id = self.start_lite("Persist an impact record")
        self.apply_current(task_id, {})
        projection = self.controller.next(task_id)
        repository_id = self.controller.show(task_id).repositories[0].repository_id
        payload = self.impact_payload(
            "Persisted impact",
            confidence=confidence,
        )
        compatibility = (
            mock.patch.object(
                assurance_module,
                "IMPACT_CONFIDENCE_VALUES",
                (*IMPACT_CONFIDENCE_VALUES, freeze_json(confidence)),
            )
            if historical
            else mock.patch.object(
                assurance_module,
                "IMPACT_CONFIDENCE_VALUES",
                IMPACT_CONFIDENCE_VALUES,
            )
        )
        with compatibility:
            self.controller.apply(
                task_id,
                projection["action"]["action_id"],
                payload,
                binding=projection["action"]["binding"],
            )
        state_path = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )
        return task_id, state_path, repository_id

    def passing_verification(self, task_id: str, command: str) -> dict:
        projection = self.controller.next(task_id)
        obligation = projection["action"]["current_obligation"]
        result = {
            "obligation_id": obligation["obligation_id"],
            "passed": True,
            "evidence": [{
                "kind": "command",
                "reference": command,
                "summary": "Verification passed",
            }],
            "limitations": [],
        }
        if obligation["kind"] == "independent-review":
            review = projection["action"]["review_contract"]
            result["review"] = {
                "reviewer_available": True,
                "independent": True,
                "reviewer_digest": "a" * 64,
                "review_scope_digest": review["review_scope_digest"],
                "guidance_digest": review["guidance_digest"],
                "workspace_digest": review["workspace_digest"],
                "findings": [],
                "claimed_outcome": "approved",
            }
        return {"summary": "Verification passed", "assurance_result": result}

    def test_data_directory_must_be_disjoint_from_repository(self) -> None:
        cases = []

        inside = self.repository / "data"
        cases.append((
            Controller(str(inside)),
            self.repository,
            inside / PLUGIN_DATA_NAMESPACE / "tasks",
        ))

        cases.append(
            (
                Controller(str(self.repository)),
                self.repository,
                self.repository / PLUGIN_DATA_NAMESPACE / "tasks",
            )
        )

        data_root = self.root / "containing-data"
        data_root.mkdir()
        nested_repository = make_repository(data_root, "nested-repository")
        cases.append((
            Controller(str(data_root)),
            nested_repository,
            data_root / PLUGIN_DATA_NAMESPACE / "tasks",
        ))

        for controller, repository, state_root in cases:
            with self.subTest(data_dir=str(controller.store.root), repository=str(repository)):
                with self.assertRaises(DevFlowError) as context:
                    controller.start(
                        requirement="Keep state outside the repository",
                        workflow="lite",
                        repositories=(str(repository),),
                    )
                self.assertEqual(
                    context.exception.code, "DATA_DIR_INSIDE_REPOSITORY"
                )
                self.assertFalse(state_root.exists())

    def test_state_paths_are_private(self) -> None:
        task_id = self.start_lite()
        state_path = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )

        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(state_path.parent.stat().st_mode), 0o700)

    def test_explicit_task_id_is_persisted(self) -> None:
        state = self.controller.start(
            requirement="Named task",
            workflow="lite",
            repositories=(str(self.repository),),
            task_id="task-custom",
        )

        self.assertEqual(state.task_id, "task-custom")
        self.assertEqual(self.controller.show("task-custom").task_id, "task-custom")

    def test_current_namespace_replays_historical_effective_payload_bytes(self) -> None:
        started = self.controller.start(
            requirement="Replay a historical 0.4.0 task",
            workflow="lite",
            repositories=(str(self.repository),),
        )
        task_id = started.task_id
        self.apply_current(task_id, {})
        projection = self.controller.next(task_id)
        historical_payload = {
            "summary": "Historical impact record",
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": "degraded",
            },
        }

        original_validate = engine.validate_action_payload
        original_apply = engine.apply_current_action

        def historical_validate(contract, payload):
            return original_validate(
                contract,
                payload,
                legacy_compatibility=True,
            )

        def historical_apply(*args, **kwargs):
            return original_apply(
                *args,
                **kwargs,
                legacy_compatibility=True,
            )

        # Reproduce bytes accepted before the effective payload contract became
        # strict; the unpatched current reader below is the compatibility proof.
        with mock.patch.object(
            controller_module,
            "validate_action_payload",
            side_effect=historical_validate,
        ), mock.patch.object(
            controller_module,
            "apply_current_action",
            side_effect=historical_apply,
        ):
            self.controller.apply(
                task_id,
                projection["action"]["action_id"],
                historical_payload,
                binding=projection["action"]["binding"],
            )

        state_path = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )
        persisted = state_path.read_bytes()
        replayed = Controller(self.data_dir).show(task_id)

        self.assertEqual(state_path.read_bytes(), persisted)
        self.assertEqual(replayed.version, "0.4.0")
        self.assertEqual(replayed.workflow_identity, started.workflow_identity)
        self.assertEqual(replayed.records[-1]["payload"], historical_payload)

    def test_historical_non_enum_impact_replays_as_conservative_without_rewrite(self) -> None:
        legacy_confidence = "legacy-arbitrary-value"
        task_id, state_path, _repository_id = self.persist_through_impact(
            confidence=legacy_confidence,
            historical=True,
        )
        persisted = state_path.read_bytes()
        stored = json.loads(persisted)
        revision = stored["revision"]
        record_count = len(stored["records"])

        reader = Controller(self.data_dir)
        replayed = reader.show(task_id)
        reader.inspect_task(task_id)
        current = reader.next(task_id)

        self.assertEqual(state_path.read_bytes(), persisted)
        self.assertEqual(replayed.revision, revision)
        self.assertEqual(len(replayed.records), record_count)
        impact_record = replayed.records[-1]
        self.assertEqual(
            impact_record["payload"]["impact_manifest"]["confidence"],
            legacy_confidence,
        )
        derived = impact_record["artifact"]["body"]["impact_manifest"]
        self.assertEqual(derived["confidence"], "unknown")
        self.assertNotEqual(derived["confidence"], "source-confirmed")
        self.assertTrue(
            any(legacy_confidence in item for item in derived["limitations"])
        )
        self.assertEqual(current["action"]["action_id"], "implementation.record")

        self.apply_current(
            task_id,
            {
                "summary": "No source changes are needed for the replay proof",
                "ownership_claims": {
                    "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                    "claims": [],
                },
            },
        )
        assurance = self.controller.next(task_id)["action"]["assurance"]
        self.assertEqual(assurance["confidence"], "unknown")
        self.assertFalse(assurance["not_required"]["independent_review"])

    def test_live_non_enum_impact_is_rejected_without_mutation(self) -> None:
        task_id = self.start_lite("Reject a non-enum live confidence")
        self.apply_current(task_id, {})
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as caught:
            self.controller.apply(
                task_id,
                projection["action"]["action_id"],
                self.impact_payload(confidence="legacy-arbitrary-value"),
                binding=projection["action"]["binding"],
            )

        self.assertEqual(caught.exception.code, "IMPACT_INVALID")
        after = self.controller.show(task_id)
        self.assertEqual(after, before)
        self.assertEqual(after.current_node, "impact")
        self.assertEqual(len(after.records), 1)
        self.assertEqual(
            self.controller.next(task_id)["action"]["action_id"],
            projection["action"]["action_id"],
        )

    def test_historical_confidence_types_keep_exact_baseline_normalization(self) -> None:
        # The 0.4.0 baseline compared confidence only with source-confirmed and
        # conservatively normalized every other JSON value. Replay preserves
        # exactly that behavior; live validation remains covered separately.
        for confidence in (True, ["legacy"], {"legacy": True}):
            with self.subTest(confidence=confidence):
                task_id, _state_path, _repository_id = self.persist_through_impact(
                    confidence=confidence,
                    historical=True,
                )
                replayed = Controller(self.data_dir).show(task_id)
                derived = replayed.records[-1]["artifact"]["body"]["impact_manifest"]
                self.assertEqual(derived["confidence"], "unknown")
                self.controller.cancel(task_id, reason="Release the test repository")

    def test_historical_impact_structural_damage_still_fails_closed(self) -> None:
        def missing_confidence(manifest, _repository_id):
            manifest.pop("confidence")

        def invalid_entries(manifest, _repository_id):
            manifest["entries"] = [{"unexpected": True}]

        def invalid_repository(manifest, _repository_id):
            manifest["entries"] = [{
                "repository_id": "foreign-repository",
                "path": "foreign.txt",
                "symbol": None,
                "criterion_ids": ["requirement"],
            }]

        def extra_field(manifest, _repository_id):
            manifest["legacy_extra"] = True

        def overflow(manifest, repository_id):
            manifest["entries"] = [
                {
                    "repository_id": repository_id,
                    "path": "impact-{}.txt".format(index),
                    "symbol": None,
                    "criterion_ids": ["requirement"],
                }
                for index in range(MAX_IMPACT_ENTRIES + 1)
            ]

        task_id, state_path, repository_id = self.persist_through_impact()
        original = json.loads(state_path.read_text(encoding="utf-8"))
        for label, corrupt in (
            ("missing-confidence", missing_confidence),
            ("invalid-entries", invalid_entries),
            ("invalid-repository", invalid_repository),
            ("extra-field", extra_field),
            ("overflow", overflow),
        ):
            with self.subTest(case=label):
                document = json.loads(json.dumps(original))
                record = document["records"][-1]
                corrupt(record["payload"]["impact_manifest"], repository_id)
                document["records"][-1] = json_value(seal_record(record))
                state_path.write_text(json.dumps(document), encoding="utf-8")

                with self.assertRaises(DevFlowError) as caught:
                    Controller(self.data_dir).show(task_id)
                self.assertEqual(caught.exception.code, "STATE_INVALID")
                state_path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(Controller(self.data_dir).show(task_id).revision, 2)

    def test_wrong_action_is_rejected_without_mutation(self) -> None:
        task_id = self.start_lite()
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                "verification.record",
                {},
                binding=projection["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")
        self.assertEqual(self.controller.show(task_id), before)

    def test_invalid_payloads_are_rejected_without_mutation(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)
        valid = self.impact_payload("x")
        cases = (
            ({**valid, "extra": 1}, "extra"),
            ({}, "summary"),
            ({**valid, "summary": 42}, None),
        )

        for payload, detail in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(DevFlowError) as context:
                    self.controller.apply(
                        task_id,
                        projection["action"]["action_id"],
                        payload,
                        binding=projection["action"]["binding"],
                    )
                self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
                if detail is not None:
                    self.assertIn(detail, str(context.exception.details))
                self.assertEqual(self.controller.show(task_id), before)

    def test_stale_apply_after_terminal_returns_fresh_conflict(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        pending = self.controller.next(task_id)
        self.controller.cancel(task_id, reason="Stop before implementation")
        terminal = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                pending["action"]["action_id"],
                {"summary": "too late"},
                binding=pending["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        fresh = context.exception.details["projection"]
        self.assertEqual(fresh["revision"], terminal.revision)
        self.assertEqual(fresh["status"], "CANCELLED")
        self.assertTrue(fresh["done"])
        self.assertIsNone(fresh["action"])
        self.assertEqual(self.controller.show(task_id), terminal)

    def test_cancel_after_terminal_state_is_rejected(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        self.controller.cancel(task_id, reason="Stop once")

        with self.assertRaises(DevFlowError) as context:
            self.controller.cancel(task_id, reason="Stop twice")

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")

    def test_entry_stage_cancel_is_a_replayable_first_record(self) -> None:
        task_id = self.start_lite("Cancel before preflight")

        result = self.controller.cancel(
            task_id,
            reason="No delivery work should begin",
        )

        self.assertEqual(result["projection"]["status"], "CANCELLED")
        self.assertTrue(result["projection"]["done"])
        state = self.controller.show(task_id)
        self.assertEqual(state.revision, 1)
        self.assertEqual(len(state.records), 1)
        record = state.records[0]
        self.assertEqual(record["kind"], "action")
        self.assertEqual(record["producer"]["node_id"], "cancel")
        self.assertEqual(
            record["snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(Controller(self.data_dir).show(task_id), state)

    def test_cancel_is_rejected_outside_declared_stages(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        self.apply_current(task_id, self.impact_payload())
        self.apply_current(task_id, {
            "summary": "Implemented",
            "ownership_claims": {
                "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                "claims": [],
            },
        })
        while self.controller.next(task_id)["action"]["action_id"] == "assurance.execute":
            self.apply_current(
                task_id,
                self.passing_verification(task_id, "python3 -m unittest focused"),
            )
        before = self.controller.show(task_id)
        self.assertEqual(before.current_node, "finalize_success")

        with self.assertRaises(DevFlowError) as context:
            self.controller.cancel(task_id, reason="Too late for this stage")

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")
        self.assertEqual(self.controller.show(task_id), before)

    def test_missing_task_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.next("task-nope")
        self.assertEqual(context.exception.code, "TASK_NOT_FOUND")

    def test_empty_requirement_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="   ",
                workflow="lite",
                repositories=(str(self.repository),),
            )
        self.assertEqual(context.exception.code, "REQUIREMENT_INVALID")

    def test_truly_unknown_workflow_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="Unknown workflow",
                workflow="workflow-that-does-not-exist",
                repositories=(str(self.repository),),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")

    def test_apply_returns_current_receipt_and_projection(self) -> None:
        task_id = self.start_lite()
        projected = self.controller.next(task_id)
        result = self.controller.apply(
            task_id,
            projected["action"]["action_id"],
            {},
            binding=projected["action"]["binding"],
        )
        observed_at = result["receipt"]["workspace_freshness"]["observed_at"]
        self.assertIsInstance(observed_at, str)
        self.assertTrue(observed_at.endswith("Z"))

        self.assertEqual(
            result["receipt"],
            {
                "schema": RECEIPT_SCHEMA,
                "task_id": task_id,
                "action_id": "task.preflight",
                "committed_revision": 1,
                "status": "ANALYZING",
                "current_node": "impact",
                "committed": True,
                "workspace_freshness": {
                    "schema": WORKSPACE_FRESHNESS_SCHEMA,
                    "status": True,
                    "observed_at": observed_at,
                    "reasons": [],
                },
                "blind_retry": False,
                "recovery": {
                    "kind": "read-after-write",
                    "tool": "dev_flow_get_next_action",
                    "task_id": task_id,
                    "blind_retry": False,
                },
            },
        )
        self.assertEqual(result["projection"]["revision"], 1)
        self.assertEqual(result["projection"]["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(
            len(result["projection"]["repository_set"]["repositories"]),
            1,
        )
        self.assertEqual(
            result["projection"]["action"]["binding"][
                "starting_snapshot_digest"
            ],
            result["projection"]["repository_set"]["digest"],
        )
        self.assertEqual(
            self.controller.show_view(task_id)["current_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(
            result["projection"]["action"]["action_id"], "impact.record"
        )


if __name__ == "__main__":
    unittest.main()
