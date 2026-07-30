from __future__ import annotations

import argparse
import ast
import contextlib
import inspect
import json
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import dev_flow


FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "workflow_legacy"
EDGE_FIXTURE = FIXTURE_ROOT / "edges.jsonl"
MANIFEST_FIXTURE = FIXTURE_ROOT / "manifest.json"
PRISTINE_SUITE_FIXTURE = FIXTURE_ROOT / "pristine_full_suite.json"


def _flatten_edges(edges: dict[str, set[str]]) -> set[tuple[str, str]]:
    return {
        (source, target)
        for source, targets in edges.items()
        for target in targets
    }


def _commit_batches(function: object) -> set[tuple[str, ...]]:
    """Return literal durable event batches declared by one production command."""

    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    batches: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        called_name = (
            called.id
            if isinstance(called, ast.Name)
            else called.attr
            if isinstance(called, ast.Attribute)
            else None
        )
        if called_name != "_commit_state" or len(node.args) < 4:
            continue
        primary = node.args[3]
        if not isinstance(primary, ast.Constant) or not isinstance(
            primary.value, str
        ):
            continue
        events = [primary.value]
        additional = next(
            (
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "additional_events"
            ),
            None,
        )
        if additional is not None:
            candidates: list[str] = []
            for candidate in ast.walk(additional):
                if (
                    isinstance(candidate, ast.Tuple)
                    and len(candidate.elts) == 2
                    and isinstance(candidate.elts[0], ast.Constant)
                    and isinstance(candidate.elts[0].value, str)
                    and isinstance(candidate.elts[1], ast.Dict)
                ):
                    candidates.append(candidate.elts[0].value)
            events.extend(dict.fromkeys(candidates))
        batches.add(tuple(events))
    return batches


def _approval_pop_labels(function: object) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    labels: set[str] = set()
    mapping = {
        "baseline-fetch": "baseline-fetch-approval",
        dev_flow.LITE_GATE: "lite-approval",
        "route": "route-approval",
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "pop"
            and node.args
        ):
            argument = node.args[0]
            gate = (
                argument.value
                if isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                else dev_flow.LITE_GATE
                if isinstance(argument, ast.Name)
                and argument.id == "LITE_GATE"
                else None
            )
            if gate in mapping:
                labels.add(mapping[gate])
    return labels


class WorkflowLegacyGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(
            MANIFEST_FIXTURE.read_text(encoding="utf-8")
        )
        cls.pristine_suite = json.loads(
            PRISTINE_SUITE_FIXTURE.read_text(encoding="utf-8")
        )
        edge_fields = cls.manifest["edge_record_fields"]
        contract_fields = cls.manifest["schema_contract_fields"]
        cls.edges = []
        for line in EDGE_FIXTURE.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            packed = dict(zip(edge_fields, json.loads(line)))
            packed["v1"] = dict(zip(contract_fields, packed["v1"]))
            packed["v2"] = dict(zip(contract_fields, packed["v2"]))
            cls.edges.append(packed)

    def test_pristine_full_suite_is_accounted_without_blessing_failures(
        self,
    ) -> None:
        report = self.pristine_suite
        self.assertEqual(
            report["base_commit"],
            "2dc397411ad1ea5f2a43d43e881523b125bb5eec",
        )
        self.assertEqual(report["observed"]["tests"], 226)
        self.assertEqual(report["observed"]["skipped"], 5)
        for kind in ("failure", "error"):
            observed_key = f"{kind}s"
            self.assertEqual(
                sum(
                    item["count"]
                    for item in report["triage"]
                    if item["kind"] == kind
                ),
                report["observed"][observed_key],
            )
        self.assertTrue(
            all(
                item["repair_files"]
                and all(
                    (Path(__file__).resolve().parents[1] / path).is_file()
                    for path in item["repair_files"]
                )
                for item in report["triage"]
            )
        )
        self.assertIn(
            "No failing behavior is accepted",
            report["triage_policy"],
        )

    def test_manifest_and_every_edge_record_are_complete(self) -> None:
        self.assertEqual(self.manifest["base_commit"], "2dc3974")
        self.assertEqual(self.manifest["edge_count"], len(self.edges))
        self.assertEqual(len(self.edges), 109)
        self.assertEqual(
            len({edge["id"] for edge in self.edges}), len(self.edges)
        )
        for edge in self.edges:
            with self.subTest(edge=edge["id"]):
                self.assertIn(edge["flow"], dev_flow.FLOW_MODES)
                self.assertIn(
                    edge["kind"],
                    {
                        "forward",
                        "rework",
                        "blocking",
                        "resume",
                        "cancellation",
                    },
                )
                self.assertIsInstance(edge["invalidation"], list)
                for schema in ("v1", "v2"):
                    contract = edge[schema]
                    self.assertEqual(
                        set(contract),
                        {
                            "supported",
                            "confirmation",
                            "revision_delta",
                            "events",
                            "transaction",
                        },
                    )
                    if contract["supported"]:
                        self.assertEqual(contract["revision_delta"], 1)
                        self.assertTrue(contract["events"])
                        self.assertEqual(
                            contract["transaction"],
                            (
                                "same-revision"
                                if len(contract["events"]) > 1
                                else "single-event"
                            ),
                        )

    def test_forward_rework_and_automatic_edges_match_production_constants(
        self,
    ) -> None:
        for flow, forward, rework in (
            ("full", dev_flow.FORWARD_EDGES, dev_flow.REWORK_EDGES),
            (
                "lite",
                dev_flow.LITE_FORWARD_EDGES,
                dev_flow.LITE_REWORK_EDGES,
            ),
        ):
            golden_forward = {
                (edge["from"], edge["to"])
                for edge in self.edges
                if edge["flow"] == flow and edge["kind"] == "forward"
            }
            golden_rework = {
                (edge["from"], edge["to"])
                for edge in self.edges
                if edge["flow"] == flow and edge["kind"] == "rework"
            }
            self.assertEqual(golden_forward, _flatten_edges(forward))
            self.assertEqual(golden_rework, _flatten_edges(rework))

        golden_automatic_transitions = {
            (edge["flow"], edge["from"], edge["to"])
            for edge in self.edges
            if edge["trigger"] == "transition"
            and edge["v2"]["confirmation"] == "automatic"
        }
        self.assertEqual(
            golden_automatic_transitions,
            set(dev_flow.AUTOMATIC_TRANSITION_EDGES),
        )
        golden_automatic_actions = {
            (edge["flow"], edge["trigger"], edge["from"], edge["to"])
            for edge in self.edges
            if edge["trigger"] not in {"transition", "transition-cancel"}
            and edge["v2"]["confirmation"] == "automatic"
        }
        self.assertEqual(
            golden_automatic_actions,
            set(dev_flow.AUTOMATIC_ACTION_EDGES),
        )

    def test_block_resume_and_both_cancellation_surfaces_are_exhaustive(
        self,
    ) -> None:
        for flow, ordered in (
            ("full", dev_flow.ORDERED_STATES),
            ("lite", dev_flow.LITE_ORDERED_STATES),
        ):
            nonterminal = set(ordered[:-1])
            manual_blocks = {
                edge["from"]
                for edge in self.edges
                if edge["flow"] == flow
                and edge["kind"] == "blocking"
                and edge["trigger"] == "transition"
            }
            manual_resumes = {
                edge["to"]
                for edge in self.edges
                if edge["flow"] == flow
                and edge["kind"] == "resume"
                and edge["trigger"] == "transition"
            }
            self.assertEqual(manual_blocks, nonterminal)
            self.assertEqual(manual_resumes, nonterminal)
            for trigger in ("cancel", "transition-cancel"):
                sources = {
                    edge["from"]
                    for edge in self.edges
                    if edge["flow"] == flow
                    and edge["kind"] == "cancellation"
                    and edge["trigger"] == trigger
                }
                self.assertEqual(sources, nonterminal | {"BLOCKED"})

        preflight_edges = {
            (
                edge["flow"],
                edge["kind"],
                edge["from"],
                edge["to"],
            )
            for edge in self.edges
            if edge["trigger"] == "preflight"
            and edge["to"] == "BLOCKED"
            or edge["trigger"] == "preflight"
            and edge["from"] == "BLOCKED"
        }
        self.assertEqual(
            preflight_edges,
            {
                (flow, "blocking", source, "BLOCKED")
                for flow in dev_flow.FLOW_MODES
                for source in ("INTAKE", "PREFLIGHTED")
            }
            | {
                (flow, "resume", "BLOCKED", "PREFLIGHTED")
                for flow in dev_flow.FLOW_MODES
            },
        )
        risk_edges = {
            (edge["from"], edge["trigger"].split(":", 1)[1])
            for edge in self.edges
            if edge["trigger"].startswith("lite-risk:")
        }
        self.assertEqual(
            risk_edges,
            {
                ("IMPLEMENTING", "VERIFYING"),
                ("VERIFYING", "DONE"),
            },
        )

    def test_transition_confirmation_modes_match_production(self) -> None:
        for edge in self.edges:
            if edge["trigger"] not in {
                "transition",
                "transition-cancel",
                "cancel",
            }:
                continue
            action = "cancel" if edge["trigger"] == "cancel" else "transition"
            for version, key in ((1, "v1"), (2, "v2")):
                state = {
                    "schema_version": version,
                    "confirmation_contract_version": (
                        dev_flow.CONFIRMATION_CONTRACT_VERSION
                        if version == 2
                        else None
                    ),
                    "flow": edge["flow"],
                }
                actual = dev_flow._transition_confirmation_mode(
                    state,
                    edge["from"],
                    edge["to"],
                    action=action,
                )
                self.assertEqual(
                    actual,
                    edge[key]["confirmation"],
                    edge["id"],
                )

    def test_event_batches_are_declared_by_real_command_implementations(
        self,
    ) -> None:
        functions = {
            "preflight": dev_flow.command_preflight,
            "baseline": dev_flow.command_baseline,
            "record-index": dev_flow.command_record_index,
            "set-route": dev_flow.command_set_route,
            "approve-route": dev_flow.command_approve,
            "prepare-workspace": dev_flow.command_prepare_workspace,
            "review-snapshot": dev_flow.command_review_snapshot,
            "transition": dev_flow.command_transition,
            "transition-cancel": dev_flow.command_transition,
            "cancel": dev_flow.command_cancel,
        }
        declared = {
            trigger: _commit_batches(function)
            for trigger, function in functions.items()
        }
        for edge in self.edges:
            trigger = (
                "transition"
                if edge["trigger"].startswith("lite-risk:")
                else edge["trigger"]
            )
            for schema in ("v1", "v2"):
                contract = edge[schema]
                if not contract["supported"]:
                    continue
                events = tuple(contract["events"])
                self.assertTrue(
                    any(
                        events == batch or events == batch[:1]
                        for batch in declared[trigger]
                    ),
                    (edge["id"], schema, events, declared[trigger]),
                )

    def _transition_state(self, edge: dict[str, object]) -> dict[str, object]:
        source = str(edge["from"])
        resume_target = str(edge["to"])
        return {
            "schema_version": 1,
            "task_id": "golden-task",
            "revision": 11,
            "status": source,
            "flow": edge["flow"],
            "workspace": {
                "strategy": (
                    "worktree" if edge["flow"] == "full" else "in-place"
                ),
                "ready": True,
                "generation": 7,
                "plan": {"id": "old-plan"},
            },
            "repositories": [
                {
                    "id": "repo",
                    "path": "/workspace/repo",
                    "workspace": {"path": "/workspace/managed", "ready": True},
                    "workspace_index": {"index_id": "old-workspace-index"},
                }
            ],
            "approvals": {
                "route": {"approval_id": "route"},
                "workspace": {"approval_id": "workspace"},
                "plan": {"approval_id": "plan"},
                "review": {"approval_id": "review"},
            },
            "review_snapshots": [{"snapshot_id": "review"}],
            "route": {"value": "direct"},
            "planning_generation": 3,
            "impact_generation": 5,
            "blocked": (
                {
                    "phase": "manual",
                    "from_status": resume_target,
                    "reason": "golden blocker",
                }
                if source == "BLOCKED"
                else None
            ),
            "cancelled": None,
        }

    def _observed_invalidations(
        self, before: dict[str, object], after: dict[str, object]
    ) -> set[str]:
        observed: set[str] = set()
        if after.get("planning_generation") != before.get(
            "planning_generation"
        ):
            observed.add("planning-generation")
        if after.get("impact_generation") != before.get("impact_generation"):
            observed.add("impact-generation")
        if before.get("route") is not None and after.get("route") is None:
            observed.add("route")
        gate_labels = {
            "route": "route-approval",
            "workspace": "workspace-approval",
            "plan": "plan-approval",
            "review": "review-approval",
        }
        before_approvals = before["approvals"]
        after_approvals = after["approvals"]
        assert isinstance(before_approvals, dict)
        assert isinstance(after_approvals, dict)
        for gate, label in gate_labels.items():
            if gate in before_approvals and gate not in after_approvals:
                observed.add(label)
        if before.get("review_snapshots") and not after.get(
            "review_snapshots"
        ):
            observed.add("review-snapshots")
        before_repositories = before["repositories"]
        after_repositories = after["repositories"]
        assert isinstance(before_repositories, list)
        assert isinstance(after_repositories, list)
        if any(
            old.get("workspace") is not None
            and new.get("workspace") is None
            for old, new in zip(before_repositories, after_repositories)
        ):
            observed.add("repository-workspaces")
        if any(
            old.get("workspace_index") is not None
            and new.get("workspace_index") is None
            for old, new in zip(before_repositories, after_repositories)
        ):
            observed.add("repository-workspace-indexes")
        before_workspace = before["workspace"]
        after_workspace = after["workspace"]
        assert isinstance(before_workspace, dict)
        assert isinstance(after_workspace, dict)
        if before_workspace.get("generation") != after_workspace.get(
            "generation"
        ):
            observed.add("task-workspace-generation")
        return observed

    def test_real_legacy_transition_execution_matches_every_pure_edge(
        self,
    ) -> None:
        for edge in self.edges:
            if edge["trigger"] not in {"transition", "transition-cancel"}:
                continue
            before = self._transition_state(edge)
            committed: list[tuple[dict[str, object], str]] = []

            @contextlib.contextmanager
            def locked(*_args: object, **_kwargs: object):
                yield Path("/unused"), before

            def commit(
                _old: dict[str, object],
                new: dict[str, object],
                _task_dir: Path,
                event_type: str,
                _payload: dict[str, object],
                **_kwargs: object,
            ) -> dict[str, object]:
                new["revision"] = int(_old["revision"]) + 1
                committed.append((new, event_type))
                return {}

            args = argparse.Namespace(
                task_option="golden-task",
                task_id=None,
                data_dir=None,
                expected_revision=11,
                to_option=edge["to"],
                to=None,
                note="golden note",
                preview=False,
                confirm_intent=None,
            )
            with (
                mock.patch.object(dev_flow, "_locked_state", locked),
                mock.patch.object(
                    dev_flow, "_transition_guard", return_value=None
                ),
                mock.patch.object(
                    dev_flow,
                    "_current_repository_fingerprints",
                    return_value={},
                ),
                mock.patch.object(dev_flow, "_commit_state", commit),
                mock.patch.object(
                    dev_flow,
                    "_result",
                    side_effect=lambda _command, state, **_extra: state,
                ),
            ):
                after = dev_flow.command_transition(args)
            self.assertEqual(len(committed), 1, edge["id"])
            self.assertEqual(committed[0][1], "state_transitioned")
            self.assertEqual(after["status"], edge["to"], edge["id"])
            self.assertEqual(
                int(after["revision"]) - int(before["revision"]),
                edge["v1"]["revision_delta"],
                edge["id"],
            )
            self.assertEqual(
                self._observed_invalidations(before, after),
                set(edge["invalidation"]),
                edge["id"],
            )

    def test_action_invalidations_and_special_blocking_execute_in_production(
        self,
    ) -> None:
        self.assertEqual(
            _approval_pop_labels(dev_flow.command_preflight),
            {"baseline-fetch-approval", "lite-approval"},
        )
        self.assertEqual(
            _approval_pop_labels(dev_flow.command_set_route),
            {"route-approval"},
        )
        action_invalidations = {
            trigger: {
                invalidation
                for edge in self.edges
                if edge["trigger"] == trigger
                for invalidation in edge["invalidation"]
            }
            for trigger in ("preflight", "set-route")
        }
        self.assertEqual(
            action_invalidations["preflight"],
            _approval_pop_labels(dev_flow.command_preflight),
        )
        self.assertEqual(
            action_invalidations["set-route"],
            _approval_pop_labels(dev_flow.command_set_route),
        )

        for source in ("INTAKE", "PREFLIGHTED"):
            current = {"status": source}
            candidate = {"status": source, "blocked": None}
            dev_flow._apply_preflight_outcome(
                current,
                candidate,
                selection_complete=True,
                all_checked=True,
                blockers=[{"repository_id": "repo", "blockers": ["dirty"]}],
            )
            self.assertEqual(candidate["status"], "BLOCKED")
            self.assertEqual(candidate["blocked"]["phase"], "preflight")
            self.assertEqual(candidate["blocked"]["from_status"], source)

        current = {
            "status": "BLOCKED",
            "blocked": {"phase": "preflight", "from_status": "INTAKE"},
        }
        candidate = {"status": "BLOCKED", "blocked": current["blocked"]}
        dev_flow._apply_preflight_outcome(
            current,
            candidate,
            selection_complete=True,
            all_checked=True,
            blockers=[],
        )
        self.assertEqual(candidate, {"status": "PREFLIGHTED", "blocked": None})

    def test_lite_risk_edges_commit_one_same_revision_batch(self) -> None:
        risk_edges = [
            edge
            for edge in self.edges
            if edge["trigger"].startswith("lite-risk:")
        ]
        for edge in risk_edges:
            attempted_target = edge["trigger"].split(":", 1)[1]
            current = self._transition_state(
                {
                    **edge,
                    "from": edge["from"],
                    "to": attempted_target,
                    "flow": "lite",
                }
            )
            current.update(
                {
                    "schema_version": 2,
                    "confirmation_contract_version": 1,
                    "status": edge["from"],
                    "flow": "lite",
                }
            )
            captured: dict[str, object] = {}

            @contextlib.contextmanager
            def locked(*_args: object, **_kwargs: object):
                yield Path("/unused"), current

            def commit(
                old: dict[str, object],
                new: dict[str, object],
                _task_dir: Path,
                event_type: str,
                _payload: dict[str, object],
                *,
                additional_events: list[tuple[str, dict[str, object]]],
            ) -> dict[str, object]:
                new["revision"] = int(old["revision"]) + 1
                captured["state"] = new
                captured["events"] = [
                    event_type,
                    *[item[0] for item in additional_events],
                ]
                return {}

            args = argparse.Namespace(
                task_option="golden-task",
                task_id=None,
                data_dir=None,
                expected_revision=11,
                to_option=attempted_target,
                to=None,
                note="golden",
                preview=False,
                confirm_intent=None,
            )
            assessment = {
                "decision": "requires_full",
                "reasons": [{"code": "protected_path"}],
                "sha256": "a" * 64,
            }
            with (
                mock.patch.object(dev_flow, "_locked_state", locked),
                mock.patch.object(
                    dev_flow,
                    "_capture_lite_change_assessment",
                    return_value=(assessment, {}),
                ),
                mock.patch.object(dev_flow, "_commit_state", commit),
                mock.patch.object(
                    dev_flow,
                    "_result",
                    side_effect=lambda _command, state, **_extra: state,
                ),
            ):
                result = dev_flow.command_transition(args)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["blocked"]["phase"], "lite-risk")
            self.assertEqual(captured["events"], edge["v2"]["events"])
            self.assertEqual(
                int(result["revision"]) - int(current["revision"]), 1
            )

    def test_real_commit_outbox_matches_every_schema_event_contract(
        self,
    ) -> None:
        for edge in self.edges:
            for schema_version, key in ((1, "v1"), (2, "v2")):
                contract = edge[key]
                if not contract["supported"]:
                    continue
                events = contract["events"]
                old = {
                    "schema_version": schema_version,
                    "task_id": "golden-task",
                    "revision": 41,
                    "status": edge["from"],
                }
                new = {
                    **old,
                    "status": edge["to"],
                }
                with (
                    mock.patch.object(
                        dev_flow, "_atomic_write_json", return_value=None
                    ),
                    mock.patch.object(
                        dev_flow, "_flush_pending_event", return_value=None
                    ),
                    mock.patch.object(
                        dev_flow,
                        "_complete_mutation_intent",
                        return_value=None,
                    ),
                    mock.patch.object(
                        dev_flow,
                        "utc_now",
                        return_value="2026-07-27T00:00:00.000Z",
                    ),
                    mock.patch.object(
                        dev_flow,
                        "resolve_loaded_task_workflow",
                        return_value={},
                    ),
                ):
                    dev_flow._commit_state(
                        old,
                        new,
                        Path("/unused"),
                        events[0],
                        {},
                        additional_events=[
                            (event_type, {}) for event_type in events[1:]
                        ],
                    )
                self.assertEqual(
                    new["revision"] - old["revision"],
                    contract["revision_delta"],
                    (edge["id"], key),
                )
                stored = (
                    new["pending_events"]
                    if len(events) > 1
                    else [new["pending_event"]]
                )
                self.assertEqual(
                    [event["type"] for event in stored],
                    events,
                    (edge["id"], key),
                )
                self.assertEqual(
                    {event["revision"] for event in stored}, {42}
                )
                self.assertEqual(
                    {event["previous_revision"] for event in stored}, {41}
                )
                transaction_ids = {
                    event.get("transaction_id") for event in stored
                }
                if len(events) > 1:
                    self.assertEqual(len(transaction_ids), 1)
                    self.assertNotIn(None, transaction_ids)
                else:
                    self.assertEqual(transaction_ids, {None})


if __name__ == "__main__":
    unittest.main()
