from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError
from tests.greenfield_authority import ConversationAuthority


class GreenfieldCoreWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)
        (self.repository / "README.md").write_text("greenfield\n", encoding="utf-8")
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
        self.controller = Controller(str(self.root / "data"))
        self.authority = ConversationAuthority(
            self.controller,
            self.repository,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _start(self, task_id: str, workflow: str, strategy: str = "in-place"):
        self.controller.start(
            requirement="core workflow",
            workflow=workflow,
            workspace_strategy=strategy,
            repositories=[str(self.repository)],
            task_id=task_id,
        )
        self.controller.preflight(task_id, 0)

    def _apply(self, task_id: str, action: str, payload: dict):
        revision = self.controller.show(task_id).revision
        return self.authority.apply(
            task_id,
            revision,
            action,
            payload,
        )

    def test_projection_is_derived_from_current_node(self) -> None:
        self._start("projection", "lite")
        projection = self.controller.next("projection")
        self.assertEqual(projection["current_node"], "implement")
        self.assertEqual(
            projection["workflow"]["identity"],
            self.controller.show("projection").workflow_identity,
        )
        self.assertEqual(
            projection["action"]["action_id"],
            "task.implementation.complete",
        )
        self.assertEqual(
            projection["action"]["allowed_state_writes"],
            [
                "/current_node",
                "/revision",
                "/status",
                "/updated_at",
                "/evidence",
            ],
        )

    def test_lite_workflow_enters_implementation_without_lite_gate(self) -> None:
        self._start("lite", "lite")
        initial = self.controller.show("lite")
        self.assertEqual(initial.current_node, "implement")
        self.assertEqual(initial.status, "IMPLEMENTING")
        self.assertEqual(len(initial.approvals), 0)
        self.assertEqual(
            self.controller.authorities.records_for_task("lite"),
            (),
        )
        self.assertEqual(self.controller.show("lite").revision, 1)
        receipt = self._apply(
            "lite",
            "task.implementation.complete",
            {"summary": "implemented"},
        )
        self.assertEqual(receipt.confirmation["status"], "CONSUMED")
        self._apply(
            "lite",
            "evidence.test.record",
            {"passed": True, "command": "focused"},
        )
        state = self.controller.show("lite")
        self.assertEqual(state.status, "DONE")
        self.assertEqual(state.current_node, "done")
        self.assertEqual(len(state.approvals), 0)
        self.assertIsNone(self.controller.next("lite")["action"])

    def test_controller_persists_exact_conversation_authority(self) -> None:
        self._start("host-authority", "lite")
        pending = self.authority.request_action(
            "host-authority",
            1,
            "task.implementation.complete",
            {"summary": "implemented"},
        )
        records = self.controller.authorities.records_for_task(
            "host-authority"
        )
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["request_id"], pending.request_id)
        self.assertEqual(
            {
                key: record["binding"][key]
                for key in (
                    "task_id",
                    "expected_revision",
                    "action_id",
                    "grant",
                    "scope",
                    "context",
                    "session_id",
                )
            },
            {
                "task_id": "host-authority",
                "expected_revision": 1,
                "action_id": "task.implementation.complete",
                "grant": "implementer",
                "scope": {},
                "context": {"summary": "implemented"},
                "session_id": pending.session_id,
            },
        )
        self.assertEqual(
            record["binding"]["actor"]["role"],
            "implementer",
        )
        projected = self.controller.next(
            "host-authority",
            session_id=pending.session_id,
        )
        self.assertEqual(
            projected["confirmation"]["requests"][0]["request_id"],
            pending.request_id,
        )
        self.authority.decide(pending, approve=True)
        receipt = self.authority.retry_action(pending)
        self.assertEqual(
            receipt.confirmation["request_id"],
            pending.request_id,
        )
        self.assertEqual(receipt.confirmation["status"], "CONSUMED")
        evidence = self.controller.show("host-authority").evidence[-1]
        self.assertEqual(evidence["authority_id"], pending.request_id)
        self.assertEqual(
            self.controller.authorities.records_for_task(
                "host-authority"
            )[0]["status"],
            "CONSUMED",
        )

    def test_full_workflow_has_explicit_nodes(self) -> None:
        self._start("full", "full")
        actions = [
            ("evidence.baseline.record", {"baseline": "head"}),
            ("evidence.impact.record", {"impact": "bounded"}),
            ("task.route.set", {"route": "direct", "reason": "small"}),
            ("workspace.prepare", {}),
            ("evidence.plan.record", {"plan": "one step"}),
            ("gate.plan.approve", {"approved": True}),
            ("task.implementation.complete", {"summary": "implemented"}),
            (
                "evidence.test.record",
                {"passed": True, "command": "focused"},
            ),
            (
                "evidence.review.record",
                {"verdict": "PASS", "review_fingerprint": "a" * 64},
            ),
            ("task.finalize", {"summary": "ready"}),
        ]
        expected_nodes = [
            "impact",
            "route",
            "workspace",
            "planning",
            "plan-approval",
            "implement",
            "verify",
            "review",
            "finalize",
            "done",
        ]
        for (action, payload), expected_node in zip(actions, expected_nodes):
            self._apply("full", action, payload)
            self.assertEqual(
                self.controller.show("full").current_node,
                expected_node,
            )
        self.assertEqual(self.controller.show("full").status, "DONE")

    def test_action_at_wrong_node_does_not_mutate(self) -> None:
        self._start("wrong-node", "full")
        with self.assertRaises(DevFlowError) as captured:
            self._apply(
                "wrong-node",
                "task.finalize",
                {"summary": "too early"},
            )
        self.assertEqual(captured.exception.code, "ACTION_NOT_AVAILABLE")
        self.assertEqual(self.controller.show("wrong-node").revision, 1)

    def test_worktree_strategy_uses_declared_git_effect(self) -> None:
        self._start("worktree", "full", "worktree")
        self._apply("worktree", "evidence.baseline.record", {"baseline": "head"})
        self._apply("worktree", "evidence.impact.record", {"impact": "bounded"})
        self._apply(
            "worktree",
            "task.route.set",
            {"route": "worktree", "reason": "isolated"},
        )
        pending = self.authority.request_action(
            "worktree",
            4,
            "workspace.prepare",
            {},
        )
        self.assertEqual(self.controller.show("worktree").revision, 4)
        self.assertFalse(
            (
                self.root
                / "data"
                / "workspaces"
                / "worktree"
            ).exists()
        )
        self.authority.decide(pending, approve=True)
        receipt = self.authority.retry_action(pending)
        self.assertEqual(receipt.confirmation["status"], "CONSUMED")
        state = self.controller.show("worktree")
        workspace = state.repositories[0].workspace
        self.assertEqual(workspace["strategy"], "worktree")
        self.assertTrue(Path(workspace["path"]).is_dir())
        self.assertEqual(state.current_node, "planning")

    def test_workspace_rejects_head_drift_before_git_mutation(self) -> None:
        self._start("drift", "full", "worktree")
        self._apply("drift", "evidence.baseline.record", {"baseline": "head"})
        self._apply("drift", "evidence.impact.record", {"impact": "bounded"})
        self._apply(
            "drift",
            "task.route.set",
            {"route": "worktree", "reason": "isolated"},
        )
        (self.repository / "DRIFT.md").write_text("drift\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.repository), "add", "DRIFT.md"],
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
                "drift",
            ],
            check=True,
        )
        with self.assertRaises(DevFlowError) as captured:
            self._apply("drift", "workspace.prepare", {})
        self.assertEqual(captured.exception.code, "EFFECT_UNCERTAIN")
        execution = self.controller.effect_inspect("drift")["executions"][0]
        self.assertEqual(execution["error"]["code"], "REPOSITORY_DRIFT")
        self.assertFalse(
            (
                self.root
                / "data"
                / "workspaces"
                / "drift"
                / self.controller.show("drift").repositories[0].repository_id
            ).exists()
        )

    def test_node_payloads_are_declared_typed_and_bounded(self) -> None:
        self._start("payload", "lite")
        with self.assertRaises(DevFlowError) as unknown:
            self.controller.apply(
                "payload",
                1,
                "task.implementation.complete",
                {"summary": "implemented", "undeclared": "value"},
            )
        self.assertEqual(unknown.exception.code, "NODE_OUTPUT_INVALID")
        with self.assertRaises(DevFlowError) as wrong_type:
            self.controller.apply(
                "payload",
                1,
                "task.implementation.complete",
                {"summary": False},
            )
        self.assertEqual(wrong_type.exception.code, "NODE_OUTPUT_INVALID")
        self._apply(
            "payload",
            "task.implementation.complete",
            {"summary": "implemented"},
        )
        with self.assertRaises(DevFlowError) as oversized:
            self.controller.apply(
                "payload",
                2,
                "evidence.test.record",
                {"passed": True, "command": "x" * 8193},
            )
        self.assertEqual(oversized.exception.code, "NODE_OUTPUT_INVALID")
        self.assertEqual(self.controller.show("payload").revision, 2)

    def test_roles_share_the_same_local_conversation_principal(self) -> None:
        self._start("actor-separation", "full")
        for action, payload in (
            ("evidence.baseline.record", {"baseline": "head"}),
            ("evidence.impact.record", {"impact": "bounded"}),
            ("task.route.set", {"route": "direct", "reason": "small"}),
            ("workspace.prepare", {}),
            ("evidence.plan.record", {"plan": "one step"}),
            ("gate.plan.approve", {"approved": True}),
        ):
            self._apply("actor-separation", action, payload)
        revision = self.controller.show("actor-separation").revision
        pending = self.authority.request_action(
            "actor-separation",
            revision,
            "task.implementation.complete",
            {"summary": "implemented"},
        )
        self.authority.decide(pending, approve=True)
        self.authority.retry_action(pending)
        self._apply(
            "actor-separation",
            "evidence.test.record",
            {"passed": True, "command": "focused"},
        )
        self._apply(
            "actor-separation",
            "evidence.review.record",
            {"verdict": "PASS", "review_fingerprint": "b" * 64},
        )
        state = self.controller.show("actor-separation")
        implementer = next(
            item["actor_id"]
            for item in state.evidence
            if item["action_id"] == "task.implementation.complete"
        )
        reviewer = next(
            item["actor_id"]
            for item in state.evidence
            if item["action_id"] == "evidence.review.record"
        )
        self.assertEqual(implementer, reviewer)
        self.assertTrue(implementer.startswith("local:"))
        review = next(
            item
            for item in state.evidence
            if item["action_id"] == "evidence.review.record"
        )
        self.assertEqual(review["payload"]["review_fingerprint"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
