from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


# AuthorityStore currently has no public pruning API.  Retention deletion is
# intentionally reported as a product gap instead of being simulated here by
# deleting or rewriting its private index.


def _workspace_receipt(
    repository_path: str,
    strategy: str,
    destination: Path,
    expected_head: object,
) -> dict:
    return {
        "schema": "dev-flow-v4-workspace-receipt/v1",
        "strategy": strategy,
        "path": str(destination),
        "head": expected_head,
        "branch": None,
    }


class SuccessfulWorkspaceGit(GitClient):
    def __init__(self) -> None:
        self.dispatch_count = 0
        self._dispatch_lock = threading.Lock()

    def prepare_workspace(
        self,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        with self._dispatch_lock:
            self.dispatch_count += 1
        return _workspace_receipt(
            repository_path,
            strategy,
            destination,
            expected_head,
        )


class BlockingWorkspaceGit(SuccessfulWorkspaceGit):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def prepare_workspace(
        self,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        with self._dispatch_lock:
            self.dispatch_count += 1
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise DevFlowError(
                "TEST_DISPATCH_TIMEOUT",
                "the focused race test did not release the Git dispatch",
            )
        return _workspace_receipt(
            repository_path,
            strategy,
            destination,
            expected_head,
        )


class AbsentUncertainWorkspaceGit(SuccessfulWorkspaceGit):
    def prepare_workspace(
        self,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        with self._dispatch_lock:
            self.dispatch_count += 1
        raise DevFlowError(
            "INJECTED_UNCERTAIN_EFFECT",
            "the test effect outcome is deliberately uncertain",
        )

    def workspace_effect_absent(self, request: dict) -> bool:
        return True


class AuthorityStoreRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "data"
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.repository_context = {
            "topology": "single-repository",
            "workspace_strategy": "in-place",
            "repositories": [
                {
                    "repository_id": "repo-primary",
                    "path": str(self.repository),
                    "workspace_path": None,
                }
            ],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _resolve(
        self,
        store: AuthorityStore,
        task_id: str,
        *,
        session_id: str = "race-session",
        request_turn_id: str = "request-turn",
    ) -> dict:
        return store.resolve(
            task_id=task_id,
            workflow_identity="workflow-identity",
            expected_revision=7,
            action_id="task.implementation.complete",
            grant="implementer",
            actor_role="implementer",
            scope={},
            context={"summary": "implemented"},
            repository_context=self.repository_context,
            session_id=session_id,
            request_turn_id=request_turn_id,
        )

    def test_concurrent_identical_first_request_creates_one_record(self) -> None:
        gate = threading.Barrier(8)

        def resolve(index: int) -> dict:
            store = AuthorityStore(self.data_root)
            gate.wait(timeout=10)
            return self._resolve(
                store,
                "task-identical",
                request_turn_id="request-turn-{}".format(index),
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            records = list(executor.map(resolve, range(8)))

        request_ids = {record["request_id"] for record in records}
        self.assertEqual(len(request_ids), 1)
        self.assertTrue(all(record == records[0] for record in records))
        persisted = AuthorityStore(self.data_root).records_for_task(
            "task-identical"
        )
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0], records[0])
        self.assertEqual(persisted[0]["status"], "PENDING")

    def test_concurrent_approve_and_deny_decide_pending_request_once(
        self,
    ) -> None:
        store = AuthorityStore(self.data_root)
        request = self._resolve(store, "task-decision")
        gate = threading.Barrier(2)

        def decide(verb: str, turn_id: str) -> dict:
            independent = AuthorityStore(self.data_root)
            gate.wait(timeout=10)
            return independent.observe_user_prompt(
                session_id="race-session",
                turn_id=turn_id,
                cwd=str(self.repository),
                prompt="{} {}".format(verb, request["request_id"]),
                eligible_task_ids=["task-decision"],
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            approve = executor.submit(decide, "approve", "turn-approve")
            deny = executor.submit(decide, "deny", "turn-deny")
            results = [approve.result(), deny.result()]

        decided = [
            result
            for result in results
            if result["status"] in {"CONFIRMED", "DENIED"}
        ]
        rejected = [
            result for result in results if result["status"] == "NO_MATCH"
        ]
        self.assertEqual(len(decided), 1)
        self.assertEqual(len(rejected), 1)
        final = store.records_for_task("task-decision")
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["status"], decided[0]["status"])
        self.assertEqual(decided[0]["request_id"], request["request_id"])

    def test_bare_reply_racing_second_task_request_is_linearizable(
        self,
    ) -> None:
        first_store = AuthorityStore(self.data_root)
        first = self._resolve(first_store, "task-first")
        gate = threading.Barrier(2)

        def bare_reply() -> dict:
            gate.wait(timeout=10)
            return AuthorityStore(self.data_root).observe_user_prompt(
                session_id="race-session",
                turn_id="turn-bare",
                cwd=str(self.repository),
                prompt="approve",
                eligible_task_ids=["task-first", "task-second"],
            )

        def create_second() -> dict:
            gate.wait(timeout=10)
            return self._resolve(
                AuthorityStore(self.data_root),
                "task-second",
                request_turn_id="request-second",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            reply_future = executor.submit(bare_reply)
            second_future = executor.submit(create_second)
            reply = reply_future.result()
            second = second_future.result()

        first_final = first_store.records_for_task("task-first")[0]
        second_final = first_store.records_for_task("task-second")[0]
        self.assertEqual(second_final["request_id"], second["request_id"])
        self.assertLessEqual(
            sum(
                record["status"] == "CONFIRMED"
                for record in (first_final, second_final)
            ),
            1,
        )
        if reply["status"] == "CONFIRMED":
            self.assertEqual(reply["request_id"], first["request_id"])
            self.assertEqual(first_final["status"], "CONFIRMED")
            self.assertEqual(second_final["status"], "PENDING")
        else:
            self.assertEqual(reply["status"], "AMBIGUOUS")
            self.assertEqual(reply["eligible_count"], 2)
            self.assertEqual(first_final["status"], "PENDING")
            self.assertEqual(second_final["status"], "PENDING")

    def test_terminal_compaction_racing_decision_preserves_live_state(
        self,
    ) -> None:
        store = AuthorityStore(self.data_root, request_limit=2)
        terminal = self._resolve(store, "task-terminal")
        decided = store.observe_user_prompt(
            session_id="race-session",
            turn_id="terminal-approve",
            cwd=str(self.repository),
            prompt="approve " + terminal["request_id"],
            eligible_task_ids=["task-terminal"],
        )
        self.assertEqual(decided["status"], "CONFIRMED")
        store.consume("task-terminal", terminal["request_id"])
        live = self._resolve(
            store,
            "task-live",
            request_turn_id="live-request",
        )
        gate = threading.Barrier(2)

        def decide_live() -> dict:
            gate.wait(timeout=10)
            return AuthorityStore(
                self.data_root,
                request_limit=2,
            ).observe_user_prompt(
                session_id="race-session",
                turn_id="live-bare-decision",
                cwd=str(self.repository),
                prompt="approve",
                eligible_task_ids=["task-live", "task-new"],
            )

        def create_and_compact() -> dict:
            gate.wait(timeout=10)
            return self._resolve(
                AuthorityStore(self.data_root, request_limit=2),
                "task-new",
                request_turn_id="new-request",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            decision_future = executor.submit(decide_live)
            create_future = executor.submit(create_and_compact)
            decision = decision_future.result()
            new = create_future.result()

        replayed_terminal = self._resolve(
            AuthorityStore(self.data_root, request_limit=2),
            "task-terminal",
        )
        live_final = store.records_for_task("task-live")[0]
        new_final = store.records_for_task("task-new")[0]
        self.assertEqual(replayed_terminal["status"], "CONSUMED")
        self.assertEqual(new_final["request_id"], new["request_id"])
        self.assertEqual(new_final["status"], "PENDING")
        if decision["status"] == "CONFIRMED":
            self.assertEqual(decision["request_id"], live["request_id"])
            self.assertEqual(live_final["status"], "CONFIRMED")
        else:
            self.assertEqual(decision["status"], "AMBIGUOUS")
            self.assertEqual(decision["eligible_count"], 2)
            self.assertEqual(live_final["status"], "PENDING")


class ControllerCrashWindowTests(unittest.TestCase):
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
            "confirmation races\n",
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
                "user.name=Confirmation Race Test",
                "-c",
                "user.email=confirmation-race@example.invalid",
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

    def _start_lite(self, controller: Controller, task_id: str) -> None:
        controller.start(
            requirement="confirmation race",
            workflow="lite",
            workspace_strategy="in-place",
            repositories=[str(self.repository)],
            task_id=task_id,
        )
        controller.preflight(task_id, 0)
        self.assertEqual(controller.show(task_id).current_node, "implement")

    def _at_workspace(self, controller: Controller, task_id: str) -> None:
        controller.start(
            requirement="workspace confirmation race",
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
        state = controller.show(task_id)
        self.assertEqual(state.revision, 4)
        self.assertEqual(state.current_node, "workspace")

    def _request_action(
        self,
        controller: Controller,
        task_id: str,
        revision: int,
        action_id: str,
        payload: dict,
        *,
        session_id: str,
        turn_id: str,
    ) -> str:
        with self.assertRaises(DevFlowError) as captured:
            controller.apply(
                task_id,
                revision,
                action_id,
                payload,
                session_id=session_id,
                request_turn_id=turn_id,
            )
        self.assertIn(
            captured.exception.code,
            {"CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING"},
        )
        packet = captured.exception.details["confirmation"]
        self.assertEqual(packet["status"], "PENDING")
        return packet["request_id"]

    def _decide(
        self,
        controller: Controller,
        task_id: str,
        request_id: str,
        *,
        session_id: str,
        turn_id: str,
        approve: bool = True,
    ) -> dict:
        result = controller.observe_user_prompt(
            session_id=session_id,
            turn_id=turn_id,
            cwd=str(self.repository),
            prompt="{} {}".format(
                "approve" if approve else "deny",
                request_id,
            ),
        )
        self.assertEqual(
            result["status"],
            "CONFIRMED" if approve else "DENIED",
        )
        self.assertEqual(result["request_id"], request_id)
        return result

    @staticmethod
    def _record(
        controller: Controller,
        task_id: str,
        request_id: str,
    ) -> dict:
        return next(
            record
            for record in controller.authorities.records_for_task(task_id)
            if record["request_id"] == request_id
        )

    def test_duplicate_confirmed_effect_free_apply_commits_once(self) -> None:
        controller = Controller(str(self.data_dir))
        self._start_lite(controller, "effect-free-race")
        session_id = "effect-free-session"
        request_id = self._request_action(
            controller,
            "effect-free-race",
            1,
            "task.implementation.complete",
            {"summary": "implemented once"},
            session_id=session_id,
            turn_id="request",
        )
        self._decide(
            controller,
            "effect-free-race",
            request_id,
            session_id=session_id,
            turn_id="approve",
        )

        gate = threading.Barrier(2)
        original_update = controller.store.update

        def gated_update(*args, **kwargs):
            gate.wait(timeout=10)
            return original_update(*args, **kwargs)

        def apply(turn_id: str):
            try:
                return controller.apply(
                    "effect-free-race",
                    1,
                    "task.implementation.complete",
                    {"summary": "implemented once"},
                    session_id=session_id,
                    request_turn_id=turn_id,
                )
            except DevFlowError as exc:
                return exc

        controller.store.update = gated_update
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(apply, "retry-one"),
                    executor.submit(apply, "retry-two"),
                ]
                outcomes = [future.result() for future in futures]
        finally:
            controller.store.update = original_update

        receipts = [
            outcome
            for outcome in outcomes
            if not isinstance(outcome, DevFlowError)
        ]
        failures = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, DevFlowError)
        ]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, "REVISION_CONFLICT")
        state = controller.show("effect-free-race")
        self.assertEqual(state.revision, 2)
        matching_evidence = [
            record
            for record in state.evidence
            if record.get("action_id") == "task.implementation.complete"
        ]
        self.assertEqual(len(matching_evidence), 1)
        self.assertEqual(matching_evidence[0]["authority_id"], request_id)
        self.assertEqual(
            self._record(
                controller,
                "effect-free-race",
                request_id,
            )["status"],
            "CONSUMED",
        )

    def test_next_reconciles_consume_failure_after_task_commit(self) -> None:
        controller = Controller(str(self.data_dir))
        self._start_lite(controller, "consume-window")
        session_id = "consume-window-session"
        request_id = self._request_action(
            controller,
            "consume-window",
            1,
            "task.implementation.complete",
            {"summary": "durably committed"},
            session_id=session_id,
            turn_id="request",
        )
        self._decide(
            controller,
            "consume-window",
            request_id,
            session_id=session_id,
            turn_id="approve",
        )
        original_consume = controller.authorities.consume

        def fail_consume(*args, **kwargs):
            raise DevFlowError(
                "INJECTED_CONSUME_FAILURE",
                "the task commit preceded confirmation consumption",
            )

        controller.authorities.consume = fail_consume
        try:
            with self.assertRaises(DevFlowError) as captured:
                controller.apply(
                    "consume-window",
                    1,
                    "task.implementation.complete",
                    {"summary": "durably committed"},
                    session_id=session_id,
                    request_turn_id="retry",
                )
        finally:
            controller.authorities.consume = original_consume

        self.assertEqual(
            captured.exception.code,
            "INJECTED_CONSUME_FAILURE",
        )
        state = controller.show("consume-window")
        self.assertEqual(state.revision, 2)
        self.assertEqual(
            self._record(
                controller,
                "consume-window",
                request_id,
            )["status"],
            "CONFIRMED",
        )

        controller.next("consume-window", session_id=session_id)
        self.assertEqual(
            self._record(
                controller,
                "consume-window",
                request_id,
            )["status"],
            "CONSUMED",
        )
        self.assertEqual(
            len(
                [
                    record
                    for record in controller.show("consume-window").evidence
                    if record.get("action_id")
                    == "task.implementation.complete"
                ]
            ),
            1,
        )

    def test_next_reconciles_journal_claim_before_confirmation_mark(
        self,
    ) -> None:
        git = SuccessfulWorkspaceGit()
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, "claim-window")
        session_id = "claim-window-session"
        request_id = self._request_action(
            controller,
            "claim-window",
            4,
            "workspace.prepare",
            {},
            session_id=session_id,
            turn_id="request",
        )
        self._decide(
            controller,
            "claim-window",
            request_id,
            session_id=session_id,
            turn_id="approve",
        )
        original_claim = controller.journal.claim

        def fail_after_claim(*args, **kwargs):
            original_claim(*args, **kwargs)
            raise DevFlowError(
                "INJECTED_POST_CLAIM_FAILURE",
                "the journal claim preceded the confirmation mark",
            )

        controller.journal.claim = fail_after_claim
        try:
            with self.assertRaises(DevFlowError) as captured:
                controller.apply(
                    "claim-window",
                    4,
                    "workspace.prepare",
                    {},
                    session_id=session_id,
                    request_turn_id="retry",
                )
        finally:
            controller.journal.claim = original_claim

        self.assertEqual(
            captured.exception.code,
            "INJECTED_POST_CLAIM_FAILURE",
        )
        executions = controller.effect_inspect("claim-window")["executions"]
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["phase"], "CLAIMED")
        self.assertEqual(executions[0]["authority_id"], request_id)
        self.assertEqual(git.dispatch_count, 0)
        self.assertEqual(controller.show("claim-window").revision, 4)
        self.assertEqual(
            self._record(
                controller,
                "claim-window",
                request_id,
            )["status"],
            "CONFIRMED",
        )

        controller.next("claim-window", session_id=session_id)
        self.assertEqual(
            self._record(
                controller,
                "claim-window",
                request_id,
            )["status"],
            "CLAIMED",
        )
        self.assertEqual(git.dispatch_count, 0)

    def test_next_reconciles_task_commit_before_journal_commit(self) -> None:
        git = SuccessfulWorkspaceGit()
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, "journal-commit-window")
        session_id = "journal-commit-session"
        request_id = self._request_action(
            controller,
            "journal-commit-window",
            4,
            "workspace.prepare",
            {},
            session_id=session_id,
            turn_id="request",
        )
        self._decide(
            controller,
            "journal-commit-window",
            request_id,
            session_id=session_id,
            turn_id="approve",
        )
        original_mark_committed = controller.journal.mark_committed

        def fail_mark_committed(*args, **kwargs):
            raise DevFlowError(
                "INJECTED_JOURNAL_COMMIT_FAILURE",
                "the task commit preceded the journal commit",
            )

        controller.journal.mark_committed = fail_mark_committed
        try:
            with self.assertRaises(DevFlowError) as captured:
                controller.apply(
                    "journal-commit-window",
                    4,
                    "workspace.prepare",
                    {},
                    session_id=session_id,
                    request_turn_id="retry",
                )
        finally:
            controller.journal.mark_committed = original_mark_committed

        self.assertEqual(
            captured.exception.code,
            "INJECTED_JOURNAL_COMMIT_FAILURE",
        )
        self.assertEqual(controller.show("journal-commit-window").revision, 5)
        before = controller.effect_inspect(
            "journal-commit-window"
        )["executions"]
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["phase"], "RECEIPT")
        self.assertEqual(git.dispatch_count, 1)
        self.assertEqual(
            self._record(
                controller,
                "journal-commit-window",
                request_id,
            )["status"],
            "CLAIMED",
        )

        controller.next("journal-commit-window", session_id=session_id)
        after = controller.effect_inspect(
            "journal-commit-window"
        )["executions"]
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["phase"], "COMMITTED")
        self.assertEqual(after[0]["committed_revision"], 5)
        self.assertEqual(
            self._record(
                controller,
                "journal-commit-window",
                request_id,
            )["status"],
            "CONSUMED",
        )
        self.assertEqual(git.dispatch_count, 1)

    def test_two_session_workspace_race_has_one_claim_and_dispatch(
        self,
    ) -> None:
        git = BlockingWorkspaceGit()
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, "workspace-race")
        first_session = "workspace-session-one"
        second_session = "workspace-session-two"
        first_request = self._request_action(
            controller,
            "workspace-race",
            4,
            "workspace.prepare",
            {},
            session_id=first_session,
            turn_id="request-one",
        )
        second_request = self._request_action(
            controller,
            "workspace-race",
            4,
            "workspace.prepare",
            {},
            session_id=second_session,
            turn_id="request-two",
        )
        self.assertNotEqual(first_request, second_request)
        self._decide(
            controller,
            "workspace-race",
            first_request,
            session_id=first_session,
            turn_id="approve-one",
        )
        self._decide(
            controller,
            "workspace-race",
            second_request,
            session_id=second_session,
            turn_id="approve-two",
        )

        def first_apply():
            return controller.apply(
                "workspace-race",
                4,
                "workspace.prepare",
                {},
                session_id=first_session,
                request_turn_id="retry-one",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(first_apply)
            self.assertTrue(git.entered.wait(timeout=10))
            second_future = executor.submit(
                controller.apply,
                "workspace-race",
                4,
                "workspace.prepare",
                {},
                session_id=second_session,
                request_turn_id="retry-two",
            )
            try:
                self.assertFalse(second_future.done())
            finally:
                git.release.set()
            receipt = first_future.result()
            with self.assertRaises(DevFlowError) as captured:
                second_future.result()
            self.assertEqual(
                captured.exception.code,
                "EFFECT_ALREADY_CLAIMED",
            )

        self.assertEqual(receipt.committed_revision, 5)
        self.assertEqual(git.dispatch_count, 1)
        executions = controller.effect_inspect(
            "workspace-race"
        )["executions"]
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0]["phase"], "COMMITTED")
        self.assertEqual(executions[0]["attempt"], 1)
        self.assertEqual(executions[0]["history"], [])
        self.assertEqual(executions[0]["authority_id"], first_request)

        controller.next("workspace-race", session_id=second_session)
        self.assertEqual(
            self._record(
                controller,
                "workspace-race",
                first_request,
            )["status"],
            "CONSUMED",
        )
        self.assertEqual(
            self._record(
                controller,
                "workspace-race",
                second_request,
            )["status"],
            "STALE",
        )

    def test_abandon_retry_gets_new_request_with_stable_execution_key(
        self,
    ) -> None:
        git = AbsentUncertainWorkspaceGit()
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, "abandon-retry")
        session_id = "abandon-retry-session"
        first_request = self._request_action(
            controller,
            "abandon-retry",
            4,
            "workspace.prepare",
            {},
            session_id=session_id,
            turn_id="request-attempt-one",
        )
        self._decide(
            controller,
            "abandon-retry",
            first_request,
            session_id=session_id,
            turn_id="approve-attempt-one",
        )
        with self.assertRaises(DevFlowError) as first_failure:
            controller.apply(
                "abandon-retry",
                4,
                "workspace.prepare",
                {},
                session_id=session_id,
                request_turn_id="retry-attempt-one",
            )
        self.assertEqual(first_failure.exception.code, "EFFECT_UNCERTAIN")
        first_execution = controller.effect_inspect(
            "abandon-retry"
        )["executions"][0]
        execution_id = first_execution["plan_binding"]
        self.assertEqual(first_execution["attempt"], 1)
        self.assertEqual(first_execution["phase"], "QUARANTINED")

        with self.assertRaises(DevFlowError) as recovery_pending:
            controller.recover_effect(
                "abandon-retry",
                execution_id,
                "abandon",
                session_id=session_id,
                request_turn_id="request-abandon",
            )
        self.assertEqual(
            recovery_pending.exception.code,
            "CONFIRMATION_REQUIRED",
        )
        recovery_id = recovery_pending.exception.details[
            "confirmation"
        ]["request_id"]
        self._decide(
            controller,
            "abandon-retry",
            recovery_id,
            session_id=session_id,
            turn_id="approve-abandon",
        )
        recovery = controller.recover_effect(
            "abandon-retry",
            execution_id,
            "abandon",
            session_id=session_id,
            request_turn_id="retry-abandon",
        )
        self.assertEqual(recovery["outcome"], "ABANDONED")
        self.assertEqual(
            controller.effect_inspect(
                "abandon-retry"
            )["executions"][0]["phase"],
            "ABANDONED",
        )
        self.assertEqual(controller.show("abandon-retry").revision, 4)

        second_request = self._request_action(
            controller,
            "abandon-retry",
            4,
            "workspace.prepare",
            {},
            session_id=session_id,
            turn_id="request-attempt-two",
        )
        self.assertNotEqual(second_request, first_request)
        second_packet = AuthorityStore.public_packet(
            self._record(
                controller,
                "abandon-retry",
                second_request,
            )
        )
        self.assertEqual(second_packet["scope"], {"effect_attempt": 2})
        self._decide(
            controller,
            "abandon-retry",
            second_request,
            session_id=session_id,
            turn_id="approve-attempt-two",
        )
        with self.assertRaises(DevFlowError) as second_failure:
            controller.apply(
                "abandon-retry",
                4,
                "workspace.prepare",
                {},
                session_id=session_id,
                request_turn_id="retry-attempt-two",
            )
        self.assertEqual(second_failure.exception.code, "EFFECT_UNCERTAIN")

        executions = controller.effect_inspect(
            "abandon-retry"
        )["executions"]
        self.assertEqual(len(executions), 1)
        second_execution = executions[0]
        self.assertEqual(second_execution["plan_binding"], execution_id)
        self.assertEqual(second_execution["attempt"], 2)
        self.assertEqual(second_execution["phase"], "QUARANTINED")
        self.assertEqual(second_execution["authority_id"], second_request)
        self.assertEqual(len(second_execution["history"]), 1)
        self.assertEqual(
            second_execution["history"][0]["phase"],
            "ABANDONED",
        )
        self.assertEqual(git.dispatch_count, 2)


if __name__ == "__main__":
    unittest.main()
