from __future__ import annotations

import hashlib
import json
from pathlib import Path

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class WorkflowProjectionTests(DevFlowTestCase):
    def _start_task(self, task_id: str = "projection-task") -> dict:
        repository, _ = self.make_repo("projection-repository")
        return self.cli(
            "start",
            "project the pinned workflow",
            "--repo",
            str(repository),
            "--task-id",
            task_id,
            "--workspace-strategy",
            "in-place",
            "--change-category",
            "docs",
            "--target-path",
            "tracked.txt",
        )

    def test_show_next_is_bounded_and_derived_from_legacy_bundle(self) -> None:
        self._start_task()

        response = self.cli("show", "projection-task", "--next")

        self.assertEqual(response["profile"], "agent-v1")
        task_next = response["next"]
        self.assertEqual(task_next["contract"], "agent-v1")
        self.assertIn("artifact", task_next)
        content, _ = dev_flow.resolve_workflow_protocol_artifact(
            "projection-task",
            task_next["artifact"]["locator"],
            data_dir=self.data,
        )
        detail = json.loads(content.decode("utf-8"))
        self.assertEqual(detail["workflow"]["id"], "lite-legacy")
        self.assertEqual(detail["frontier"][0]["node_id"], "INTAKE")
        self.assertEqual(
            {
                item["edge_id"] for item in detail["actions"]
            },
            {
                "lite-legacy.intake.preflight-blocked",
                "lite-legacy.intake.preflighted",
                "lite-legacy.cancel.intake.cancelled",
                "lite-legacy.transition-cancel.intake.cancelled",
                "lite-legacy.block.intake.blocked",
            },
        )
        self.assertLessEqual(
            dev_flow.protocol_size(task_next),
            dev_flow.TASK_NEXT_BUDGET,
        )
        profile = self.cli(
            "show", "projection-task", "--profile", "agent-v1"
        )
        self.assertEqual(profile["next"], task_next)

    def test_progress_and_node_description_use_one_pinned_catalog(self) -> None:
        self._start_task()
        state = dev_flow.load_state("projection-task", self.data)

        progress = dev_flow.workflow_progress_projection(state)
        description = dev_flow.workflow_node_description(state)

        self.assertEqual(progress["node_id"], "INTAKE")
        self.assertEqual(progress["labels"]["zh-CN"], "需求接收")
        self.assertEqual(progress["position"], 0)
        self.assertEqual(progress["index_role"], None)
        self.assertEqual(description["node"]["id"], "INTAKE")
        self.assertEqual(
            description["workflow"]["bundle_sha256"],
            progress["workflow"]["bundle_sha256"],
        )
        self.assertTrue(
            description["playbook"]["locator"].startswith("bundle/")
        )
        self.assertNotIn("module", json.dumps(description))
        self.assertNotIn("shell", json.dumps(description))

        playbook = dev_flow.workflow_node_playbook(
            state,
            locator=description["playbook"]["locator"],
        )
        self.assertEqual(
            playbook["contract"], "dev-flow-node-playbook/v1"
        )
        self.assertEqual(playbook["node_id"], "INTAKE")
        self.assertTrue(playbook["content"].startswith("## intake\n"))
        self.assertNotIn("## preflighted", playbook["content"])
        self.assertLessEqual(
            playbook["size"], dev_flow.WORKFLOW_PLAYBOOK_BUDGET
        )
        self.assertEqual(
            playbook["workflow"]["bundle_sha256"],
            progress["workflow"]["bundle_sha256"],
        )

        with self.assertRaises(
            dev_flow.WorkflowProjectionError
        ) as raised:
            dev_flow.workflow_node_playbook(
                state, locator="bundle/other/playbooks/workflow.md"
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_PROJECTION_PLAYBOOK_LOCATOR_MISMATCH",
        )

    def test_protocol_artifact_resolution_is_task_scoped_and_integrity_bound(
        self,
    ) -> None:
        self._start_task()
        content = b'{"large":"projection"}'
        reference = dev_flow._workflow_projection_artifact_writer(
            self.data
        )("projection-task", "task-next", content)

        observed, verified = dev_flow.resolve_workflow_protocol_artifact(
            "projection-task",
            reference["locator"],
            data_dir=self.data,
        )

        self.assertEqual(observed, content)
        self.assertEqual(
            verified["sha256"], hashlib.sha256(content).hexdigest()
        )
        path = (
            self.data
            / "tasks"
            / "projection-task"
            / Path(reference["locator"])
        )
        path.write_bytes(b"tampered")
        with self.assertRaises(
            dev_flow.WorkflowProjectionError
        ) as raised:
            dev_flow.resolve_workflow_protocol_artifact(
                "projection-task",
                reference["locator"],
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "PROTOCOL_ARTIFACT_INTEGRITY_MISMATCH",
        )

    def test_show_projection_modes_remain_mutually_exclusive(self) -> None:
        parser = dev_flow.build_parser()
        with self.assertRaises(dev_flow.FlowError) as raised:
            parser.parse_args(
                [
                    "show",
                    "projection-task",
                    "--next",
                    "--compact",
                ]
            )
        self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")
