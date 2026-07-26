from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock


if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case

dev_flow = test_case.dev_flow


class DevFlowV2ContractTest(test_case.DevFlowTestCase):
    def start_lite(
        self,
        *repositories: Path,
        task_id: str,
        categories: tuple[str, ...] = ("internal",),
        target_paths: tuple[str, ...] = ("tracked.txt",),
        expected_code: int = 0,
    ) -> dict:
        arguments = [
            "start",
            "--task-id",
            task_id,
            "--workspace-strategy",
            "in-place",
            "--requirement",
            "Implement a declared low-risk change",
        ]
        for repository in repositories:
            arguments.extend(["--repo", str(repository)])
        for category in categories:
            arguments.extend(["--change-category", category])
        for target_path in target_paths:
            arguments.extend(["--target-path", target_path])
        return self.cli(*arguments, expected_code=expected_code)

    def preview_transition(
        self,
        task: dict,
        target: str,
        *,
        note: str | None = None,
    ) -> dict:
        arguments = [
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--to",
            target,
            "--preview",
        ]
        if note is not None:
            arguments.extend(["--note", note])
        return self.cli(*arguments)

    def confirm_transition(
        self,
        task: dict,
        target: str,
        intent_id: str,
        *,
        note: str | None = None,
        expected_code: int = 0,
    ) -> dict:
        arguments = [
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--to",
            target,
            "--confirm-intent",
            intent_id,
        ]
        if note is not None:
            arguments.extend(["--note", note])
        return self.cli(*arguments, expected_code=expected_code)

    def approved_lite_task(self, repository: Path, *, task_id: str) -> dict:
        task = self.start_lite(repository, task_id=task_id)["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "declared low-risk change approved",
        )
        return dev_flow.load_state(task_id, self.data)

    def impact_metadata(
        self,
        repository_id: str = "repository",
        *,
        coverage: str = "complete",
    ) -> dict:
        return {
            "schema": "dev-flow-impact-analysis/v1",
            "strategy": "funnel",
            "coverage": coverage,
            "budget_profile": "seed-v1",
            "repositories": [
                {
                    "repository_id": repository_id,
                    "index_id": "index-1",
                    "index_mode": "fast",
                    "checks": {
                        name: {"status": "complete"}
                        for name in dev_flow.IMPACT_CHECKS
                    },
                    "queries": {
                        name: 0 for name in dev_flow.IMPACT_QUERY_KEYS
                    },
                    "unresolved_truncations": [],
                    "material_unknowns": [],
                }
            ],
            "cross_repository": {
                "status": "not_applicable",
                "reason": "single repository task",
            },
        }

    def test_new_tasks_use_schema_v2_and_full_allows_no_lite_declaration(
        self,
    ) -> None:
        repository, _ = self.make_repo("v2-full")

        response = self.start(repository, task_id="v2-full")
        task = response["task"]

        self.assertEqual(task["schema_version"], dev_flow.TASK_SCHEMA_VERSION)
        self.assertEqual(
            task["confirmation_contract_version"],
            dev_flow.CONFIRMATION_CONTRACT_VERSION,
        )
        self.assertEqual(task["flow"], "full")
        self.assertEqual(task["workspace"]["strategy"], "worktree")
        self.assertEqual(
            task["risk_assessment"]["decision"],
            "requires_full",
        )
        self.assertEqual(task["risk_assessment"]["categories"], [])
        self.assertEqual(task["risk_assessment"]["target_paths"], [])
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data),
            task,
        )

    def test_lite_start_requires_complete_low_risk_declaration(
        self,
    ) -> None:
        repository, _ = self.make_repo("v2-lite-risk")
        second_repository, _ = self.make_repo("v2-lite-risk-second")

        rejected_cases = (
            (
                "missing-category",
                (repository,),
                (),
                ("tracked.txt",),
                "change_category_unknown",
            ),
            (
                "missing-target",
                (repository,),
                ("internal",),
                (),
                "target_paths_unknown",
            ),
            (
                "high-risk",
                (repository,),
                ("public-api",),
                ("tracked.txt",),
                "full_only_category",
            ),
            (
                "unknown-category",
                (repository,),
                ("maybe-safe",),
                ("tracked.txt",),
                "change_category_unknown",
            ),
            (
                "protected-target",
                (repository,),
                ("internal",),
                ("api/routes.py",),
                "protected_path",
            ),
            (
                "multiple-repositories",
                (repository, second_repository),
                ("tests",),
                ("tracked.txt",),
                "cross_repository",
            ),
        )
        for (
            task_id,
            repositories,
            categories,
            target_paths,
            reason_code,
        ) in rejected_cases:
            with self.subTest(task_id=task_id):
                rejected = self.start_lite(
                    *repositories,
                    task_id=task_id,
                    categories=categories,
                    target_paths=target_paths,
                    expected_code=2,
                )
                self.assertEqual(
                    rejected["error"]["code"],
                    "LITE_REQUIRES_FULL",
                )
                details = rejected["error"]["details"]
                self.assertEqual(details["required_flow"], "full")
                self.assertIn(
                    reason_code,
                    {
                        reason["code"]
                        for reason in details["assessment"]["reasons"]
                    },
                )
                self.assertFalse(
                    (
                        self.data
                        / "tasks"
                        / task_id
                        / "state.json"
                    ).exists()
                )

        accepted = self.start_lite(
            repository,
            task_id="declared-lite",
            categories=("internal", "tests"),
            target_paths=("tracked.txt",),
        )["task"]
        self.assertEqual(accepted["schema_version"], 2)
        self.assertEqual(accepted["flow"], "lite")
        self.assertEqual(accepted["risk_assessment"]["decision"], "safe")
        self.assertEqual(
            accepted["risk_assessment"]["categories"],
            ["internal", "tests"],
        )
        self.assertEqual(
            accepted["risk_assessment"]["target_paths"],
            ["tracked.txt"],
        )
        self.assertEqual(
            accepted["risk_assessment"]["repository_count"],
            1,
        )

    def test_config_v1_upgrade_preserves_scope_and_validates_risk_globs(
        self,
    ) -> None:
        included = self.root / "included"
        included.mkdir()
        self.data.mkdir(parents=True)
        path = dev_flow.config_path(self.data)
        dev_flow._atomic_write_json(
            path,
            {
                "schema_version": 1,
                "scope": {
                    "mode": "allowlist",
                    "include": [str(included)],
                    "exclude": [],
                },
            },
        )

        compatible = dev_flow.load_config(self.data)
        self.assertEqual(
            compatible["schema_version"],
            dev_flow.CONFIG_SCHEMA_VERSION,
        )
        self.assertEqual(
            compatible["scope"]["include"],
            [str(included.resolve())],
        )
        self.assertEqual(
            compatible["risk_policy"]["protected_paths"],
            sorted(dev_flow.DEFAULT_PROTECTED_PATH_GLOBS),
        )

        updated = self.cli(
            "scope",
            "--add-protected-path",
            "generated/contracts/**",
        )
        self.assertTrue(updated["changed"])
        self.assertEqual(
            updated["scope"]["include"],
            [str(included.resolve())],
        )
        self.assertIn(
            "generated/contracts/**",
            updated["risk_policy"]["protected_paths"],
        )
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            stored["schema_version"],
            dev_flow.CONFIG_SCHEMA_VERSION,
        )
        self.assertEqual(
            stored["scope"]["include"],
            [str(included.resolve())],
        )
        self.assertEqual(
            dev_flow._protected_path_match(
                "generated/contracts/api.json",
                stored["risk_policy"],
            ),
            "generated/contracts/**",
        )

        before_invalid = path.read_bytes()
        invalid = self.cli(
            "scope",
            "--add-protected-path",
            "../outside/**",
            expected_code=2,
        )
        self.assertEqual(invalid["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(path.read_bytes(), before_invalid)

    def test_lite_transition_intents_keep_only_exact_safe_edge_automatic(
        self,
    ) -> None:
        repository, _ = self.make_repo("v2-lite-intents")
        task = self.approved_lite_task(
            repository,
            task_id="v2-lite-intents",
        )

        direct = self.mutate(
            "transition",
            task,
            "--to",
            "IMPLEMENTING",
            expected_code=2,
        )
        self.assertEqual(
            direct["error"]["code"],
            "TRANSITION_INTENT_REQUIRED",
        )
        entry_preview = self.preview_transition(task, "IMPLEMENTING")
        self.assertTrue(entry_preview["preview"]["requires_confirmation"])
        self.assertEqual(
            entry_preview["preview"]["confirmation_mode"],
            "explicit",
        )
        entered = self.confirm_transition(
            task,
            "IMPLEMENTING",
            entry_preview["preview"]["intent_id"],
        )
        self.assertEqual(entered["status"], "IMPLEMENTING")

        task = dev_flow.load_state(task["task_id"], self.data)
        (repository / "tracked.txt").write_text(
            "declared implementation\n",
            encoding="utf-8",
        )
        verifying = self.mutate(
            "transition",
            task,
            "--to",
            "VERIFYING",
        )
        self.assertEqual(verifying["status"], "VERIFYING")
        self.assertEqual(
            verifying["transition"]["confirmation_mode"],
            "automatic",
        )

        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "record-test",
            task,
            "--name",
            "focused-v2",
            "--command",
            "python -m unittest tests.test_dev_flow_v2",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        direct_done = self.mutate(
            "transition",
            task,
            "--to",
            "DONE",
            expected_code=2,
        )
        self.assertEqual(
            direct_done["error"]["code"],
            "TRANSITION_INTENT_REQUIRED",
        )

        done_preview = self.preview_transition(task, "DONE")
        self.assertTrue(done_preview["preview"]["requires_confirmation"])
        self.assertEqual(
            done_preview["preview"]["confirmation_mode"],
            "explicit",
        )
        self.assertIn(
            "irreversible-terminal-state",
            done_preview["preview"]["side_effects"],
        )
        self.assertIn(
            "repository-claim-release",
            done_preview["preview"]["side_effects"],
        )
        completed = self.confirm_transition(
            task,
            "DONE",
            done_preview["preview"]["intent_id"],
        )
        self.assertEqual(completed["status"], "DONE")

    def test_cancel_intent_detects_evidence_and_revision_staleness(
        self,
    ) -> None:
        repository, _ = self.make_repo("v2-cancel-intent")
        task = self.start(
            repository,
            task_id="v2-cancel-intent",
        )["task"]
        transition_preview = self.preview_transition(
            task,
            "CANCELLED",
            note="cancel through the generic transition",
        )
        repeated_transition_preview = self.preview_transition(
            task,
            "CANCELLED",
            note="cancel through the generic transition",
        )
        self.assertEqual(
            transition_preview["preview"]["side_effects"],
            [
                "task-state",
                "irreversible-terminal-state",
                "repository-claim-release",
            ],
        )
        self.assertEqual(
            transition_preview["preview"]["intent_id"],
            repeated_transition_preview["preview"]["intent_id"],
        )
        preview = self.cli(
            "cancel",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--reason",
            "cancel the obsolete task",
            "--preview",
        )
        intent_id = preview["preview"]["intent_id"]
        self.assertEqual(
            preview["preview"]["confirmation_mode"],
            "explicit",
        )
        self.assertIn(
            "repository-claim-release",
            preview["preview"]["side_effects"],
        )

        (repository / "tracked.txt").write_text(
            "changed after preview\n",
            encoding="utf-8",
        )
        stale_evidence = self.cli(
            "cancel",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--reason",
            "cancel the obsolete task",
            "--confirm-intent",
            intent_id,
            expected_code=2,
        )
        self.assertEqual(stale_evidence["error"]["code"], "INTENT_STALE")

        current = dev_flow.load_state(task["task_id"], self.data)
        second_preview = self.cli(
            "cancel",
            current["task_id"],
            "--expected-revision",
            str(current["revision"]),
            "--reason",
            "cancel the obsolete task",
            "--preview",
        )
        task_dir = self.data / "tasks" / current["task_id"]
        replacement = dev_flow._copy_state(current)
        replacement["requirement"] = "revision changed after preview"
        dev_flow._commit_state(
            current,
            replacement,
            task_dir,
            "test_revision_changed",
        )
        current = dev_flow.load_state(task["task_id"], self.data)
        stale_revision = self.cli(
            "cancel",
            current["task_id"],
            "--expected-revision",
            str(current["revision"]),
            "--reason",
            "cancel the obsolete task",
            "--confirm-intent",
            second_preview["preview"]["intent_id"],
            expected_code=2,
        )
        self.assertEqual(stale_revision["error"]["code"], "INTENT_STALE")

        missing_intent = self.cli(
            "cancel",
            current["task_id"],
            "--expected-revision",
            str(current["revision"]),
            "--reason",
            "cancel the obsolete task",
            expected_code=2,
        )
        self.assertEqual(
            missing_intent["error"]["code"],
            "TRANSITION_INTENT_REQUIRED",
        )
        final_preview = self.cli(
            "cancel",
            current["task_id"],
            "--expected-revision",
            str(current["revision"]),
            "--reason",
            "cancel the obsolete task",
            "--preview",
        )
        cancelled = self.cli(
            "cancel",
            current["task_id"],
            "--expected-revision",
            str(current["revision"]),
            "--reason",
            "cancel the obsolete task",
            "--confirm-intent",
            final_preview["preview"]["intent_id"],
        )
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(
            cancelled["confirmation"]["intent_id"],
            final_preview["preview"]["intent_id"],
        )

        events = [
            json.loads(line)
            for line in (task_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        cancellation_facts = [
            event
            for event in events
            if event["type"] in {"task_cancelled", "state_transitioned"}
            and event["revision"] == cancelled["revision"]
        ]
        self.assertEqual(
            {event["type"] for event in cancellation_facts},
            {"task_cancelled", "state_transitioned"},
        )
        self.assertEqual(
            len(
                {
                    event["transaction_id"]
                    for event in cancellation_facts
                }
            ),
            1,
        )
        self.assertEqual(
            {
                event["payload"]["intent_id"]
                for event in cancellation_facts
            },
            {final_preview["preview"]["intent_id"]},
        )

    def test_cancellation_intents_survive_unavailable_fingerprints(self) -> None:
        transition_repository, _ = self.make_repo(
            "v2-cancel-unavailable-transition"
        )
        cancel_repository, _ = self.make_repo(
            "v2-cancel-unavailable-command"
        )
        transition_task = self.start(
            transition_repository,
            task_id="v2-cancel-unavailable-transition",
        )["task"]
        failure = dev_flow.FlowError(
            "COMMAND_FAILED",
            "fingerprint evidence is unavailable",
        )

        with mock.patch.object(
            dev_flow,
            "_current_repository_fingerprints",
            side_effect=failure,
        ):
            transition_preview = self.preview_transition(
                transition_task,
                "CANCELLED",
                note="cancel despite unavailable repository evidence",
            )
            repeated_preview = self.preview_transition(
                transition_task,
                "CANCELLED",
                note="cancel despite unavailable repository evidence",
            )
            self.assertEqual(
                transition_preview["preview"]["intent_id"],
                repeated_preview["preview"]["intent_id"],
            )
            transitioned = self.confirm_transition(
                transition_task,
                "CANCELLED",
                transition_preview["preview"]["intent_id"],
                note="cancel despite unavailable repository evidence",
            )
            self.assertEqual(transitioned["status"], "CANCELLED")

            evidence_changed = json.loads(json.dumps(transition_task))
            evidence_changed["risk_assessment"]["sha256"] = (
                "changed-risk-evidence"
            )
            changed_evidence_preview = dev_flow._transition_intent_preview(
                evidence_changed,
                "INTAKE",
                "CANCELLED",
                action="transition",
                action_parameters={
                    "note": "cancel despite unavailable repository evidence"
                },
            )
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._assert_confirmation_intent(
                    changed_evidence_preview,
                    transition_preview["preview"]["intent_id"],
                )
            self.assertEqual(captured.exception.code, "INTENT_STALE")

            revision_changed = json.loads(json.dumps(transition_task))
            revision_changed["revision"] += 1
            changed_revision_preview = dev_flow._transition_intent_preview(
                revision_changed,
                "INTAKE",
                "CANCELLED",
                action="transition",
                action_parameters={
                    "note": "cancel despite unavailable repository evidence"
                },
            )
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._assert_confirmation_intent(
                    changed_revision_preview,
                    transition_preview["preview"]["intent_id"],
                )
            self.assertEqual(captured.exception.code, "INTENT_STALE")

            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._transition_intent_preview(
                    transition_task,
                    "INTAKE",
                    "DONE",
                    action="transition",
                    action_parameters={"note": None},
                )
            self.assertEqual(captured.exception.code, "COMMAND_FAILED")

        cancel_task = self.start(
            cancel_repository,
            task_id="v2-cancel-unavailable-command",
        )["task"]
        with mock.patch.object(
            dev_flow,
            "_current_repository_fingerprints",
            side_effect=failure,
        ):
            cancel_preview = self.cli(
                "cancel",
                cancel_task["task_id"],
                "--expected-revision",
                str(cancel_task["revision"]),
                "--reason",
                "cancel despite unavailable repository evidence",
                "--preview",
            )
            cancelled = self.cli(
                "cancel",
                cancel_task["task_id"],
                "--expected-revision",
                str(cancel_task["revision"]),
                "--reason",
                "cancel despite unavailable repository evidence",
                "--confirm-intent",
                cancel_preview["preview"]["intent_id"],
            )
        self.assertEqual(cancelled["status"], "CANCELLED")

    def test_live_protected_diff_blocks_lite_and_requires_replacement(
        self,
    ) -> None:
        repository, _ = self.make_repo("v2-live-risk")
        task = self.approved_lite_task(
            repository,
            task_id="v2-live-risk",
        )
        entry_preview = self.preview_transition(task, "IMPLEMENTING")
        self.confirm_transition(
            task,
            "IMPLEMENTING",
            entry_preview["preview"]["intent_id"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        protected = repository / "api" / "routes.py"
        protected.parent.mkdir()
        protected.write_text("route = '/v2'\n", encoding="utf-8")

        escalated = self.mutate(
            "transition",
            task,
            "--to",
            "VERIFYING",
        )

        self.assertFalse(escalated["transition_applied"])
        self.assertEqual(escalated["status"], "BLOCKED")
        self.assertEqual(escalated["required_flow"], "full")
        reason_codes = {
            reason["code"]
            for reason in escalated["assessment"]["reasons"]
        }
        self.assertIn("protected_path", reason_codes)
        self.assertIn("undeclared_changed_path", reason_codes)
        blocked = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(blocked["blocked"]["phase"], "lite-risk")
        self.assertEqual(blocked["blocked"]["required_flow"], "full")
        self.assertEqual(blocked["blocked"]["from_status"], "IMPLEMENTING")
        self.assertEqual(blocked["flow"], "lite")
        self.assertEqual(blocked["workspace"]["strategy"], "in-place")
        resume = self.mutate(
            "transition",
            blocked,
            "--to",
            "IMPLEMENTING",
            expected_code=2,
        )
        self.assertEqual(
            resume["error"]["code"], "LITE_REPLACEMENT_REQUIRED"
        )

    def test_batched_outbox_recovers_idempotently_after_partial_delivery(
        self,
    ) -> None:
        repository, _ = self.make_repo("v2-batched-outbox")
        task = self.start(
            repository,
            task_id="v2-batched-outbox",
        )["task"]
        task_dir = self.data / "tasks" / task["task_id"]
        current = dev_flow.load_state(task["task_id"], self.data)
        replacement = dev_flow._copy_state(current)
        replacement["requirement"] = "commit two audit facts"
        real_append = dev_flow._append_event
        calls = 0

        def fail_second_append(path: Path, event: dict) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise dev_flow.FlowError(
                    "EVENT_APPEND_FAILED",
                    "injected second event failure",
                )
            real_append(path, event)

        with mock.patch.object(
            dev_flow,
            "_append_event",
            side_effect=fail_second_append,
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._commit_state(
                    current,
                    replacement,
                    task_dir,
                    "primary_fact",
                    {"kind": "primary"},
                    additional_events=[
                        ("transition_fact", {"kind": "transition"})
                    ],
                )
        self.assertEqual(
            captured.exception.code,
            "EVENT_DELIVERY_PENDING",
        )
        persisted = json.loads(
            (task_dir / "state.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("pending_event", persisted)
        self.assertEqual(len(persisted["pending_events"]), 2)
        pending_ids = {
            event["event_id"] for event in persisted["pending_events"]
        }
        self.assertEqual(
            len(
                {
                    event["transaction_id"]
                    for event in persisted["pending_events"]
                }
            ),
            1,
        )

        recovered = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("pending_event", recovered)
        self.assertNotIn("pending_events", recovered)
        events_path = task_dir / "events.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            {
                event["type"]
                for event in events
                if event["event_id"] in pending_ids
            },
            {"primary_fact", "transition_fact"},
        )
        for event_id in pending_ids:
            self.assertEqual(
                sum(event["event_id"] == event_id for event in events),
                1,
            )

        before_reload = events_path.read_bytes()
        dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(events_path.read_bytes(), before_reload)

    def test_route_approval_records_separate_linked_audit_facts(
        self,
    ) -> None:
        repository, _ = self.make_repo("v2-route-audit")
        task = self.route_approved_task(
            repository,
            task_id="v2-route-audit",
        )
        self.assertEqual(task["status"], "ROUTE_APPROVED")
        approval = task["approvals"]["route"]
        self.assertTrue(approval["intent_id"])
        impact = next(
            artifact
            for artifact in reversed(task["artifacts"])
            if artifact["kind"] == "impact"
        )
        impact_analysis_sha = impact["metadata"][
            "impact_analysis_sha256"
        ]
        self.assertEqual(
            task["route"]["impact_analysis_sha256"],
            impact_analysis_sha,
        )
        self.assertEqual(
            approval["impact_analysis_sha256"],
            impact_analysis_sha,
        )
        intent_fingerprints = {
            task["repositories"][0]["id"]: {
                "sha256": "intent-fingerprint",
                "head_sha": "intent-head",
                "capability_profile_sha256": "intent-capabilities",
            }
        }
        original_intent = dev_flow._transition_intent_preview(
            task,
            "IMPACT_REVIEW",
            "ROUTE_APPROVED",
            action="approve-route",
            action_parameters={"gate": "route"},
            fingerprints=intent_fingerprints,
        )
        changed_impact = json.loads(json.dumps(task))
        next(
            artifact
            for artifact in reversed(changed_impact["artifacts"])
            if artifact["kind"] == "impact"
        )["metadata"]["impact_analysis_sha256"] = "f" * 64
        changed_intent = dev_flow._transition_intent_preview(
            changed_impact,
            "IMPACT_REVIEW",
            "ROUTE_APPROVED",
            action="approve-route",
            action_parameters={"gate": "route"},
            fingerprints=intent_fingerprints,
        )
        self.assertNotEqual(
            original_intent["evidence_sha256"],
            changed_intent["evidence_sha256"],
        )
        self.assertNotEqual(
            original_intent["intent_id"],
            changed_intent["intent_id"],
        )
        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / task["task_id"]
                / "events.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        facts = [
            event
            for event in events
            if event["revision"] == task["revision"]
        ]
        self.assertEqual(
            {event["type"] for event in facts},
            {"gate_approved", "state_transitioned"},
        )
        self.assertEqual(
            len({event["event_id"] for event in facts}), 2
        )
        self.assertEqual(
            len({event["transaction_id"] for event in facts}), 1
        )
        self.assertEqual(
            {event["payload"]["intent_id"] for event in facts},
            {approval["intent_id"]},
        )
        transition = next(
            event for event in facts if event["type"] == "state_transitioned"
        )
        self.assertEqual(
            transition["payload"]["approval_id"],
            approval["approval_id"],
        )

    def test_review_snapshot_only_records_a_real_state_edge(self) -> None:
        repository, _ = self.make_repo("v2-review-snapshot-events")
        task = self.start(
            repository,
            task_id="v2-review-snapshot-events",
        )["task"]
        task_dir = self.data / "tasks" / task["task_id"]
        fingerprint = {
            "sha256": "snapshot-fingerprint",
            "capability_profile_sha256": "snapshot-capabilities",
        }

        def captured_repository(
            snapshot_root: Path,
            selected_repository: dict,
            *,
            task_dir: Path,
            initial_fingerprint: dict,
        ) -> dict:
            return {
                "repository_id": selected_repository["id"],
                "working_path": selected_repository["path"],
                "fingerprint": initial_fingerprint,
                "capability_profile_sha256": (
                    initial_fingerprint["capability_profile_sha256"]
                ),
                "sections": {},
            }

        for source_status, expected_transition in (
            ("VERIFYING", True),
            ("REVIEWING", False),
        ):
            with self.subTest(source_status=source_status):
                current = json.loads(json.dumps(task))
                current["status"] = source_status
                locked = mock.MagicMock()
                locked.return_value.__enter__.return_value = (
                    task_dir,
                    current,
                )
                committed = mock.Mock()
                args = mock.Mock(
                    task_id=task["task_id"],
                    task_option=None,
                    data_dir=self.data,
                    expected_revision=current["revision"],
                    repo=[],
                )
                with (
                    mock.patch.object(
                        dev_flow,
                        "_locked_state",
                        locked,
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_require_current_workspace_indexes",
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_require_workspace_ready",
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_require_current_plan_gate",
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_fingerprint_repo",
                        return_value=fingerprint,
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_latest_passing_test_is_current",
                        return_value=(True, None),
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_write_review_repo",
                        side_effect=captured_repository,
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_review_snapshot_integrity_error",
                        return_value=None,
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_commit_state",
                        committed,
                    ),
                ):
                    response = dev_flow.command_review_snapshot(args)

                self.assertEqual(response["status"], "REVIEWING")
                additional_events = committed.call_args.kwargs[
                    "additional_events"
                ]
                if expected_transition:
                    self.assertEqual(
                        additional_events,
                        [
                            (
                                "state_transitioned",
                                {
                                    "from": "VERIFYING",
                                    "to": "REVIEWING",
                                    "action": "review-snapshot",
                                    "confirmation_mode": "automatic",
                                },
                            )
                        ],
                    )
                else:
                    self.assertIsNone(additional_events)

    def test_impact_funnel_contract_accepts_complete_and_declared_degraded(
        self,
    ) -> None:
        state = {
            "repositories": [
                {
                    "id": "repository",
                    "index": {"index_id": "index-1"},
                }
            ]
        }
        complete = self.impact_metadata()
        normalized = dev_flow._validate_impact_analysis_contract(
            state,
            complete,
        )
        self.assertEqual(
            normalized["impact_analysis_contract_version"],
            dev_flow.IMPACT_ANALYSIS_CONTRACT_VERSION,
        )
        self.assertEqual(
            normalized["impact_analysis_sha256"],
            dev_flow._sha256_bytes(dev_flow._json_bytes(complete)),
        )

        degraded = self.impact_metadata(coverage="degraded")
        degraded["repositories"][0]["checks"]["contracts"] = {
            "status": "degraded",
            "reason": "dependency index unavailable",
        }
        accepted_degraded = (
            dev_flow._validate_impact_analysis_contract(state, degraded)
        )
        self.assertEqual(accepted_degraded["coverage"], "degraded")

        missing_signal = self.impact_metadata(coverage="degraded")
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._validate_impact_analysis_contract(
                state,
                missing_signal,
            )
        self.assertEqual(
            captured.exception.code,
            "IMPACT_ANALYSIS_INVALID",
        )

        over_budget = self.impact_metadata()
        over_budget["repositories"][0]["queries"]["search_graph"] = (
            dev_flow.IMPACT_QUERY_BUDGETS["seed-v1"]["search_graph"] + 1
        )
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._validate_impact_analysis_contract(
                state,
                over_budget,
            )
        self.assertEqual(
            captured.exception.code,
            "IMPACT_ANALYSIS_INVALID",
        )
        self.assertEqual(
            captured.exception.details["query"],
            "search_graph",
        )

    def test_impact_digest_rejects_reserved_fields_and_tampering(
        self,
    ) -> None:
        state = {
            "schema_version": dev_flow.TASK_SCHEMA_VERSION,
            "confirmation_contract_version": (
                dev_flow.CONFIRMATION_CONTRACT_VERSION
            ),
            "task_id": "impact-digest",
            "impact_generation": 0,
            "repositories": [
                {
                    "id": "repository",
                    "index": {"index_id": "index-1"},
                }
            ],
        }
        for reserved_field, value in (
            ("impact_analysis_sha256", "0" * 64),
            (
                "impact_analysis_contract_version",
                dev_flow.IMPACT_ANALYSIS_CONTRACT_VERSION,
            ),
            ("artifact_id", "forged-artifact"),
            ("artifact_sha256", "1" * 64),
            ("index_provenance_sha256", "2" * 64),
            ("impact_generation", 0),
            ("controller_digest", "3" * 64),
        ):
            with self.subTest(reserved_field=reserved_field):
                metadata = self.impact_metadata()
                metadata[reserved_field] = value
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._validate_impact_analysis_contract(
                        state,
                        metadata,
                    )
                self.assertEqual(
                    captured.exception.code,
                    "IMPACT_ANALYSIS_INVALID",
                )

        normalized = dev_flow._validate_impact_analysis_contract(
            state,
            self.impact_metadata(),
        )
        stored_metadata = {
            **normalized,
            "index_provenance_sha256": "4" * 64,
            "impact_generation": 0,
        }
        current = {
            **state,
            "artifacts": [
                {
                    "artifact_id": "impact-artifact",
                    "kind": "impact",
                    "metadata": stored_metadata,
                }
            ],
        }
        with (
            mock.patch.object(
                dev_flow,
                "_assert_artifact_unchanged",
            ),
            mock.patch.object(
                dev_flow,
                "_index_provenance_sha256",
                return_value="4" * 64,
            ),
        ):
            self.assertEqual(
                dev_flow._require_current_impact(current)[
                    "artifact_id"
                ],
                "impact-artifact",
            )

            tampered = json.loads(json.dumps(current))
            tampered_metadata = tampered["artifacts"][0]["metadata"]
            tampered_metadata["coverage"] = "degraded"
            tampered_metadata["repositories"][0]["checks"][
                "contracts"
            ] = {
                "status": "degraded",
                "reason": "rewritten after recording",
            }
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._require_current_impact(tampered)
            self.assertEqual(captured.exception.code, "STALE_IMPACT")

            invalid = json.loads(json.dumps(current))
            invalid["artifacts"][0]["metadata"]["coverage"] = "unknown"
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._require_current_impact(invalid)
            self.assertEqual(
                captured.exception.code,
                "IMPACT_ANALYSIS_INVALID",
            )

    def test_impact_funnel_rejects_non_string_repository_ids(self) -> None:
        state = {
            "repositories": [
                {
                    "id": "repository",
                    "index": {"index_id": "index-1"},
                }
            ]
        }
        for invalid_repository_id in (None, "", "   ", [], {}):
            with self.subTest(repository_id=invalid_repository_id):
                metadata = self.impact_metadata()
                metadata["repositories"][0][
                    "repository_id"
                ] = invalid_repository_id
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._validate_impact_analysis_contract(
                        state,
                        metadata,
                    )
                self.assertEqual(
                    captured.exception.code,
                    "IMPACT_ANALYSIS_INVALID",
                )


if __name__ == "__main__":
    unittest.main()
