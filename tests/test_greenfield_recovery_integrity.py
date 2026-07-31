from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator.authority import AuthorityStore
from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.git_client import GitClient
from dev_flow_orchestrator.model import DevFlowError
from tests.greenfield_authority import ConversationAuthority


def _workspace_receipt(request: dict) -> dict:
    return {
        "schema": "dev-flow-v4-workspace-receipt/v1",
        "strategy": request["strategy"],
        "path": request["destination"],
        "head": request["expected_head"],
        "branch": None,
    }


class MutableRecoveryEvidenceGit(GitClient):
    """Create an uncertain placement with operator-controlled later proof."""

    def __init__(self) -> None:
        self.dispatch_count = 0
        self.observation_count = 0
        self.settlement_provable = True
        self.absence_provable = True
        self.observed_branch = None

    def prepare_workspace(
        self,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        self.dispatch_count += 1
        raise DevFlowError(
            "INJECTED_UNCERTAIN_EFFECT",
            "the focused test deliberately loses the effect response",
        )

    def observe_workspace(self, request: dict) -> dict:
        self.observation_count += 1
        if not self.settlement_provable:
            raise DevFlowError(
                "EFFECT_OBSERVATION_MISMATCH",
                "the current workspace no longer proves settlement",
            )
        receipt = _workspace_receipt(request)
        receipt["branch"] = self.observed_branch
        return receipt

    def workspace_effect_absent(self, request: dict) -> bool:
        return self.absence_provable


class SuccessfulLostResponseGit(GitClient):
    """Return one placement receipt; recovery observation must be unnecessary."""

    def __init__(self) -> None:
        self.dispatch_count = 0
        self.observation_count = 0

    def prepare_workspace(
        self,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        self.dispatch_count += 1
        return {
            "schema": "dev-flow-v4-workspace-receipt/v1",
            "strategy": strategy,
            "path": str(destination),
            "head": expected_head,
            "branch": None,
        }

    def observe_workspace(self, request: dict) -> dict:
        self.observation_count += 1
        raise DevFlowError(
            "INJECTED_UNNECESSARY_OBSERVATION",
            "terminal lost-response recovery must not consult live evidence",
        )


class BlockingLiveWorkspaceGit(GitClient):
    """Expose absence until one blocked dispatch produces the live effect."""

    def __init__(self) -> None:
        self.dispatch_count = 0
        self.absence_checks = 0
        self.effect_present = False
        self.dispatch_entered = threading.Event()
        self.release_dispatch = threading.Event()
        self.second_absence_checked = threading.Event()
        self._lock = threading.Lock()

    def prepare_workspace(
        self,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        with self._lock:
            self.dispatch_count += 1
        self.dispatch_entered.set()
        if not self.release_dispatch.wait(timeout=10):
            raise DevFlowError(
                "TEST_DISPATCH_TIMEOUT",
                "the focused test did not release the live dispatch",
            )
        with self._lock:
            self.effect_present = True
        return {
            "schema": "dev-flow-v4-workspace-receipt/v1",
            "strategy": strategy,
            "path": str(destination),
            "head": expected_head,
            "branch": None,
        }

    def workspace_effect_absent(self, request: dict) -> bool:
        with self._lock:
            self.absence_checks += 1
            if self.absence_checks >= 2:
                self.second_absence_checked.set()
            return not self.effect_present


class GreenfieldRecoveryIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(self.repository)],
            check=True,
        )
        (self.repository / "README.md").write_text(
            "recovery integrity\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "add", "README.md"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "-c",
                "user.name=Greenfield Test",
                "-c",
                "user.email=greenfield@example.invalid",
                "commit",
                "-q",
                "-m",
                "initial",
            ],
            check=True,
        )
        self.data_dir = self.root / "data"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _conversation(
        self,
        controller: Controller,
        session_id: str,
    ) -> ConversationAuthority:
        return ConversationAuthority(
            controller,
            self.repository,
            session_id=session_id,
        )

    def _at_workspace(self, controller: Controller, task_id: str) -> None:
        controller.start(
            requirement="recovery integrity",
            workflow="full",
            workspace_strategy="worktree",
            repositories=[str(self.repository)],
            task_id=task_id,
        )
        controller.preflight(task_id, 0)
        controller.apply(
            task_id,
            1,
            "evidence.baseline.record",
            {"baseline": "head"},
        )
        controller.apply(
            task_id,
            2,
            "evidence.impact.record",
            {"impact": "bounded"},
        )
        controller.apply(
            task_id,
            3,
            "task.route.set",
            {"route": "worktree", "reason": "isolated"},
        )

    def _uncertain_effect(
        self,
        task_id: str,
        *,
        session_id: str,
        request_limit: int | None = None,
    ) -> tuple[Controller, MutableRecoveryEvidenceGit, dict]:
        git = MutableRecoveryEvidenceGit()
        controller = Controller(str(self.data_dir), git_client=git)
        if request_limit is not None:
            controller.authorities = AuthorityStore(
                controller.store.root,
                request_limit=request_limit,
            )
        self._at_workspace(controller, task_id)
        authority = self._conversation(controller, session_id)
        with self.assertRaises(DevFlowError) as captured:
            authority.apply(
                task_id,
                4,
                "workspace.prepare",
                {},
            )
        self.assertEqual(captured.exception.code, "EFFECT_UNCERTAIN")
        execution = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(execution["phase"], "QUARANTINED")
        self.assertEqual(git.dispatch_count, 1)
        return controller, git, execution

    def _abandoned_with_compacted_confirmation(
        self,
        label: str,
    ) -> tuple[Controller, str, object, set[str]]:
        self.data_dir = self.root / ("data-" + label)
        task_id = "terminal-compaction-" + label
        controller, _, execution = self._uncertain_effect(
            task_id,
            session_id="original-" + label,
            request_limit=2,
        )
        recovery_authority = self._conversation(
            controller,
            "recovery-" + label,
        )
        recovery = recovery_authority.recover(
            task_id,
            execution["plan_binding"],
            "abandon",
        )
        self.assertEqual(recovery["outcome"], "ABANDONED")
        terminal_records = controller.authorities.records_for_task(task_id)
        self.assertEqual(len(terminal_records), 2)
        self.assertEqual(
            {record["status"] for record in terminal_records},
            {"CONSUMED"},
        )
        terminal_ids = {
            record["request_id"] for record in terminal_records
        }

        next_authority = self._conversation(
            controller,
            "next-attempt-" + label,
        )
        pending = next_authority.request_action(
            task_id,
            4,
            "workspace.prepare",
            {},
        )
        index = json.loads(
            controller.authorities.index_path.read_text(encoding="utf-8")
        )
        self.assertEqual(len(index["tombstones"]), 1)
        self.assertTrue(
            set(index["tombstones"]).issubset(terminal_ids)
        )
        return controller, task_id, pending, terminal_ids

    def test_terminal_tombstone_proves_abandoned_effect_without_authority(
        self,
    ) -> None:
        controller, task_id, pending, terminal_ids = (
            self._abandoned_with_compacted_confirmation("valid")
        )

        projection = controller.next(
            task_id,
            session_id=pending.session_id,
        )

        self.assertEqual(
            projection["confirmation"]["status"],
            "PENDING",
        )
        self.assertEqual(
            [
                record["request_id"]
                for record in projection["confirmation"]["requests"]
            ],
            [pending.request_id],
        )
        live_records = controller.authorities.records_for_task(task_id)
        self.assertNotIn(
            "dev-flow-v4-confirmation-tombstone/v1",
            {record["schema"] for record in live_records},
        )
        evidence = controller.authorities.evidence_for_task(task_id)
        tombstones = [
            record
            for record in evidence
            if record["schema"]
            == "dev-flow-v4-confirmation-tombstone/v1"
        ]
        self.assertEqual(len(tombstones), 1)
        self.assertIn(tombstones[0]["request_id"], terminal_ids)
        self.assertEqual(tombstones[0]["status"], "CONSUMED")

    def test_tampered_terminal_tombstone_fails_closed(self) -> None:
        cases = (
            (
                "binding-digest",
                lambda tombstone: tombstone.__setitem__(
                    "binding_digest",
                    "0" * 64,
                ),
            ),
            (
                "scope-locator",
                lambda tombstone: tombstone["locator"].__setitem__(
                    "scope_digest",
                    "0" * 64,
                ),
            ),
        )
        for label, tamper in cases:
            with self.subTest(field=label):
                controller, task_id, _, _ = (
                    self._abandoned_with_compacted_confirmation(label)
                )
                index_path = controller.authorities.index_path
                index = json.loads(
                    index_path.read_text(encoding="utf-8")
                )
                tombstone = next(iter(index["tombstones"].values()))
                tamper(tombstone)
                index_path.write_text(
                    json.dumps(
                        index,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n",
                    encoding="utf-8",
                )

                with self.assertRaises(DevFlowError) as captured:
                    controller.next(task_id)

                self.assertEqual(
                    captured.exception.code,
                    "EFFECT_JOURNAL_INVALID",
                )

    @staticmethod
    def _raw_journal_record(
        controller: Controller,
        task_id: str,
        binding: str,
    ) -> dict:
        path = controller.journal._path(task_id, binding)
        return json.loads(path.read_text(encoding="utf-8"))

    def test_tampered_recovery_journal_fails_before_request_creation(
        self,
    ) -> None:
        def tamper_schema(record: dict) -> None:
            record["schema"] = "dev-flow-v4-effect-journal/tampered"

        def tamper_plan_binding(record: dict) -> None:
            record["plan_binding"] = "f" * 64

        def tamper_payload(record: dict) -> None:
            record["payload"] = {"undeclared": True}

        def tamper_requests(record: dict) -> None:
            request = next(iter(record["requests"].values()))
            request["expected_head"] = "0" * 40

        def tamper_original_authority(record: dict) -> None:
            record["authority_id"] = "confirm-" + ("0" * 64)

        cases = (
            ("schema", tamper_schema),
            ("plan-binding", tamper_plan_binding),
            ("payload", tamper_payload),
            ("requests", tamper_requests),
            ("original-authority", tamper_original_authority),
        )
        for index, (label, tamper) in enumerate(cases):
            with self.subTest(field=label):
                self.data_dir = self.root / "data-tamper-{}".format(index)
                task_id = "recovery-tamper-{}".format(index)
                controller, _, execution = self._uncertain_effect(
                    task_id,
                    session_id="tamper-session-{}".format(index),
                )
                binding = execution["plan_binding"]
                path = controller.journal._path(task_id, binding)
                tampered = self._raw_journal_record(
                    controller,
                    task_id,
                    binding,
                )
                tamper(tampered)
                controller.journal._write(path, tampered)
                request_ids_before = {
                    item["request_id"]
                    for item in controller.authorities.records_for_task(
                        task_id
                    )
                }

                with self.assertRaises(DevFlowError) as captured:
                    controller.recover_effect(
                        task_id,
                        binding,
                        "settle",
                        session_id="tamper-session-{}".format(index),
                        request_turn_id="request-recovery",
                    )

                self.assertEqual(
                    captured.exception.code,
                    "EFFECT_JOURNAL_INVALID",
                )
                self.assertEqual(controller.show(task_id).revision, 4)
                self.assertEqual(
                    {
                        item["request_id"]
                        for item in controller.authorities.records_for_task(
                            task_id
                        )
                    },
                    request_ids_before,
                )
                self.assertEqual(
                    self._raw_journal_record(
                        controller,
                        task_id,
                        binding,
                    ),
                    tampered,
                )

    def test_tampered_terminal_phase_cannot_consume_unrelated_request(
        self,
    ) -> None:
        task_id = "reconciliation-authority-tamper"
        controller, _, execution = self._uncertain_effect(
            task_id,
            session_id="original-effect-session",
        )
        state = controller.show(task_id)
        unrelated = controller.authorities.resolve(
            task_id=task_id,
            workflow_identity=state.workflow_identity,
            expected_revision=state.revision,
            action_id="workspace.prepare",
            grant="workspace-mutation",
            actor_role="operator",
            actor_id=None,
            scope={"unrelated": True},
            context={"unrelated": True},
            repository_context=controller._repository_context(state),
            session_id="unrelated-session",
            request_turn_id="unrelated-request",
        )
        controller.observe_user_prompt(
            session_id="unrelated-session",
            turn_id="unrelated-decision",
            cwd=str(self.repository),
            prompt="approve " + unrelated["request_id"],
        )
        binding = execution["plan_binding"]
        path = controller.journal._path(task_id, binding)
        tampered = self._raw_journal_record(
            controller,
            task_id,
            binding,
        )
        tampered.update(
            phase="COMMITTED",
            authority_id=unrelated["request_id"],
            receipt={},
            error=None,
            committed_revision=tampered["expected_revision"] + 1,
        )
        controller.journal._write(path, tampered)

        with self.assertRaises(DevFlowError) as captured:
            controller.next(task_id, session_id="unrelated-session")

        self.assertEqual(captured.exception.code, "EFFECT_JOURNAL_INVALID")
        records = {
            item["request_id"]: item
            for item in controller.authorities.records_for_task(task_id)
        }
        self.assertEqual(
            records[unrelated["request_id"]]["status"],
            "CONFIRMED",
        )
        self.assertEqual(controller.show(task_id).revision, 4)

    def test_valid_recovery_proof_drift_stales_all_unclaimed_requests(
        self,
    ) -> None:
        task_id = "valid-proof-drift"
        controller, git, execution = self._uncertain_effect(
            task_id,
            session_id="original-effect-session",
        )
        binding = execution["plan_binding"]
        pending_authority = self._conversation(
            controller,
            "old-pending-proof-session",
        )
        confirmed_authority = self._conversation(
            controller,
            "old-confirmed-proof-session",
        )
        pending = pending_authority.request_recovery(
            task_id,
            binding,
            "settle",
        )
        confirmed = confirmed_authority.request_recovery(
            task_id,
            binding,
            "settle",
        )
        confirmed_authority.decide(confirmed, approve=True)

        git.observed_branch = "refs/heads/changed-proof"
        current_authority = self._conversation(
            controller,
            "current-proof-session",
        )
        current = current_authority.request_recovery(
            task_id,
            binding,
            "settle",
        )

        self.assertNotEqual(current.request_id, pending.request_id)
        self.assertNotEqual(current.request_id, confirmed.request_id)
        records = {
            item["request_id"]: item
            for item in controller.authorities.records_for_task(task_id)
        }
        self.assertEqual(records[pending.request_id]["status"], "STALE")
        self.assertEqual(records[confirmed.request_id]["status"], "STALE")
        self.assertEqual(records[current.request_id]["status"], "PENDING")
        self.assertEqual(controller.show(task_id).revision, 4)
        self.assertIsNone(
            controller.effect_inspect(task_id)["executions"][0][
                "recovery_claim"
            ]
        )

    def test_apply_retry_revalidates_abandoned_journal_binding(self) -> None:
        task_id = "apply-retry-journal-tamper"
        controller, _, execution = self._uncertain_effect(
            task_id,
            session_id="original-effect-session",
        )
        recovery = self._conversation(
            controller,
            "abandon-recovery-session",
        )
        result = recovery.recover(
            task_id,
            execution["plan_binding"],
            "abandon",
        )
        self.assertEqual(result["outcome"], "ABANDONED")
        binding = execution["plan_binding"]
        path = controller.journal._path(task_id, binding)
        tampered = self._raw_journal_record(
            controller,
            task_id,
            binding,
        )
        tampered["authority_id"] = "confirm-" + ("0" * 64)
        controller.journal._write(path, tampered)
        request_ids_before = {
            item["request_id"]
            for item in controller.authorities.records_for_task(task_id)
        }
        controller._reconcile_confirmations = lambda state: None

        with self.assertRaises(DevFlowError) as captured:
            controller.apply(
                task_id,
                4,
                "workspace.prepare",
                {},
                session_id="retry-session",
                request_turn_id="retry-request",
            )

        self.assertEqual(captured.exception.code, "EFFECT_JOURNAL_INVALID")
        self.assertEqual(controller.show(task_id).revision, 4)
        self.assertEqual(
            {
                item["request_id"]
                for item in controller.authorities.records_for_task(task_id)
            },
            request_ids_before,
        )

    def test_terminal_recovery_revalidates_journal_binding(self) -> None:
        task_id = "terminal-recovery-journal-tamper"
        git = SuccessfulLostResponseGit()
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, task_id)
        authority = self._conversation(
            controller,
            "terminal-effect-session",
        )
        authority.apply(
            task_id,
            4,
            "workspace.prepare",
            {},
        )
        execution = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(execution["phase"], "COMMITTED")
        binding = execution["plan_binding"]
        path = controller.journal._path(task_id, binding)
        tampered = self._raw_journal_record(
            controller,
            task_id,
            binding,
        )
        tampered["authority_id"] = "confirm-" + ("0" * 64)
        controller.journal._write(path, tampered)
        controller._reconcile_confirmations = lambda state: None

        with self.assertRaises(DevFlowError) as captured:
            controller.recover_effect(
                task_id,
                binding,
                "settle",
                session_id="terminal-effect-session",
                request_turn_id="terminal-recovery",
            )

        self.assertEqual(captured.exception.code, "EFFECT_JOURNAL_INVALID")
        self.assertEqual(controller.show(task_id).revision, 5)

    def test_unprovable_settlement_needs_operator_without_new_request(
        self,
    ) -> None:
        task_id = "settlement-unprovable"
        controller, git, execution = self._uncertain_effect(
            task_id,
            session_id="settlement-unprovable-session",
        )
        git.settlement_provable = False
        request_ids_before = {
            item["request_id"]
            for item in controller.authorities.records_for_task(task_id)
        }

        result = controller.recover_effect(
            task_id,
            execution["plan_binding"],
            "settle",
            session_id="settlement-unprovable-session",
            request_turn_id="request-recovery",
        )

        self.assertEqual(
            result["schema"],
            "dev-flow-v4-operator-intervention/v1",
        )
        self.assertEqual(result["reason"], "EFFECT_SETTLEMENT_UNPROVEN")
        self.assertTrue(result["required"])
        self.assertFalse(result["automatic_redispatch"])
        self.assertFalse(result["automatic_unblock"])
        self.assertFalse(result["caller_assertion_can_unblock"])
        self.assertEqual(
            {
                item["request_id"]
                for item in controller.authorities.records_for_task(task_id)
            },
            request_ids_before,
        )
        self.assertEqual(controller.show(task_id).revision, 4)
        final = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(final["phase"], "QUARANTINED")
        self.assertIsNone(final["recovery_claim"])

    def test_lost_response_reconciliation_reloads_committed_terminal_state(
        self,
    ) -> None:
        task_id = "lost-response"
        git = SuccessfulLostResponseGit()
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, task_id)
        authority = self._conversation(
            controller,
            "lost-response-session",
        )
        original_mark_committed = controller.journal.mark_committed

        def fail_mark_committed(*args, **kwargs):
            raise DevFlowError(
                "INJECTED_JOURNAL_COMMIT_FAILURE",
                "task commit completed before journal settlement",
            )

        controller.journal.mark_committed = fail_mark_committed
        try:
            with self.assertRaises(DevFlowError) as captured:
                authority.apply(
                    task_id,
                    4,
                    "workspace.prepare",
                    {},
                )
        finally:
            controller.journal.mark_committed = original_mark_committed

        self.assertEqual(
            captured.exception.code,
            "INJECTED_JOURNAL_COMMIT_FAILURE",
        )
        self.assertEqual(controller.show(task_id).revision, 5)
        execution = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(execution["phase"], "RECEIPT")
        request_ids_before = {
            item["request_id"]
            for item in controller.authorities.records_for_task(task_id)
        }

        result = controller.recover_effect(
            task_id,
            execution["plan_binding"],
            "settle",
            session_id=authority.session_id,
            request_turn_id="recover-lost-response",
        )

        self.assertEqual(result["outcome"], "SETTLED")
        self.assertEqual(result["committed_revision"], 5)
        self.assertTrue(result["already_terminal"])
        self.assertEqual(git.dispatch_count, 1)
        self.assertEqual(git.observation_count, 0)
        self.assertEqual(
            {
                item["request_id"]
                for item in controller.authorities.records_for_task(task_id)
            },
            request_ids_before,
        )
        terminal = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(terminal["phase"], "COMMITTED")
        self.assertEqual(terminal["committed_revision"], 5)

    def test_other_session_cannot_replace_existing_recovery_claim(
        self,
    ) -> None:
        task_id = "cross-session-recovery-claim"
        controller, _, execution = self._uncertain_effect(
            task_id,
            session_id="original-action-session",
        )
        binding = execution["plan_binding"]
        session_a = self._conversation(controller, "recovery-session-a")
        pending_a = session_a.request_recovery(
            task_id,
            binding,
            "settle",
        )
        session_a.decide(pending_a, approve=True)
        pending_record = next(
            item
            for item in controller.authorities.records_for_task(task_id)
            if item["request_id"] == pending_a.request_id
        )
        controller.journal.claim_recovery(
            task_id=task_id,
            binding=binding,
            request_id=pending_a.request_id,
            binding_digest=pending_record["binding_digest"],
            mode="settle",
            effect_attempt=execution["attempt"],
            evidence_digest=pending_record["binding"]["scope"][
                "evidence_digest"
            ],
            timestamp="2026-07-31T00:00:00Z",
        )
        controller.authorities.mark_claimed(
            task_id,
            pending_a.request_id,
        )
        request_ids_before = {
            item["request_id"]
            for item in controller.authorities.records_for_task(task_id)
        }

        with self.assertRaises(DevFlowError) as captured:
            controller.recover_effect(
                task_id,
                binding,
                "settle",
                session_id="recovery-session-b",
                request_turn_id="request-from-session-b",
            )

        self.assertEqual(
            captured.exception.code,
            "EFFECT_RECOVERY_ALREADY_CLAIMED",
        )
        self.assertEqual(
            {
                item["request_id"]
                for item in controller.authorities.records_for_task(task_id)
            },
            request_ids_before,
        )
        final = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(final["phase"], "QUARANTINED")
        self.assertEqual(
            final["recovery_claim"]["request_id"],
            pending_a.request_id,
        )
        self.assertEqual(
            final["recovery_claim"]["effect_attempt"],
            execution["attempt"],
        )
        self.assertEqual(controller.show(task_id).revision, 4)

    def test_settlement_proof_change_after_confirmation_is_not_terminal(
        self,
    ) -> None:
        task_id = "settlement-proof-change"
        controller, git, execution = self._uncertain_effect(
            task_id,
            session_id="original-proof-session",
        )
        authority = self._conversation(
            controller,
            "recovery-proof-session",
        )
        pending = authority.request_recovery(
            task_id,
            execution["plan_binding"],
            "settle",
        )
        authority.decide(pending, approve=True)
        requests_before = len(
            controller.authorities.records_for_task(task_id)
        )
        git.settlement_provable = False

        result = authority.retry_recovery(pending)

        self.assertEqual(
            result["schema"],
            "dev-flow-v4-operator-intervention/v1",
        )
        self.assertEqual(
            result["reason"],
            "EFFECT_RECOVERY_EVIDENCE_CHANGED",
        )
        self.assertTrue(result["required"])
        self.assertFalse(result["automatic_redispatch"])
        self.assertFalse(result["automatic_unblock"])
        self.assertEqual(controller.show(task_id).revision, 4)
        final = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(final["phase"], "QUARANTINED")
        self.assertIsNone(final["receipt"])
        self.assertIsNone(final["recovery_claim"])
        records = controller.authorities.records_for_task(task_id)
        self.assertEqual(len(records), requests_before)
        recovery_record = next(
            item
            for item in records
            if item["request_id"] == pending.request_id
        )
        self.assertEqual(recovery_record["status"], "STALE")

    def test_live_dispatch_fence_serializes_terminal_settlement(self) -> None:
        task_id = "dispatch-abandon-fence"
        git = BlockingLiveWorkspaceGit()
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, task_id)
        action_authority = self._conversation(
            controller,
            "live-dispatch-session",
        )
        pending_action = action_authority.request_action(
            task_id,
            4,
            "workspace.prepare",
            {},
        )
        action_authority.decide(pending_action, approve=True)

        original_mark_committed = controller.journal.mark_committed
        settlement_entered = threading.Event()
        allow_settlement = threading.Event()

        def block_journal_commit(*args, **kwargs) -> dict:
            settlement_entered.set()
            if not allow_settlement.wait(timeout=10):
                raise DevFlowError(
                    "TEST_SETTLEMENT_TIMEOUT",
                    "the focused test did not release journal settlement",
                )
            return original_mark_committed(*args, **kwargs)

        controller.journal.mark_committed = block_journal_commit
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                apply_future = executor.submit(
                    action_authority.retry_action,
                    pending_action,
                )
                self.assertTrue(git.dispatch_entered.wait(timeout=10))
                execution = controller.effect_inspect(task_id)["executions"][0]
                self.assertEqual(execution["phase"], "CLAIMED")
                binding = execution["plan_binding"]

                recovery_authority = self._conversation(
                    controller,
                    "racing-abandon-session",
                )
                pending_recovery = recovery_authority.request_recovery(
                    task_id,
                    binding,
                    "abandon",
                )
                recovery_authority.decide(pending_recovery, approve=True)
                recovery_future = executor.submit(
                    recovery_authority.retry_recovery,
                    pending_recovery,
                )
                self.assertTrue(git.second_absence_checked.wait(timeout=10))

                git.release_dispatch.set()
                self.assertTrue(settlement_entered.wait(timeout=10))
                self.assertFalse(recovery_future.done())
                allow_settlement.set()
                applied = apply_future.result(timeout=10)
                recovery = recovery_future.result(timeout=10)
        finally:
            allow_settlement.set()
            controller.journal.mark_committed = original_mark_committed

        self.assertEqual(
            recovery["schema"],
            "dev-flow-v4-effect-recovery-result/v1",
        )
        self.assertEqual(recovery["outcome"], "SETTLED")
        self.assertTrue(recovery["already_terminal"])
        self.assertEqual(recovery["committed_revision"], 5)
        recovery_record = next(
            item
            for item in controller.authorities.records_for_task(task_id)
            if item["request_id"] == pending_recovery.request_id
        )
        self.assertEqual(recovery_record["status"], "STALE")
        self.assertEqual(applied.committed_revision, 5)
        self.assertEqual(git.dispatch_count, 1)
        self.assertTrue(git.effect_present)
        final = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(final["phase"], "COMMITTED")
        self.assertNotEqual(final["phase"], "ABANDONED")
        self.assertIsNone(final["recovery_claim"])
        self.assertEqual(controller.show(task_id).revision, 5)

    def test_reverse_order_settlement_fence_blocks_apply_retry(self) -> None:
        task_id = "reverse-order-settlement-fence"
        controller, git, execution = self._uncertain_effect(
            task_id,
            session_id="original-effect-session",
        )
        binding = execution["plan_binding"]
        recovery_authority = self._conversation(
            controller,
            "settlement-owner-session",
        )
        pending_recovery = recovery_authority.request_recovery(
            task_id,
            binding,
            "settle",
        )
        recovery_authority.decide(pending_recovery, approve=True)

        original_update = controller.store.update
        original_mark_committed = controller.journal.mark_committed
        before_task_cas = threading.Event()
        allow_task_cas = threading.Event()
        after_task_cas = threading.Event()
        allow_journal_commit = threading.Event()
        recovery_thread_id = {}

        def block_recovery_task_cas(*args, **kwargs):
            if threading.get_ident() == recovery_thread_id.get("value"):
                before_task_cas.set()
                if not allow_task_cas.wait(timeout=10):
                    raise DevFlowError(
                        "TEST_TASK_CAS_TIMEOUT",
                        "the focused test did not release recovery task CAS",
                    )
            return original_update(*args, **kwargs)

        def block_recovery_journal_commit(*args, **kwargs):
            if threading.get_ident() == recovery_thread_id.get("value"):
                after_task_cas.set()
                if not allow_journal_commit.wait(timeout=10):
                    raise DevFlowError(
                        "TEST_JOURNAL_COMMIT_TIMEOUT",
                        "the focused test did not release recovery journal commit",
                    )
            return original_mark_committed(*args, **kwargs)

        def settle():
            recovery_thread_id["value"] = threading.get_ident()
            return recovery_authority.retry_recovery(pending_recovery)

        def ordinary_retry():
            try:
                controller.apply(
                    task_id,
                    4,
                    "workspace.prepare",
                    {},
                    session_id="ordinary-retry-session",
                    request_turn_id="ordinary-retry",
                )
            except DevFlowError as exc:
                return exc
            raise AssertionError("ordinary retry unexpectedly applied")

        controller.store.update = block_recovery_task_cas
        controller.journal.mark_committed = block_recovery_journal_commit
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                recovery_future = executor.submit(settle)
                self.assertTrue(before_task_cas.wait(timeout=10))
                ordinary_future = executor.submit(ordinary_retry)
                self.assertFalse(ordinary_future.done())

                allow_task_cas.set()
                self.assertTrue(after_task_cas.wait(timeout=10))
                self.assertEqual(controller.show(task_id).revision, 5)
                self.assertEqual(
                    controller.effect_inspect(task_id)["executions"][0][
                        "phase"
                    ],
                    "RECEIPT",
                )
                self.assertFalse(ordinary_future.done())

                allow_journal_commit.set()
                recovery = recovery_future.result(timeout=10)
                ordinary_error = ordinary_future.result(timeout=10)
        finally:
            allow_task_cas.set()
            allow_journal_commit.set()
            controller.store.update = original_update
            controller.journal.mark_committed = original_mark_committed

        self.assertEqual(recovery["outcome"], "SETTLED")
        self.assertEqual(ordinary_error.code, "EFFECT_ALREADY_CLAIMED")
        self.assertEqual(git.dispatch_count, 1)
        final = controller.effect_inspect(task_id)["executions"][0]
        self.assertEqual(final["phase"], "COMMITTED")
        self.assertEqual(final["committed_revision"], 5)
        self.assertIsNone(final["error"])
        self.assertEqual(controller.show(task_id).revision, 5)


if __name__ == "__main__":
    unittest.main()
