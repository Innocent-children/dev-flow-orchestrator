from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.git_client import GitClient
from dev_flow_orchestrator.model import DevFlowError
from tests.greenfield_authority import ConversationAuthority


class UncertainWorkspaceGit(GitClient):
    def __init__(self, *, create_destination: bool) -> None:
        self.create_destination = create_destination
        self.dispatch_count = 0

    def prepare_workspace(
        self,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        self.dispatch_count += 1
        if self.create_destination:
            destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        raise DevFlowError("INJECTED_INTERRUPTION", "effect outcome is uncertain")

    def observe_workspace(self, request: dict) -> dict:
        return {
            "schema": "dev-flow-v4-workspace-receipt/v1",
            "strategy": request["strategy"],
            "path": request["destination"],
            "head": request["expected_head"],
            "branch": None,
        }

    def workspace_effect_absent(self, request: dict) -> bool:
        return not Path(request["destination"]).exists()


class GreenfieldEffectRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)
        (self.repository / "README.md").write_text("effect\n", encoding="utf-8")
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
        self.conversations = {}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _conversation(
        self,
        controller: Controller,
        task_id: str,
    ) -> ConversationAuthority:
        key = (id(controller), task_id)
        if key not in self.conversations:
            self.conversations[key] = ConversationAuthority(
                controller,
                self.repository,
                session_id="effect-recovery-" + task_id,
            )
        return self.conversations[key]

    def _at_workspace(self, controller: Controller, task_id: str) -> None:
        controller.start(
            requirement="effect recovery",
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

    def _recover(
        self,
        controller: Controller,
        task_id: str,
        binding: str,
        mode: str,
    ) -> dict:
        return self._conversation(controller, task_id).recover(
            task_id,
            binding,
            mode,
        )

    def test_successful_effect_has_claim_receipt_and_commit(self) -> None:
        controller = Controller(str(self.data_dir))
        self._at_workspace(controller, "success")
        receipt = self._conversation(controller, "success").apply(
            "success",
            4,
            "workspace.prepare",
            {},
        )
        inspection = controller.effect_inspect("success")
        self.assertEqual(receipt.committed_revision, 5)
        self.assertEqual(receipt.confirmation["status"], "CONSUMED")
        self.assertEqual(len(inspection["executions"]), 1)
        self.assertEqual(inspection["executions"][0]["phase"], "COMMITTED")
        self.assertEqual(
            inspection["executions"][0]["authority_id"],
            receipt.confirmation["request_id"],
        )
        self.assertEqual(len(controller.show("success").effects), 1)
        self.assertEqual(
            controller.show("success").effects[0]["authority_id"],
            receipt.confirmation["request_id"],
        )

    def test_invalid_payload_is_rejected_before_claim_or_dispatch(self) -> None:
        git = UncertainWorkspaceGit(create_destination=True)
        controller = Controller(str(self.data_dir), git_client=git)
        self._at_workspace(controller, "invalid-payload")
        requests_before = len(
            controller.authorities.records_for_task("invalid-payload")
        )
        with self.assertRaises(DevFlowError) as captured:
            controller.apply(
                "invalid-payload",
                4,
                "workspace.prepare",
                {"undeclared": True},
            )
        self.assertEqual(captured.exception.code, "NODE_OUTPUT_INVALID")
        self.assertEqual(git.dispatch_count, 0)
        self.assertEqual(
            controller.effect_inspect("invalid-payload")["executions"],
            [],
        )
        self.assertEqual(controller.show("invalid-payload").revision, 4)
        self.assertEqual(
            len(controller.authorities.records_for_task("invalid-payload")),
            requests_before,
        )

    def test_uncertain_effect_is_single_dispatch_and_can_settle(self) -> None:
        git = UncertainWorkspaceGit(create_destination=True)
        controller = Controller(
            str(self.data_dir),
            git_client=git,
        )
        self._at_workspace(controller, "settle")
        authority = self._conversation(controller, "settle")
        with self.assertRaises(DevFlowError) as first:
            authority.apply(
                "settle",
                4,
                "workspace.prepare",
                {},
            )
        self.assertEqual(first.exception.code, "EFFECT_UNCERTAIN")
        execution = controller.effect_inspect("settle")["executions"][0]
        self.assertEqual(execution["phase"], "QUARANTINED")
        original_request_id = execution["authority_id"]
        original = next(
            record
            for record in controller.authorities.records_for_task("settle")
            if record["request_id"] == original_request_id
        )
        self.assertEqual(original["status"], "CLAIMED")
        pending_recovery = authority.request_recovery(
            "settle",
            execution["plan_binding"],
            "settle",
        )
        with self.assertRaises(DevFlowError) as replay:
            controller.apply(
                "settle",
                4,
                "workspace.prepare",
                {},
                session_id=authority.session_id,
                request_turn_id="ordinary-retry",
            )
        self.assertEqual(replay.exception.code, "EFFECT_ALREADY_CLAIMED")
        self.assertEqual(git.dispatch_count, 1)
        authority.decide(pending_recovery, approve=True)
        result = authority.retry_recovery(pending_recovery)
        self.assertEqual(result["outcome"], "SETTLED")
        self.assertEqual(result["confirmation"]["status"], "CONSUMED")
        self.assertEqual(
            result["confirmation"]["request_id"],
            pending_recovery.request_id,
        )
        self.assertEqual(controller.show("settle").revision, 5)
        final = controller.effect_inspect("settle")["executions"][0]
        self.assertEqual(final["phase"], "COMMITTED")

    def test_absent_effect_can_be_abandoned_without_state_change(self) -> None:
        git = UncertainWorkspaceGit(create_destination=False)
        controller = Controller(
            str(self.data_dir),
            git_client=git,
        )
        self._at_workspace(controller, "abandon")
        with self.assertRaises(DevFlowError):
            self._conversation(controller, "abandon").apply(
                "abandon",
                4,
                "workspace.prepare",
                {},
            )
        execution = controller.effect_inspect("abandon")["executions"][0]
        result = self._recover(
            controller,
            "abandon",
            execution["plan_binding"],
            "abandon",
        )
        self.assertEqual(result["outcome"], "ABANDONED")
        self.assertEqual(controller.show("abandon").revision, 4)

    def test_unavailable_reattach_and_compensation_are_bounded(self) -> None:
        git = UncertainWorkspaceGit(create_destination=True)
        controller = Controller(
            str(self.data_dir),
            git_client=git,
        )
        self._at_workspace(controller, "operator")
        with self.assertRaises(DevFlowError):
            self._conversation(controller, "operator").apply(
                "operator",
                4,
                "workspace.prepare",
                {},
            )
        execution = controller.effect_inspect("operator")["executions"][0]
        authority = self._conversation(controller, "operator")
        requests_before = len(
            controller.authorities.records_for_task("operator")
        )
        for mode in ("reattach", "compensate", "abandon"):
            result = controller.recover_effect(
                "operator",
                execution["plan_binding"],
                mode,
                session_id=authority.session_id,
                request_turn_id="unsupported-" + mode,
            )
            self.assertEqual(
                result["schema"],
                "dev-flow-v4-operator-intervention/v1",
            )
            self.assertFalse(result["automatic_redispatch"])
            self.assertFalse(result["automatic_compensation"])
            self.assertFalse(result["caller_assertion_can_unblock"])
            self.assertEqual(
                len(controller.authorities.records_for_task("operator")),
                requests_before,
            )
        self.assertEqual(controller.show("operator").revision, 4)


if __name__ == "__main__":
    unittest.main()
