from __future__ import annotations

import hashlib
import json
import unittest

from dev_flow_orchestrator import engine
from dev_flow_orchestrator.mcp.guidance import (
    SERVER_INSTRUCTIONS,
    guidance_for_projection,
)
from dev_flow_orchestrator.mcp.identity import (
    MCP_CURRENT_ACTION_MAX_BYTES,
    MCP_GUIDANCE_MAX_BYTES,
    MCP_GUIDANCE_SCHEMA,
    MCP_SERVER_INSTRUCTIONS_MAX_BYTES,
)
from dev_flow_orchestrator.mcp.projection import (
    FIELD_USE_MANIFEST,
    compact_current_action,
)
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.review_guidance import (
    INDEPENDENT_REVIEW_GUIDANCE_DIGEST,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class MCPGuidanceTests(unittest.TestCase):
    def _action(
        self,
        *,
        action_id: str,
        handler: str = "artifact.record",
        node_id: str = "implement",
        workspace: str = "context",
        payload: dict | None = None,
        driver: dict | None = None,
    ) -> dict:
        return {
            "node_id": node_id,
            "action_id": action_id,
            "target": {"node": "next", "status": "ACTIVE"},
            "handler": handler,
            "payload": {} if payload is None else payload,
            "writes": ["artifact"],
            "driver": driver,
            "description": None,
            "artifact": {
                "type": "artifact",
                "workspace": workspace,
                "inputs": [],
            },
            "rework": None,
            "finalize": None,
            "inputs": [],
            "binding": {
                "task_id": "task-guidance",
                "starting_snapshot_digest": "b" * 64,
                "digest": "z" * 64,
            },
            "blocked": None,
            "retry_budget": None,
        }

    def _projection(self, action: dict | None, *, done: bool = False) -> dict:
        return {
            "schema": "dev-flow-agent/0.4.0",
            "task_id": "task-guidance",
            "revision": 7,
            "workflow": {"id": "feature", "version": "0.4.0"},
            "status": "DONE" if done else "ACTIVE",
            "current_node": "done" if done else (action or {}).get("node_id"),
            "contract": {"revision": 2, "summary": "bounded"},
            "repository_set": {
                "id": "repository-set",
                "digest": "w" * 64,
                "repositories": [
                    {
                        "id": "repo-a",
                        "path": "/workspace/repo-a",
                        "snapshot": {
                            "digest": "a" * 64,
                            "head": "1" * 40,
                            "branch": "main",
                            "clean": False,
                            "status_sha256": "2" * 64,
                            "status_bytes": 19,
                            "object_format": "sha1",
                            "index_entry_count": 3,
                            "index_output_bytes": 72,
                            "has_unmerged_entries": False,
                        },
                    },
                    {
                        "id": "repo-b",
                        "path": "/workspace/repo-b",
                        "snapshot": {
                            "digest": "c" * 64,
                            "head": "3" * 40,
                            "branch": "topic",
                            "clean": True,
                            "status_sha256": "4" * 64,
                            "status_bytes": 0,
                            "object_format": "sha1",
                            "index_entry_count": 1,
                            "index_output_bytes": 24,
                            "has_unmerged_entries": False,
                        },
                    },
                ],
            },
            "freshness": {"current": True},
            "review": None,
            "action": action,
            "dossier": {"schema": "dev-flow-delivery-dossier/0.4.0", "digest": "d" * 64}
            if done
            else None,
            "done": done,
        }

    def assertGuidanceDigest(self, guidance: dict) -> None:
        body = dict(guidance)
        digest = body.pop("guidance_digest")
        self.assertEqual(digest, hashlib.sha256(_canonical(body)).hexdigest())
        self.assertEqual(digest, digest.lower())

    def test_instructions_and_preflight_are_self_contained_and_bounded(self) -> None:
        encoded = SERVER_INSTRUCTIONS.encode("utf-8")
        self.assertLessEqual(len(encoded), MCP_SERVER_INSTRUCTIONS_MAX_BYTES)
        prefix = encoded[:512].decode("ascii")
        for phrase in (
            "Controller is the only",
            "dev_flow_find_tasks_for_path",
            "dev_flow_start_task only if none matches",
            "dev_flow_get_next_action to obtain exactly one action",
            "immutable repository set",
            "dev_flow_apply_action with its exact current binding and closed payload",
            "stale, ambiguous, unavailable, or terminal",
            "Direct task-state file access is unsupported",
        ):
            self.assertIn(phrase, prefix)

        action = self._action(
            action_id="task.preflight",
            handler="preflight",
            node_id="preflight",
            workspace="produces-source",
        )
        guidance = guidance_for_projection(self._projection(action))
        required = {
            "schema",
            "objective",
            "must_read",
            "allowed_effects",
            "required_evidence",
            "payload_notes",
            "driver",
            "stale_recovery",
            "completion_rule",
            "guidance_digest",
        }
        self.assertEqual(set(guidance), required)
        self.assertEqual(guidance["schema"], MCP_GUIDANCE_SCHEMA)
        self.assertEqual(guidance["allowed_effects"], "read-only")
        self.assertIn("empty payload", " ".join(guidance["payload_notes"]))
        self.assertNotIn("task-change-claims", json.dumps(guidance))
        self.assertNotIn("Implement", guidance["objective"])
        self.assertGuidanceDigest(guidance)
        self.assertLessEqual(len(_canonical(guidance)), MCP_GUIDANCE_MAX_BYTES)

    def test_source_producing_guidance_and_projection_preserve_exact_authority(self) -> None:
        action = self._action(
            action_id="implementation.record",
            workspace="produces-source",
            payload={"summary": "string"},
        )
        binding = action["binding"]
        causal = {"type": "verification-result", "edge": "causal", "record_id": "r0"}
        governing = {"type": "impact-report", "edge": "governing", "record_id": "r1"}
        predecessor = {
            "type": "implementation",
            "edge": "source-predecessor",
            "record_id": "r2",
            "snapshot_digest": "b" * 64,
        }
        action["inputs"] = [predecessor, causal, governing]
        action["blocked"] = {
            "code": "AMBIENT_DRIFT",
            "details": {"recovery": ["restore", "revise-contract", "cancel-with-authority"]},
        }
        projection = self._projection(action)
        guidance = guidance_for_projection(projection)
        self.assertEqual(guidance["allowed_effects"], "source-producing")
        rendered = json.dumps(guidance, ensure_ascii=False)
        for phrase in (
            "starting_snapshot_digest",
            "dev-flow-task-change-claims/0.4.0",
            "repository_id",
            "criterion_ids",
            "ambient drift",
            "binding is null",
        ):
            self.assertIn(phrase, rendered)

        compact = compact_current_action(projection, guidance)
        self.assertIs(compact["action"]["binding"], binding)
        self.assertEqual(compact["inputs"], [predecessor, causal, governing])
        self.assertEqual(compact["resources"], [governing])
        self.assertEqual(compact["action"]["context"]["blocked"], action["blocked"])
        self.assertEqual(
            compact["repository_set"]["workspace_snapshot_digest"],
            projection["repository_set"]["digest"],
        )
        self.assertEqual(
            compact["repository_set"]["repositories"][0]["status_sha256"],
            "2" * 64,
        )

    def test_optional_driver_fallbacks_are_exact_truthful_and_stable(self) -> None:
        graph_fallback = "Inspect the exact source slice directly and record degraded coverage."
        impact = self._action(
            action_id="impact.record",
            node_id="impact",
            payload={"summary": "string", "driver_result": "object"},
            driver={
                "tool": "codebase-memory",
                "optional": True,
                "fallback": graph_fallback,
                "produces": "impact-report",
            },
        )
        graph = guidance_for_projection(self._projection(impact))
        self.assertEqual(graph["driver"]["fallback"], graph_fallback)
        self.assertEqual(graph["driver"]["status_values"], ["available", "degraded", "unavailable"])
        self.assertIn("stale or unmatched", graph["driver"]["source_confirmation"])
        self.assertIn("fallback evidence is never", graph["driver"]["truth_rule"])

        # Task identity, revision, current snapshots, and binding are ambient
        # projection data; unchanged normative guidance keeps one stable digest.
        changed = self._projection(dict(impact))
        changed["task_id"] = "another-task"
        changed["revision"] = 99
        changed["repository_set"]["digest"] = "9" * 64
        changed["action"]["binding"] = {"digest": "8" * 64}
        self.assertEqual(
            graph["guidance_digest"],
            guidance_for_projection(changed)["guidance_digest"],
        )

        openspec_fallback = "Create the same repository-backed plan and report degraded provenance."
        planning = self._action(
            action_id="plan.record",
            node_id="planning",
            workspace="produces-source",
            payload={"summary": "string", "resources": "object", "driver_result": "object"},
            driver={
                "tool": "openspec",
                "optional": True,
                "fallback": openspec_fallback,
                "produces": "delivery-plan",
            },
        )
        openspec = guidance_for_projection(self._projection(planning))
        self.assertEqual(openspec["driver"]["fallback"], openspec_fallback)
        self.assertIn("machine-readable status", openspec["driver"]["source_confirmation"])
        self.assertIn("semantic normalizer", " ".join(openspec["payload_notes"]))

    def test_assurance_keeps_current_obligation_slices_reuse_and_budgets(self) -> None:
        action = self._action(
            action_id="assurance.execute",
            handler="assurance.dispatch",
            node_id="verify",
            workspace="verifies-source",
            payload={"summary": "string", "assurance_result": "object"},
        )
        current = {
            "obligation_id": "obligation-current",
            "kind": "repository-check",
            "fingerprint": "f" * 64,
            "evidence_contract": {"type": "repository", "command_required": True},
            "repository_ids": ["repo-a"],
            "edges": [],
            "task_change_slice": [{"repository_id": "repo-a", "path": "src/a.py"}],
            "prerequisites": [],
            "driver": "local-command",
        }
        action["current_obligation"] = current
        action["obligation"] = {"obligation_id": "wrong-legacy-field"}
        action["task_change_slice"] = current["task_change_slice"]
        action["assurance"] = {
            "plan_digest": "p" * 64,
            "obligation_states": {"obligation-current": {"remaining": 1}},
            "budget": {
                "remaining": {"verification": 2, "review": 1, "total_action": 5},
            },
            "maximum_remaining_actions": 5,
            "not_required": {"integration": True, "rule": "controller"},
            "reuse_decisions": [{"status": "invalidated"}],
        }
        action["retry_budget"] = {"attempts": 1, "remaining": 1}
        action["review_state"] = {"outcome": "changes-requested"}
        action["verification_coverage"] = {"schema": "dev-flow-verification-coverage/0.4.0"}
        projection = self._projection(action)
        guidance = guidance_for_projection(projection)
        compact = compact_current_action(projection, guidance)
        self.assertEqual(compact["action"]["current_obligation"], current)
        self.assertEqual(compact["action"]["task_change_slice"], current["task_change_slice"])
        self.assertEqual(compact["action"]["assurance"], action["assurance"])
        self.assertEqual(compact["action"]["review_state"], action["review_state"])
        self.assertEqual(compact["action"]["verification_coverage"], action["verification_coverage"])
        rendered = json.dumps(guidance)
        for phrase in (
            "current_obligation",
            "task_change_slice",
            "prerequisites",
            "not-required",
            "budgets",
            "undeclared retry",
            "smallest",
        ):
            self.assertIn(phrase, rendered)

    def test_independent_review_uses_the_controller_guidance_authority(self) -> None:
        action = self._action(
            action_id="assurance.execute",
            handler="assurance.dispatch",
            node_id="verify",
            workspace="verifies-source",
            payload={"summary": "string", "assurance_result": "object"},
        )
        action["current_obligation"] = {
            "obligation_id": "review-current",
            "kind": "independent-review",
            "fingerprint": "f" * 64,
            "evidence_contract": {"type": "review", "independent": True},
            "task_change_slice": [{"repository_id": "repo-a", "path": "src/a.py"}],
            "prerequisites": ["repository-check"],
            "driver": "independent-review",
        }
        action["task_change_slice"] = action["current_obligation"]["task_change_slice"]
        action["assurance"] = {"plan_digest": "p" * 64, "budget": {"remaining": {"review": 1}}}
        action["review_contract"] = {
            "contract_digest": "c" * 64,
            "plan_digest": "p" * 64,
            "manifest_digest": "m" * 64,
            "review_scope_digest": "s" * 64,
            "guidance_digest": INDEPENDENT_REVIEW_GUIDANCE_DIGEST,
            "workspace_digest": "w" * 64,
        }
        projection = self._projection(action)
        first = guidance_for_projection(projection)
        second_projection = self._projection(dict(action))
        second_projection["task_id"] = "another-task"
        second_projection["action"]["binding"] = {"digest": "x" * 64}
        second = guidance_for_projection(second_projection)
        self.assertGuidanceDigest(first)
        self.assertEqual(first["guidance_digest"], INDEPENDENT_REVIEW_GUIDANCE_DIGEST)
        self.assertEqual(second["guidance_digest"], INDEPENDENT_REVIEW_GUIDANCE_DIGEST)
        self.assertEqual(engine.INDEPENDENT_REVIEW_GUIDANCE_DIGEST, INDEPENDENT_REVIEW_GUIDANCE_DIGEST)
        rendered = json.dumps(first)
        for phrase in (
            "genuinely separate reviewer context",
            "every repository member",
            "dev-flow-review-finding/0.4.0",
            "fresh aggregate workspace digest",
            "Self-review",
            "Controller remains verdict authority",
        ):
            self.assertIn(phrase, rendered)

        stale = dict(action)
        stale["review_contract"] = {**action["review_contract"], "guidance_digest": "0" * 64}
        with self.assertRaises(DevFlowError) as caught:
            guidance_for_projection(self._projection(stale))
        self.assertEqual(caught.exception.code, "MCP_PROJECTION_INVALID")

    def test_terminal_dossier_manifest_and_result_budgets_fail_closed(self) -> None:
        projection = self._projection(None, done=True)
        guidance = guidance_for_projection(projection)
        compact = compact_current_action(projection, guidance)
        self.assertIsNone(compact["action"])
        self.assertEqual(compact["terminal"]["dossier"], projection["dossier"])
        self.assertIn("no executable action", " ".join(guidance["payload_notes"]).lower())
        self.assertGuidanceDigest(guidance)

        for field in (
            "action.current_obligation",
            "action.task_change_slice",
            "action.assurance",
            "action.review_state",
            "action.review_contract",
            "action.verification_coverage",
            "action.binding",
            "repository_set.workspace_snapshot_digest",
            "inputs",
            "resources",
            "terminal.dossier",
        ):
            self.assertIn(field, FIELD_USE_MANIFEST)
            self.assertTrue(FIELD_USE_MANIFEST[field])

        oversized_action = self._action(
            action_id="implementation.record",
            workspace="produces-source",
            payload={"summary": "string"},
        )
        oversized_action["inputs"] = [
            {"type": "impact-report", "edge": "governing", "summary": "x" * MCP_CURRENT_ACTION_MAX_BYTES}
        ]
        oversized_projection = self._projection(oversized_action)
        oversized_guidance = guidance_for_projection(oversized_projection)
        with self.assertRaises(DevFlowError) as caught:
            compact_current_action(oversized_projection, oversized_guidance)
        self.assertEqual(caught.exception.code, "MCP_RESULT_LIMIT")
        self.assertIn("Do not execute", caught.exception.details["recovery"])


if __name__ == "__main__":
    unittest.main()
