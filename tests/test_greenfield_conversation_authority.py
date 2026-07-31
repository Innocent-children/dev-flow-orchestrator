from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import runpy
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import dev_flow_orchestrator.authority as authority_module
from dev_flow_orchestrator.authority import AuthorityStore
from dev_flow_orchestrator.model import DevFlowError


class GreenfieldConversationAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "controller-data"
        self.repository_context = {
            "repositories": [
                {
                    "id": "repo-primary",
                    "path": str(self.root / "repository"),
                    "workspace": {
                        "strategy": "in-place",
                        "path": str(self.root / "repository"),
                    },
                }
            ]
        }
        self.store = AuthorityStore(self.data_root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _resolve(
        self,
        task_id: str,
        *,
        context=None,
        request_turn_id: str = "request-turn-1",
        session_id: str = "session-1",
        action_id: str = "task.implementation.complete",
    ) -> dict:
        return self.store.resolve(
            task_id=task_id,
            workflow_identity="workflow-identity-1",
            expected_revision=7,
            action_id=action_id,
            grant="implementer",
            actor_role="implementer",
            scope={"repository_id": "repo-primary"},
            context=context or {"summary": "implemented"},
            repository_context=self.repository_context,
            session_id=session_id,
            request_turn_id=request_turn_id,
        )

    def _observe(
        self,
        prompt: str,
        *,
        turn_id: str,
        eligible_task_ids,
        session_id: str = "session-1",
    ) -> dict:
        return self.store.observe_user_prompt(
            session_id=session_id,
            turn_id=turn_id,
            cwd=str(self.root / "repository"),
            prompt=prompt,
            eligible_task_ids=eligible_task_ids,
        )

    def test_request_is_deterministic_private_and_survives_restart(self) -> None:
        first = self._resolve("task-a", request_turn_id="request-turn-1")
        repeated = self._resolve("task-a", request_turn_id="request-turn-2")
        restarted = AuthorityStore(self.data_root)
        after_restart = restarted.resolve(
            task_id="task-a",
            workflow_identity="workflow-identity-1",
            expected_revision=7,
            action_id="task.implementation.complete",
            grant="implementer",
            actor_role="implementer",
            scope={"repository_id": "repo-primary"},
            context={"summary": "implemented"},
            repository_context=self.repository_context,
            session_id="session-1",
            request_turn_id="request-turn-after-restart",
        )

        self.assertEqual(first["request_id"], repeated["request_id"])
        self.assertEqual(first["request_id"], after_restart["request_id"])
        self.assertEqual(first["status"], "PENDING")
        self.assertEqual(
            after_restart["routing"]["request_turn_id"],
            "request-turn-1",
        )
        self.assertEqual(
            after_restart["binding"]["actor"]["local_account"]["uid"],
            os.getuid(),
        )
        self.assertEqual(
            stat.S_IMODE(self.data_root.stat().st_mode),
            0o700,
        )
        self.assertEqual(
            stat.S_IMODE(
                (self.data_root / "confirmations").stat().st_mode
            ),
            0o700,
        )
        self.assertEqual(
            stat.S_IMODE(
                (self.data_root / "confirmations" / "index.json").stat().st_mode
            ),
            0o600,
        )
        self.assertEqual(
            stat.S_IMODE(
                (self.data_root / "locks" / "confirmation.lock").stat().st_mode
            ),
            0o600,
        )

    def test_exact_bare_named_and_ambiguous_grammar(self) -> None:
        first = self._resolve("task-a")
        second = self._resolve("task-b")

        ambiguous = self._observe(
            "approve",
            turn_id="turn-ambiguous",
            eligible_task_ids=["task-a", "task-b"],
        )
        self.assertEqual(ambiguous["status"], "AMBIGUOUS")
        self.assertEqual(ambiguous["eligible_count"], 2)
        self.assertEqual(
            ambiguous["request_ids"],
            sorted([first["request_id"], second["request_id"]]),
        )
        self.assertEqual(self._resolve("task-a")["status"], "PENDING")
        self.assertEqual(self._resolve("task-b")["status"], "PENDING")

        ignored = self._observe(
            "approve this request please",
            turn_id="turn-prose",
            eligible_task_ids=["task-a"],
        )
        self.assertEqual(ignored["status"], "IGNORED")
        self.assertEqual(self._resolve("task-a")["status"], "PENDING")

        named = self._observe(
            "同意 " + second["request_id"],
            turn_id="turn-named",
            eligible_task_ids=["task-a", "task-b"],
        )
        self.assertEqual(named["status"], "CONFIRMED")
        self.assertEqual(named["request_id"], second["request_id"])
        self.assertEqual(self._resolve("task-a")["status"], "PENDING")
        self.assertEqual(self._resolve("task-b")["status"], "CONFIRMED")

        bare = self._observe(
            " \t同意\n",
            turn_id="turn-bare",
            eligible_task_ids=["task-a"],
        )
        self.assertEqual(bare["status"], "CONFIRMED")
        self.assertEqual(bare["request_id"], first["request_id"])

    def test_whitespace_prompt_is_invalid_and_leaves_request_pending(self) -> None:
        self._resolve("task-whitespace")
        with self.assertRaises(DevFlowError) as captured:
            self._observe(
                " \t\n",
                turn_id="turn-whitespace",
                eligible_task_ids=["task-whitespace"],
            )
        self.assertEqual(
            captured.exception.code,
            "CONFIRMATION_EVENT_INVALID",
        )
        self.assertEqual(
            self._resolve("task-whitespace")["status"],
            "PENDING",
        )

    def test_cross_task_event_replay_and_conflict_never_mutate_twice(self) -> None:
        first = self._resolve("task-a")
        second = self._resolve("task-b")
        prompt = "approve " + first["request_id"]

        decided = self._observe(
            prompt,
            turn_id="shared-turn",
            eligible_task_ids=["task-a", "task-b"],
        )
        replayed = self._observe(
            prompt,
            turn_id="shared-turn",
            eligible_task_ids=["task-b"],
        )
        conflicting = self._observe(
            "deny " + second["request_id"],
            turn_id="shared-turn",
            eligible_task_ids=["task-a", "task-b"],
        )

        self.assertEqual(decided, replayed)
        self.assertEqual(decided["status"], "CONFIRMED")
        self.assertEqual(conflicting["status"], "CONFLICT")
        self.assertEqual(
            conflicting["code"],
            "CONFIRMATION_EVENT_CONFLICT",
        )
        self.assertEqual(self._resolve("task-a")["status"], "CONFIRMED")
        self.assertEqual(self._resolve("task-b")["status"], "PENDING")
        persisted = (
            self.data_root / "confirmations" / "index.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn(prompt, persisted)
        self.assertNotIn("deny " + second["request_id"], persisted)

    def test_denial_is_terminal_for_the_exact_binding(self) -> None:
        request = self._resolve("task-denied")
        denied = self._observe(
            "拒绝 " + request["request_id"],
            turn_id="turn-deny",
            eligible_task_ids=["task-denied"],
        )
        self.assertEqual(denied["status"], "DENIED")

        restarted = AuthorityStore(self.data_root)
        self.store = restarted
        same_request = self._resolve(
            "task-denied",
            request_turn_id="new-request-turn",
        )
        self.assertEqual(same_request["request_id"], request["request_id"])
        self.assertEqual(same_request["status"], "DENIED")
        later_agreement = self._observe(
            "approve " + request["request_id"],
            turn_id="turn-after-denial",
            eligible_task_ids=["task-denied"],
        )
        self.assertEqual(later_agreement["status"], "NO_MATCH")
        self.assertEqual(self._resolve("task-denied")["status"], "DENIED")
        with self.assertRaises(DevFlowError) as captured:
            self.store.mark_claimed(
                "task-denied",
                request["request_id"],
            )
        self.assertEqual(captured.exception.code, "CONFIRMATION_DENIED")

    def test_claim_consume_stale_and_bounded_projection(self) -> None:
        claimed_request = self._resolve("task-claimed")
        self._observe(
            "approve " + claimed_request["request_id"],
            turn_id="turn-claim",
            eligible_task_ids=["task-claimed"],
        )
        claimed = self.store.mark_claimed(
            "task-claimed",
            claimed_request["request_id"],
        )
        claimed_again = self.store.mark_claimed(
            "task-claimed",
            claimed_request["request_id"],
        )
        self.assertEqual(claimed["status"], "CLAIMED")
        self.assertEqual(claimed, claimed_again)

        consumed = self.store.consume(
            "task-claimed",
            claimed_request["request_id"],
        )
        consumed_again = self.store.consume(
            "task-claimed",
            claimed_request["request_id"],
        )
        self.assertEqual(consumed["status"], "CONSUMED")
        self.assertEqual(consumed, consumed_again)
        self.assertEqual(
            AuthorityStore.public_packet(consumed)["status"],
            "CONSUMED",
        )
        projection = self.store.projection(
            task_id="task-claimed",
            workflow_identity="workflow-identity-1",
            expected_revision=7,
            action_id="task.implementation.complete",
            session_id="session-1",
            repository_context=self.repository_context,
        )
        self.assertEqual(projection["status"], "NONE")
        self.assertEqual(projection["requests"], [])
        self.assertLessEqual(
            len(
                json.dumps(
                    projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            4096,
        )

        stale_request = self._resolve("task-stale")
        stale = self.store.mark_stale(
            "task-stale",
            stale_request["request_id"],
        )
        stale_again = self.store.mark_stale(
            "task-stale",
            stale_request["request_id"],
        )
        self.assertEqual(stale["status"], "STALE")
        self.assertEqual(stale, stale_again)

    def test_terminal_records_compact_and_exact_retry_cannot_recreate(self) -> None:
        for terminal_status in ("CONSUMED", "STALE"):
            with self.subTest(status=terminal_status):
                data_root = self.root / ("compact-" + terminal_status.lower())
                self.store = AuthorityStore(data_root, request_limit=1)
                first = self._resolve("task-terminal")
                if terminal_status == "CONSUMED":
                    self._observe(
                        "approve " + first["request_id"],
                        turn_id="turn-terminal",
                        eligible_task_ids=["task-terminal"],
                    )
                    self.store.consume(
                        "task-terminal",
                        first["request_id"],
                    )
                else:
                    self.store.mark_stale(
                        "task-terminal",
                        first["request_id"],
                    )
                before = json.loads(
                    (data_root / "confirmations" / "index.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertIn(first["request_id"], before["requests"])
                self.assertEqual(before["tombstones"], {})

                self._resolve("task-new")
                compacted = json.loads(
                    (data_root / "confirmations" / "index.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertNotIn(first["request_id"], compacted["requests"])
                tombstone = compacted["tombstones"][first["request_id"]]
                self.assertEqual(
                    set(tombstone),
                    {
                        "schema",
                        "request_id",
                        "binding_digest",
                        "status",
                        "task_id",
                        "terminal_at",
                        "compacted_at",
                        "locator",
                    },
                )
                self.assertEqual(tombstone["status"], terminal_status)
                self.assertNotIn("binding", tombstone)
                self.assertNotIn("decision", tombstone)

                self.store = AuthorityStore(data_root, request_limit=1)
                exact_retry = self._resolve(
                    "task-terminal",
                    request_turn_id="retry-after-compaction",
                )
                self.assertEqual(
                    exact_retry["schema"],
                    "dev-flow-v4-confirmation-tombstone/v1",
                )
                self.assertEqual(exact_retry["status"], terminal_status)
                self.assertEqual(
                    AuthorityStore.public_packet(exact_retry)["status"],
                    terminal_status,
                )
                self.assertEqual(
                    self.store.records_for_task("task-terminal"),
                    (),
                )
                if terminal_status == "CONSUMED":
                    repeated = self.store.consume(
                        "task-terminal",
                        first["request_id"],
                    )
                else:
                    repeated = self.store.mark_stale(
                        "task-terminal",
                        first["request_id"],
                    )
                self.assertEqual(repeated, exact_retry)

    def test_live_claimed_and_denied_records_are_never_compacted(self) -> None:
        for protected_status in (
            "PENDING",
            "CONFIRMED",
            "CLAIMED",
            "DENIED",
        ):
            with self.subTest(status=protected_status):
                data_root = self.root / ("protected-" + protected_status.lower())
                self.store = AuthorityStore(data_root, request_limit=1)
                protected = self._resolve("task-protected")
                if protected_status != "PENDING":
                    verb = "deny" if protected_status == "DENIED" else "approve"
                    self._observe(
                        verb + " " + protected["request_id"],
                        turn_id="turn-protected",
                        eligible_task_ids=["task-protected"],
                    )
                if protected_status == "CLAIMED":
                    self.store.mark_claimed(
                        "task-protected",
                        protected["request_id"],
                    )
                index_path = data_root / "confirmations" / "index.json"
                before = index_path.read_bytes()
                with self.assertRaises(DevFlowError) as captured:
                    self._resolve("task-overflow")
                self.assertEqual(
                    captured.exception.code,
                    "CONFIRMATION_STORE_CAPACITY",
                )
                self.assertEqual(index_path.read_bytes(), before)
                current = json.loads(before.decode("utf-8"))
                self.assertEqual(current["tombstones"], {})
                self.assertEqual(
                    current["requests"][protected["request_id"]]["status"],
                    protected_status,
                )

    def test_tombstone_capacity_fails_closed_without_partial_compaction(
        self,
    ) -> None:
        self.store = AuthorityStore(
            self.root / "bounded-tombstones",
            request_limit=1,
        )
        first = self._resolve("task-first")
        self.store.mark_stale("task-first", first["request_id"])
        second = self._resolve("task-second")
        self.store.mark_stale("task-second", second["request_id"])
        index_path = (
            self.root
            / "bounded-tombstones"
            / "confirmations"
            / "index.json"
        )
        before = index_path.read_bytes()

        with self.assertRaises(DevFlowError) as captured:
            self._resolve("task-third")
        self.assertEqual(
            captured.exception.code,
            "CONFIRMATION_STORE_CAPACITY",
        )
        self.assertEqual(index_path.read_bytes(), before)
        current = json.loads(before.decode("utf-8"))
        self.assertEqual(
            set(current["tombstones"]),
            {first["request_id"]},
        )
        self.assertEqual(
            set(current["requests"]),
            {second["request_id"]},
        )
        self.assertEqual(
            self._resolve("task-first")["status"],
            "STALE",
        )

    def test_byte_capacity_compacts_only_a_safe_terminal_record(self) -> None:
        self.store = AuthorityStore(
            self.root / "byte-capacity",
            request_limit=4,
        )
        terminal = self._resolve("task-byte-terminal")
        self.store.mark_stale(
            "task-byte-terminal",
            terminal["request_id"],
        )
        current = self._resolve("task-byte-current")

        with self.store._confirmation_lock():
            index = self.store._load_index()
            full_size = self.store._index_size(index)
            preview = copy.deepcopy(index)
            self.store._compact_one_terminal(preview)
            compacted_size = self.store._index_size(preview)
            self.assertLess(compacted_size, full_size)
            with mock.patch.object(
                authority_module,
                "_MAX_INDEX_BYTES",
                compacted_size,
            ):
                self.store._write_index(index)

        persisted = json.loads(
            (
                self.root
                / "byte-capacity"
                / "confirmations"
                / "index.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(terminal["request_id"], persisted["tombstones"])
        self.assertIn(current["request_id"], persisted["requests"])
        self.assertEqual(
            persisted["requests"][current["request_id"]]["status"],
            "PENDING",
        )

    def test_projection_can_select_multiple_actions_in_one_snapshot(self) -> None:
        first = self._resolve(
            "task-projection-actions",
            action_id="repository.result.accept",
            context={"result": "first"},
        )
        second = self._resolve(
            "task-projection-actions",
            action_id="repository.cancel",
            context={"reason": "stop"},
        )
        self._observe(
            "approve " + first["request_id"],
            turn_id="turn-projection-actions",
            eligible_task_ids=["task-projection-actions"],
        )

        projection = self.store.projection(
            task_id="task-projection-actions",
            workflow_identity="workflow-identity-1",
            expected_revision=7,
            action_ids=[
                "repository.cancel",
                "repository.result.accept",
                "repository.cancel",
            ],
            session_id="session-1",
            repository_context=self.repository_context,
        )
        self.assertEqual(projection["status"], "MIXED")
        self.assertEqual(
            [item["request_id"] for item in projection["requests"]],
            sorted([first["request_id"], second["request_id"]]),
        )
        self.assertEqual(
            {item["action_id"] for item in projection["requests"]},
            {"repository.result.accept", "repository.cancel"},
        )
        self.assertLessEqual(
            len(
                json.dumps(
                    projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            4096,
        )
        single = self.store.projection(
            task_id="task-projection-actions",
            workflow_identity="workflow-identity-1",
            expected_revision=7,
            action_id="repository.cancel",
            session_id="session-1",
            repository_context=self.repository_context,
        )
        self.assertEqual(len(single["requests"]), 1)
        self.assertEqual(
            single["requests"][0]["request_id"],
            second["request_id"],
        )
        with self.assertRaises(DevFlowError) as captured:
            self.store.projection(
                task_id="task-projection-actions",
                workflow_identity="workflow-identity-1",
                expected_revision=7,
                action_id="repository.cancel",
                action_ids=["repository.result.accept"],
                session_id="session-1",
                repository_context=self.repository_context,
            )
        self.assertEqual(captured.exception.code, "CONFIRMATION_INVALID")

    def test_complete_current_source_closure_has_no_popup_authority(
        self,
    ) -> None:
        namespace = runpy.run_path(
            str(ROOT / "scripts" / "validate_package.py"),
            run_name="popup_source_closure_probe",
        )
        audit = namespace["validate_popup_source_closure"](ROOT)
        self.assertEqual(audit["violations"], [])
        self.assertTrue(
            {
                ".codex-plugin/plugin.json",
                "ARCHITECTURE.md",
                "hooks/dev_flow_hook.py",
                "scripts/validate_package.py",
                "skills/follow-dev-flow/SKILL.md",
                "src/dev_flow_orchestrator/authority.py",
                "tests/test_greenfield_conversation_authority.py",
            }.issubset(set(audit["files"]))
        )

        fixture_root = self.root / "closure-fixture"
        fixture_source = fixture_root / "src"
        fixture_source.mkdir(parents=True)
        samples = {
            "approval-port": (
                "class MacOS" + "Approval" + "Port: pass\n"
            ),
            "apple-script-executable": (
                "/usr/bin/" + "osa" + "script\n"
            ),
            "dialog-channel-schema": "macos-system-" + "dialog/v1\n",
            "dialog-script": "display " + "dialog\n",
            "dialog-title": "Dev Flow " + "Authority\n",
            "dialog-timeout": "timeout = " + "120\n",
            "graphical-host-prerequisite": (
                "graphical macOS " + "session\n"
            ),
            "macos-dialog-product-reference": (
                "macOS system " + "dialog\n"
            ),
            "popup-error-contract": "HOST_" + "APPROVAL_DENIED\n",
        }
        for index, sample in enumerate(samples.values()):
            (fixture_source / "probe-{}.txt".format(index)).write_text(
                sample,
                encoding="utf-8",
            )
        fixture_audit = namespace["validate_popup_source_closure"](
            fixture_root
        )
        self.assertEqual(
            {item["signature"] for item in fixture_audit["violations"]},
            set(samples),
        )


if __name__ == "__main__":
    unittest.main()
