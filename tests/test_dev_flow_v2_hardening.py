from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import mock

if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case


dev_flow = test_case.dev_flow


class DevFlowV2HardeningTest(test_case.DevFlowTestCase):
    def _task_paths(self, task_id: str) -> tuple[Path, Path]:
        task_dir = self.data / "tasks" / task_id
        return task_dir / "state.json", task_dir / "events.jsonl"

    def _event_copy(self, events_path: Path, event_id: str) -> dict:
        event = json.loads(
            events_path.read_text(encoding="utf-8").splitlines()[-1]
        )
        event["event_id"] = event_id
        event["type"] = "hardening_test_pending"
        event["payload"] = {}
        event.pop("transaction_id", None)
        return event

    def _approved_lite_implementing(
        self, repository: Path, *, task_id: str, target_path: str
    ) -> dict:
        task = self.cli(
            "start",
            "--task-id",
            task_id,
            "--workspace-strategy",
            "in-place",
            "--requirement",
            "Exercise lite risk evidence",
            "--repo",
            str(repository),
            "--change-category",
            "internal",
            "--target-path",
            target_path,
        )["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "approve exact target",
        )
        task = dev_flow.load_state(task_id, self.data)
        preview = self.cli(
            "transition",
            task_id,
            "--expected-revision",
            str(task["revision"]),
            "--to",
            "IMPLEMENTING",
            "--preview",
        )
        self.cli(
            "transition",
            task_id,
            "--expected-revision",
            str(task["revision"]),
            "--to",
            "IMPLEMENTING",
            "--confirm-intent",
            preview["preview"]["intent_id"],
        )
        return dev_flow.load_state(task_id, self.data)

    def test_invalid_v2_contract_cannot_deliver_pending_event(self) -> None:
        repository, _ = self.make_repo("invalid-v2-outbox")
        task = self.start(repository, task_id="invalid-v2-outbox")["task"]
        state_path, events_path = self._task_paths(task["task_id"])
        damaged = copy.deepcopy(task)
        damaged["pending_event"] = self._event_copy(
            events_path, "pending-must-not-be-delivered"
        )
        risk = damaged["risk_assessment"]
        risk["decision"] = "safe"
        risk["reasons"] = []
        risk_payload = dict(risk)
        risk_payload.pop("sha256", None)
        risk["sha256"] = dev_flow._sha256_bytes(
            dev_flow._json_bytes(risk_payload)
        )
        dev_flow._atomic_write_json(state_path, damaged)
        state_before = state_path.read_bytes()
        events_before = events_path.read_bytes()

        with self.assertRaises(dev_flow.FlowError) as caught:
            dev_flow.load_state(task["task_id"], self.data)

        self.assertEqual(caught.exception.code, "STATE_INVARIANT_VIOLATION")
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(events_path.read_bytes(), events_before)
        self.assertNotIn(b"pending-must-not-be-delivered", events_before)

    def test_schema_types_and_v1_batch_outbox_fail_stably(self) -> None:
        repository, _ = self.make_repo("schema-hardening")
        task = self.start(repository, task_id="schema-hardening")["task"]
        state_path, events_path = self._task_paths(task["task_id"])

        invalid_schema = copy.deepcopy(task)
        invalid_schema["schema_version"] = []
        dev_flow._atomic_write_json(state_path, invalid_schema)
        with self.assertRaises(dev_flow.FlowError) as caught:
            dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_STATE")

        legacy = copy.deepcopy(task)
        legacy["schema_version"] = 1
        legacy.pop("confirmation_contract_version", None)
        legacy.pop("risk_assessment", None)
        first = self._event_copy(events_path, "legacy-batch-1")
        second = self._event_copy(events_path, "legacy-batch-2")
        for event in (first, second):
            event["transaction_id"] = "legacy-batch"
        legacy["pending_events"] = [first, second]
        dev_flow._atomic_write_json(state_path, legacy)
        events_before = events_path.read_bytes()
        with self.assertRaises(dev_flow.FlowError) as caught:
            dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(caught.exception.code, "PENDING_EVENT_INVALID")
        self.assertEqual(events_path.read_bytes(), events_before)

    def test_batch_outbox_requires_complete_common_transaction_metadata(
        self,
    ) -> None:
        repository, _ = self.make_repo("batch-hardening")
        task = self.start(repository, task_id="batch-hardening")["task"]
        _, events_path = self._task_paths(task["task_id"])
        first = self._event_copy(events_path, "batch-1")
        second = self._event_copy(events_path, "batch-2")
        first["transaction_id"] = "transaction"
        state = copy.deepcopy(task)
        state["pending_events"] = [first, second]

        with self.assertRaises(dev_flow.FlowError) as caught:
            dev_flow._validate_pending_event_outbox(
                self.data / "tasks" / task["task_id"], state
            )

        self.assertEqual(caught.exception.code, "PENDING_EVENT_INVALID")

    def test_schema_v2_config_requires_complete_risk_policy(self) -> None:
        self.data.mkdir(parents=True)
        path = dev_flow.config_path(self.data)
        for schema_version, risk_policy in (
            ([], None),
            (dev_flow.CONFIG_SCHEMA_VERSION, None),
            (dev_flow.CONFIG_SCHEMA_VERSION, {}),
            (
                dev_flow.CONFIG_SCHEMA_VERSION,
                {
                    "schema": "dev-flow-risk-policy/v1",
                    "protected_paths": [42],
                },
            ),
        ):
            with self.subTest(
                schema_version=schema_version, risk_policy=risk_policy
            ):
                document = {
                    "schema_version": schema_version,
                    "scope": {"mode": "all", "include": [], "exclude": []},
                }
                if risk_policy is not None:
                    document["risk_policy"] = risk_policy
                dev_flow._atomic_write_json(path, document)
                with self.assertRaises(dev_flow.FlowError) as caught:
                    dev_flow.load_config(self.data)
                self.assertEqual(caught.exception.code, "CONFIG_INVALID")

    def test_terminal_claim_scan_validates_schema_before_releasing_claim(
        self,
    ) -> None:
        repository, _ = self.make_repo("claim-schema-hardening")
        task = self.start(
            repository, task_id="claim-schema-hardening"
        )["task"]
        state_path, _ = self._task_paths(task["task_id"])
        damaged = copy.deepcopy(task)
        damaged["schema_version"] = 999
        damaged["status"] = "DONE"
        dev_flow._atomic_write_json(state_path, damaged)

        with self.assertRaises(dev_flow.FlowError) as caught:
            dev_flow._active_repository_claims(self.data)

        self.assertEqual(
            caught.exception.code, "REPOSITORY_CLAIM_UNAVAILABLE"
        )
        self.assertEqual(
            caught.exception.details["cause"], "UNSUPPORTED_STATE"
        )

    def test_git_risk_paths_reject_identity_collapsing_normalization(
        self,
    ) -> None:
        for path in (" tracked.txt", "tracked.txt ", r"docs\file.md"):
            with self.subTest(path=path):
                with self.assertRaises(dev_flow.FlowError) as caught:
                    dev_flow._decode_risk_paths(
                        path.encode("utf-8") + b"\0", source="test"
                    )
                self.assertEqual(
                    caught.exception.code, "RISK_EVIDENCE_INVALID"
                )

    def test_live_risk_unknown_message_is_redacted_before_hashing(
        self,
    ) -> None:
        repository, _ = self.make_repo("risk-redaction")
        task = self._approved_lite_implementing(
            repository,
            task_id="risk-redaction",
            target_path="tracked.txt",
        )
        with mock.patch.object(
            dev_flow,
            "_fingerprint_repo_once",
            side_effect=OSError("capture failed token=super-secret"),
        ):
            assessment, _ = dev_flow._capture_lite_change_assessment(
                task, self.data
            )

        self.assertNotIn("super-secret", json.dumps(assessment))
        self.assertEqual(
            dev_flow._redact_sensitive_value(assessment), assessment
        )
        stable = dict(assessment)
        recorded_sha = stable.pop("sha256")
        stable.pop("evaluated_at")
        self.assertEqual(
            recorded_sha,
            dev_flow._sha256_bytes(dev_flow._json_bytes(stable)),
        )

    def test_record_index_automatic_transition_uses_runtime_whitelist(
        self,
    ) -> None:
        repository, _ = self.make_repo("automatic-index-whitelist")
        task = self.start(
            repository, task_id="automatic-index-whitelist"
        )["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "approve baseline",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        repository_id = task["repositories"][0]["id"]

        with mock.patch.object(
            dev_flow, "AUTOMATIC_ACTION_EDGES", frozenset()
        ):
            rejected = self.mutate(
                "record-index",
                task,
                "--repo",
                repository_id,
                "--index-id",
                dev_flow._recommended_index_name(
                    task, task["repositories"][0], "baseline"
                ),
                expected_code=2,
            )

        self.assertEqual(
            rejected["error"]["code"], "AUTOMATIC_ACTION_NOT_ALLOWED"
        )
        unchanged = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(unchanged["status"], "BASELINED")
        self.assertIsNone(unchanged["repositories"][0]["index"])

    def test_schema_v1_route_ignores_untrusted_impact_contract_digest(
        self,
    ) -> None:
        impact = {
            "artifact_id": "impact-1",
            "sha256": "artifact-sha",
            "metadata": {
                "index_provenance_sha256": "index-sha",
                "impact_generation": 2,
                "impact_analysis_sha256": "legacy-user-value",
            },
        }
        route = {
            "value": "direct",
            "impact_artifact_id": "impact-1",
            "impact_sha256": "artifact-sha",
            "index_provenance_sha256": "index-sha",
            "impact_generation": 2,
        }
        approval = {
            "artifact_id": "impact-1",
            "index_provenance_sha256": "index-sha",
            "impact_generation": 2,
        }
        state = {
            "schema_version": 1,
            "route": route,
            "approvals": {"route": approval},
        }
        with mock.patch.object(
            dev_flow, "_require_current_impact", return_value=impact
        ):
            selected, selected_impact = (
                dev_flow._require_current_route_selection(state)
            )
        self.assertIs(selected, route)
        self.assertIs(selected_impact, impact)

        with (
            mock.patch.object(
                dev_flow,
                "_require_current_route_selection",
                return_value=(route, impact),
            ),
            mock.patch.object(
                dev_flow,
                "_require_gate_for_latest_artifact",
                return_value=(approval, impact),
            ),
        ):
            selected_approval, approved_impact = (
                dev_flow._require_route_gate(state)
            )
        self.assertIs(selected_approval, approval)
        self.assertIs(approved_impact, impact)

    def _assert_protected_rename_blocks(
        self, *, task_id: str, commit: bool
    ) -> None:
        repository, _ = self.make_repo(task_id)
        protected = repository / "api" / "routes.py"
        protected.parent.mkdir()
        protected.write_text("route = '/v1'\n", encoding="utf-8")
        test_case.git(repository, "add", "api/routes.py")
        test_case.git(repository, "commit", "-q", "-m", "add protected route")
        test_case.git(repository, "push", "-q", "origin", "main")
        task = self._approved_lite_implementing(
            repository,
            task_id=task_id,
            target_path="renamed-route.txt",
        )
        test_case.git(
            repository, "mv", "api/routes.py", "renamed-route.txt"
        )
        if commit:
            test_case.git(repository, "commit", "-q", "-m", "rename route")

        blocked = self.mutate("transition", task, "--to", "VERIFYING")

        self.assertEqual(blocked["status"], "BLOCKED")
        reasons = blocked["assessment"]["reasons"]
        self.assertTrue(
            any(
                reason.get("code") == "protected_path"
                and reason.get("path") == "api/routes.py"
                for reason in reasons
            )
        )
        self.assertEqual(
            set(blocked["assessment"]["changed_paths"]),
            {"api/routes.py", "renamed-route.txt"},
        )

    def test_staged_rename_from_protected_path_blocks_lite(self) -> None:
        self._assert_protected_rename_blocks(
            task_id="staged-protected-rename", commit=False
        )

    def test_committed_rename_from_protected_path_blocks_lite(self) -> None:
        self._assert_protected_rename_blocks(
            task_id="committed-protected-rename", commit=True
        )
