from __future__ import annotations

import concurrent.futures
import errno
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "node_telemetry.py"
)
REPRESENTATIVE_REPORT_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "telemetry"
    / "representative_workflows.json"
)
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_node_telemetry_tests", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
telemetry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = telemetry
SPEC.loader.exec_module(telemetry)


def record(
    *,
    task_id: str = "task-a",
    node_instance_id: str = "node-a",
    repository_id: str | None = "repo-a",
    revision: int = 7,
    attempt: int = 1,
    role: str = "worker",
    adapter_outcome: str = "SUCCEEDED",
    evidence_outcome: str = "SUCCEEDED",
    duration_ms: int = 100,
    usage: object = None,
) -> object:
    return telemetry.build_node_telemetry(
        task_id=task_id,
        bundle_sha256="a" * 64,
        node_instance_id=node_instance_id,
        repository_id=repository_id,
        revision=revision,
        attempt=attempt,
        executor_policy="executor.codex-exec/v1",
        model_policy="balanced",
        orchestration_role=role,
        adapter_outcome=adapter_outcome,
        evidence_outcome=evidence_outcome,
        started_at="2026-07-27T00:00:00.000Z",
        ended_at="2026-07-27T00:00:00.100Z",
        duration_ms=duration_ms,
        response_bytes=120,
        artifact_bytes=900,
        usage=usage,
    )


def task_observation_snapshot(task_dir: Path) -> object:
    files = tuple(
        (
            str(path.relative_to(task_dir)),
            path.read_bytes(),
        )
        for path in sorted(task_dir.rglob("*"))
        if path.is_file()
    )
    state = json.loads(
        (task_dir / "state.json").read_text(encoding="utf-8")
    )
    return (
        files,
        state["revision"],
        state["pending_event"],
        state["guards"],
        state["readiness"],
        state["plan"]["current"],
    )


class NodeTelemetryTests(unittest.TestCase):
    def test_representative_workflow_reports_match_committed_baseline(
        self,
    ) -> None:
        def item(
            *,
            task_id: str,
            node_instance_id: str,
            repository_id: str | None,
            role: str,
            attempt: int,
            outcome: str,
            duration_ms: int,
            input_tokens: int,
            cached_input_tokens: int,
            output_tokens: int,
            reasoning_output_tokens: int,
        ) -> object:
            return record(
                task_id=task_id,
                node_instance_id=node_instance_id,
                repository_id=repository_id,
                role=role,
                attempt=attempt,
                adapter_outcome=outcome,
                evidence_outcome=outcome,
                duration_ms=duration_ms,
                usage={
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached_input_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_output_tokens": reasoning_output_tokens,
                },
            )

        single = (
            item(
                task_id="single-full",
                node_instance_id="manager",
                repository_id=None,
                role="manager",
                attempt=1,
                outcome="SUCCEEDED",
                duration_ms=80,
                input_tokens=40,
                cached_input_tokens=20,
                output_tokens=10,
                reasoning_output_tokens=5,
            ),
            item(
                task_id="single-full",
                node_instance_id="implementation",
                repository_id="repo-a",
                role="worker",
                attempt=1,
                outcome="SUCCEEDED",
                duration_ms=600,
                input_tokens=300,
                cached_input_tokens=200,
                output_tokens=60,
                reasoning_output_tokens=30,
            ),
            item(
                task_id="single-full",
                node_instance_id="review",
                repository_id="repo-a",
                role="worker",
                attempt=1,
                outcome="SUCCEEDED",
                duration_ms=250,
                input_tokens=100,
                cached_input_tokens=50,
                output_tokens=25,
                reasoning_output_tokens=10,
            ),
        )
        parallel = (
            item(
                task_id="multi-full",
                node_instance_id="manager",
                repository_id=None,
                role="manager",
                attempt=1,
                outcome="SUCCEEDED",
                duration_ms=100,
                input_tokens=100,
                cached_input_tokens=70,
                output_tokens=30,
                reasoning_output_tokens=15,
            ),
            item(
                task_id="multi-full",
                node_instance_id="repo-a",
                repository_id="repo-a",
                role="worker",
                attempt=1,
                outcome="SUCCEEDED",
                duration_ms=800,
                input_tokens=400,
                cached_input_tokens=300,
                output_tokens=80,
                reasoning_output_tokens=40,
            ),
            item(
                task_id="multi-full",
                node_instance_id="repo-b",
                repository_id="repo-b",
                role="worker",
                attempt=1,
                outcome="FAILED",
                duration_ms=700,
                input_tokens=350,
                cached_input_tokens=200,
                output_tokens=70,
                reasoning_output_tokens=35,
            ),
            item(
                task_id="multi-full",
                node_instance_id="repo-b",
                repository_id="repo-b",
                role="worker",
                attempt=2,
                outcome="SUCCEEDED",
                duration_ms=650,
                input_tokens=300,
                cached_input_tokens=220,
                output_tokens=65,
                reasoning_output_tokens=30,
            ),
            item(
                task_id="multi-full",
                node_instance_id="integration",
                repository_id=None,
                role="worker",
                attempt=1,
                outcome="SUCCEEDED",
                duration_ms=300,
                input_tokens=160,
                cached_input_tokens=100,
                output_tokens=40,
                reasoning_output_tokens=20,
            ),
        )
        actual = {
            "schema": (
                "dev-flow-representative-telemetry-baselines/v1"
            ),
            "measurement": (
                "Adapter-reported token counts and controller-observed "
                "integer milliseconds; deterministic representative "
                "fixture, observational only."
            ),
            "single_repository_full": json.loads(
                json.dumps(
                    dict(
                        telemetry.build_node_telemetry_report(
                            single,
                            successful_task_ids=("single-full",),
                            single_agent_baseline_tokens=560,
                            observed_wall_time_ms=930,
                            single_agent_baseline_wall_time_ms=1120,
                            accepted_results=2,
                            evaluated_results=2,
                        )
                    )
                )
            ),
            "multi_repository_parallel": json.loads(
                json.dumps(
                    dict(
                        telemetry.build_node_telemetry_report(
                            parallel,
                            successful_task_ids=("multi-full",),
                            single_agent_baseline_tokens=1400,
                            observed_wall_time_ms=1150,
                            single_agent_baseline_wall_time_ms=2450,
                            accepted_results=3,
                            evaluated_results=4,
                        )
                    )
                )
            ),
        }
        expected = json.loads(
            REPRESENTATIVE_REPORT_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(actual, expected)

    def test_complete_usage_is_exact_attempt_scoped_and_immutable(
        self,
    ) -> None:
        item = record(
            usage={
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 20,
                "reasoning_output_tokens": 10,
            }
        )

        self.assertEqual(
            item.schema, "dev-flow-node-telemetry/v1"
        )
        self.assertEqual(item.task_id, "task-a")
        self.assertEqual(item.repository_id, "repo-a")
        self.assertEqual(item.revision, 7)
        self.assertEqual(item.attempt, 1)
        self.assertEqual(item.usage["status"], "available")
        self.assertEqual(item.usage["cached_input_tokens"], 40)
        with self.assertRaises(TypeError):
            item.usage["input_tokens"] = 0
        self.assertEqual(
            json.loads(json.dumps(item.as_dict())),
            item.as_dict(),
        )

    def test_unavailable_usage_does_not_invalidate_result(self) -> None:
        item = record(usage=None)

        self.assertEqual(item.evidence_outcome, "SUCCEEDED")
        self.assertEqual(item.usage["status"], "unavailable")
        self.assertEqual(item.diagnostics, ())

    def test_malformed_and_contradictory_counts_become_diagnostics(
        self,
    ) -> None:
        cases = (
            {"input_tokens": -1},
            {
                "input_tokens": 2,
                "cached_input_tokens": 3,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
            },
            {
                "input_tokens": 2,
                "cached_input_tokens": 1,
                "output_tokens": 1,
                "reasoning_output_tokens": 2,
            },
            {
                "input_tokens": True,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
            },
        )
        for supplied in cases:
            with self.subTest(supplied=supplied):
                item = record(usage=supplied)
                self.assertEqual(
                    item.usage["status"], "unavailable"
                )
                self.assertTrue(item.diagnostics)
                self.assertEqual(
                    item.evidence_outcome, "SUCCEEDED"
                )

    def test_adapter_success_cannot_override_failed_evidence(self) -> None:
        item = record(
            adapter_outcome="SUCCEEDED",
            evidence_outcome="FAILED",
            usage={
                "input_tokens": 30,
                "cached_input_tokens": 0,
                "output_tokens": 5,
                "reasoning_output_tokens": 2,
            },
        )

        self.assertEqual(item.evidence_outcome, "FAILED")
        self.assertEqual(
            item.diagnostics[-1]["code"],
            "TELEMETRY_EVIDENCE_OUTCOME_CONFLICT",
        )
        self.assertEqual(
            item.diagnostics[-1]["authoritative"],
            "evidence_outcome",
        )

    def test_record_identity_is_content_addressed_and_deterministic(
        self,
    ) -> None:
        supplied = {
            "input_tokens": 11,
            "cached_input_tokens": 1,
            "output_tokens": 3,
            "reasoning_output_tokens": 2,
        }
        first = record(usage=supplied)
        second = record(usage=dict(reversed(tuple(supplied.items()))))

        self.assertEqual(first.telemetry_id, second.telemetry_id)
        self.assertTrue(
            first.telemetry_id.startswith(
                "dev-flow-node-telemetry/v1:"
            )
        )

    def test_store_uses_independent_lock_and_atomic_idempotent_creation(
        self,
    ) -> None:
        item = record(
            usage={
                "input_tokens": 11,
                "cached_input_tokens": 1,
                "output_tokens": 3,
                "reasoning_output_tokens": 2,
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=8
            ) as executor:
                results = tuple(
                    executor.map(
                        lambda _: telemetry.write_node_telemetry_record(
                            data_dir, item
                        ),
                        range(8),
                    )
                )

            self.assertEqual(
                sum(result.status == "created" for result in results),
                1,
            )
            self.assertEqual(
                sum(result.status == "existing" for result in results),
                7,
            )
            self.assertTrue(all(result.persisted for result in results))
            self.assertEqual(
                len({result.path for result in results}), 1
            )
            path = Path(str(results[0].path))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                item.as_dict(),
            )
            self.assertTrue(
                (data_dir / "telemetry" / "node.lock").is_file()
            )
            self.assertEqual(
                len(
                    tuple(
                        (data_dir / "telemetry" / "node").rglob(
                            "*.json"
                        )
                    )
                ),
                1,
            )

    def test_store_rejects_noncanonical_record_without_writing(self) -> None:
        item = record()
        forged = (
            replace(
                item,
                telemetry_id=(
                    "dev-flow-node-telemetry/v1:" + ("0" * 64)
                ),
            ),
            replace(item, revision=-1),
            replace(
                item,
                diagnostics=(
                    {
                        "code": "TELEMETRY_EVIDENCE_OUTCOME_CONFLICT",
                        "authoritative": "adapter_outcome",
                    },
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            for candidate in forged:
                with self.subTest(candidate=candidate):
                    result = telemetry.write_node_telemetry_record(
                        data_dir, candidate
                    )
                    self.assertEqual(result.status, "diagnostic")
                    self.assertEqual(
                        result.diagnostic["code"],
                        "TELEMETRY_RECORD_REJECTED",
                    )
            self.assertFalse(
                (data_dir / "telemetry" / "node").exists()
            )

    @unittest.skipIf(
        os.name == "nt",
        "symlink creation is not guaranteed for unprivileged Windows tests",
    )
    def test_store_never_follows_lock_or_record_symlinks(self) -> None:
        item = record()
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            telemetry_root = data_dir / "telemetry"
            telemetry_root.mkdir()
            target = data_dir / "unrelated.txt"
            target.write_bytes(b"do-not-touch")
            lock_path = telemetry_root / "node.lock"
            lock_path.symlink_to(target)

            rejected_lock = telemetry.write_node_telemetry_record(
                data_dir, item
            )
            self.assertEqual(rejected_lock.status, "diagnostic")
            self.assertEqual(target.read_bytes(), b"do-not-touch")

            lock_path.unlink()
            created = telemetry.write_node_telemetry_record(
                data_dir, item
            )
            self.assertEqual(created.status, "created")
            record_path = Path(str(created.path))
            record_path.unlink()
            record_path.symlink_to(target)

            rejected_record = telemetry.write_node_telemetry_record(
                data_dir, item
            )
            self.assertEqual(rejected_record.status, "diagnostic")
            self.assertEqual(target.read_bytes(), b"do-not-touch")

    def test_accepted_and_rejected_store_writes_never_change_task(
        self,
    ) -> None:
        item = record()
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            task_dir = data_dir / "tasks" / "task-a"
            task_dir.mkdir(parents=True)
            state = {
                "task_id": "task-a",
                "revision": 23,
                "pending_event": {
                    "event_id": "event-23",
                    "revision": 23,
                },
                "guards": {
                    "source-confirmed": True,
                    "review-approved": False,
                },
                "readiness": {
                    "ready": False,
                    "blockers": ["review-approved"],
                },
                "plan": {
                    "current": True,
                    "digest": "b" * 64,
                },
            }
            (task_dir / "state.json").write_text(
                json.dumps(state, sort_keys=True),
                encoding="utf-8",
            )
            (task_dir / "events.jsonl").write_text(
                '{"event_id":"event-22","revision":22}\n',
                encoding="utf-8",
            )
            before = task_observation_snapshot(task_dir)

            with mock.patch.object(
                telemetry,
                "_persist_state_transaction",
                side_effect=AssertionError(
                    "telemetry must not call the task commit service"
                ),
                create=True,
            ), mock.patch.object(
                telemetry,
                "_flush_pending_event",
                side_effect=AssertionError(
                    "telemetry must not call the durable outbox"
                ),
                create=True,
            ):
                created = telemetry.write_node_telemetry_record(
                    data_dir, item
                )
                self.assertEqual(created.status, "created")
                self.assertEqual(
                    task_observation_snapshot(task_dir), before
                )

                replayed = telemetry.write_node_telemetry_record(
                    data_dir, item
                )
                self.assertEqual(replayed.status, "existing")
                self.assertEqual(
                    task_observation_snapshot(task_dir), before
                )

                record_path = Path(str(created.path))
                conflicting = item.as_dict()
                conflicting["response_bytes"] = (
                    int(conflicting["response_bytes"]) + 1
                )
                record_path.write_bytes(
                    json.dumps(
                        conflicting,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    + b"\n"
                )
                conflict = telemetry.write_node_telemetry_record(
                    data_dir, item
                )
                self.assertEqual(conflict.status, "diagnostic")
                self.assertEqual(
                    conflict.diagnostic["code"],
                    "TELEMETRY_STORE_CONFLICT",
                )
                self.assertEqual(
                    task_observation_snapshot(task_dir), before
                )

                record_path.write_bytes(b"{")
                corrupt = telemetry.write_node_telemetry_record(
                    data_dir, item
                )
                self.assertEqual(corrupt.status, "diagnostic")
                self.assertEqual(
                    corrupt.diagnostic["code"],
                    "TELEMETRY_STORE_CORRUPT",
                )
                self.assertEqual(
                    task_observation_snapshot(task_dir), before
                )

                unwritable_item = record(node_instance_id="node-b")
                with mock.patch.object(
                    telemetry,
                    "_node_telemetry_atomic_create",
                    side_effect=PermissionError(
                        errno.EACCES, "permission denied"
                    ),
                ):
                    unwritable = (
                        telemetry.write_node_telemetry_record(
                            data_dir, unwritable_item
                        )
                    )
                self.assertEqual(unwritable.status, "diagnostic")
                self.assertEqual(
                    unwritable.diagnostic["code"],
                    "TELEMETRY_STORE_UNWRITABLE",
                )
                self.assertEqual(
                    task_observation_snapshot(task_dir), before
                )

                unavailable_root = data_dir / "not-a-directory"
                unavailable_root.write_text(
                    "occupied", encoding="utf-8"
                )
                unavailable = telemetry.write_node_telemetry_record(
                    unavailable_root, unwritable_item
                )
                self.assertEqual(unavailable.status, "diagnostic")
                self.assertEqual(
                    unavailable.diagnostic["code"],
                    "TELEMETRY_STORE_UNAVAILABLE",
                )
                self.assertEqual(
                    task_observation_snapshot(task_dir), before
                )

    def test_failed_attempt_remains_retry_waste(self) -> None:
        failed = record(
            node_instance_id="node-failed",
            attempt=1,
            evidence_outcome="FAILED",
            adapter_outcome="FAILED",
            duration_ms=200,
            usage={
                "input_tokens": 50,
                "cached_input_tokens": 10,
                "output_tokens": 10,
                "reasoning_output_tokens": 5,
            },
        )
        succeeded = record(
            node_instance_id="node-failed",
            attempt=2,
            duration_ms=400,
            usage={
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 20,
                "reasoning_output_tokens": 10,
            },
        )

        report = telemetry.build_node_telemetry_report(
            (failed, succeeded),
            successful_task_ids=("task-a",),
            single_agent_baseline_tokens=300,
            observed_wall_time_ms=450,
            single_agent_baseline_wall_time_ms=900,
            accepted_results=1,
            evaluated_results=1,
        )

        self.assertEqual(report["record_count"], 2)
        # cached input is included in input and reasoning output is included
        # in output, matching the Codex turn.completed usage contract.
        self.assertEqual(report["total_tokens"], 180)
        self.assertEqual(report["input_tokens"], 150)
        self.assertEqual(report["cached_input_tokens"], 30)
        self.assertEqual(report["output_tokens"], 30)
        self.assertEqual(report["reasoning_output_tokens"], 15)
        self.assertEqual(report["cached_input_ratio_millis"], 200)
        self.assertEqual(report["retry_waste_tokens"], 60)
        self.assertEqual(report["retry_waste_ratio_millis"], 333)
        self.assertEqual(report["parallel_multiplier_millis"], 600)
        self.assertEqual(report["observed_wall_time_ms"], 450)
        self.assertEqual(
            report["single_agent_baseline_wall_time_ms"], 900
        )
        self.assertEqual(report["wall_time_ratio_millis"], 500)
        self.assertEqual(report["wall_time_speedup_millis"], 2000)
        self.assertEqual(report["wall_time_saved_ms"], 450)
        self.assertEqual(report["wall_time_gain_millis"], 500)
        self.assertEqual(report["duration_ms_p50"], 200)
        self.assertEqual(report["duration_ms_p95"], 400)
        self.assertEqual(report["quality_rate_millis"], 1000)

    def test_manager_usage_is_separate_orchestration_overhead(
        self,
    ) -> None:
        manager = record(
            node_instance_id="manager",
            repository_id=None,
            role="manager",
            usage={
                "input_tokens": 20,
                "cached_input_tokens": 0,
                "output_tokens": 5,
                "reasoning_output_tokens": 0,
            },
        )
        worker = record(
            node_instance_id="worker",
            usage={
                "input_tokens": 60,
                "cached_input_tokens": 0,
                "output_tokens": 15,
                "reasoning_output_tokens": 0,
            },
        )

        report = telemetry.build_node_telemetry_report(
            (manager, worker)
        )

        self.assertEqual(report["total_tokens"], 100)
        self.assertEqual(
            report["orchestration_overhead_tokens"], 25
        )
        self.assertEqual(
            report["orchestration_overhead_ratio_millis"], 250
        )

    def test_identity_and_quality_contracts_fail_closed(self) -> None:
        with self.assertRaises(telemetry.NodeTelemetryError) as raised:
            record(repository_id="../other")
        self.assertEqual(
            raised.exception.code, "TELEMETRY_IDENTITY_INVALID"
        )

        item = record()
        with self.assertRaises(telemetry.NodeTelemetryError) as raised:
            telemetry.build_node_telemetry_report(
                (item, item)
            )
        self.assertEqual(
            raised.exception.code, "TELEMETRY_RECORD_DUPLICATE"
        )

        with self.assertRaises(telemetry.NodeTelemetryError) as raised:
            telemetry.build_node_telemetry_report(
                (item,),
                accepted_results=2,
                evaluated_results=1,
            )
        self.assertEqual(
            raised.exception.code, "TELEMETRY_QUALITY_INVALID"
        )

        for arguments in (
            {"observed_wall_time_ms": 100},
            {"single_agent_baseline_wall_time_ms": 100},
            {
                "observed_wall_time_ms": 0,
                "single_agent_baseline_wall_time_ms": 100,
            },
            {
                "observed_wall_time_ms": 100,
                "single_agent_baseline_wall_time_ms": 0,
            },
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(
                    telemetry.NodeTelemetryError
                ) as raised:
                    telemetry.build_node_telemetry_report(
                        (item,), **arguments
                    )
                self.assertEqual(
                    raised.exception.code,
                    "TELEMETRY_WALL_TIME_BASELINE_INVALID",
                )

    def test_timestamps_are_canonical_ordered_utc_instants(self) -> None:
        for started_at, ended_at in (
            ("2026-07-27T00:00:00Z", "2026-07-27T00:00:00.100Z"),
            ("2026-02-30T00:00:00.000Z", "2026-03-01T00:00:00.000Z"),
            ("2026-07-27T00:00:01.000Z", "2026-07-27T00:00:00.000Z"),
        ):
            with self.subTest(started_at=started_at, ended_at=ended_at):
                with self.assertRaises(
                    telemetry.NodeTelemetryError
                ) as raised:
                    telemetry.build_node_telemetry(
                        task_id="task-a",
                        bundle_sha256="a" * 64,
                        node_instance_id="node-a",
                        repository_id="repo-a",
                        revision=7,
                        attempt=1,
                        executor_policy="executor.codex-exec/v1",
                        model_policy="balanced",
                        orchestration_role="worker",
                        adapter_outcome="SUCCEEDED",
                        evidence_outcome="SUCCEEDED",
                        started_at=started_at,
                        ended_at=ended_at,
                        duration_ms=100,
                        response_bytes=0,
                        artifact_bytes=0,
                    )
                self.assertEqual(
                    raised.exception.code, "TELEMETRY_TIME_INVALID"
                )

    def test_logical_model_policy_is_resolved_only_by_host_config(
        self,
    ) -> None:
        configuration = {
            "schema": "dev-flow-model-policy-map/v1",
            "policies": {
                "economy": {
                    "model": "host-small",
                    "reasoning_effort": "low",
                },
                "balanced": {
                    "model": "host-default",
                    "reasoning_effort": "medium",
                    "service_tier": "priority",
                },
                "critical": {
                    "model": "host-review",
                    "reasoning_effort": "high",
                },
            },
        }

        resolved = telemetry.resolve_node_model_policy(
            "balanced", configuration
        )

        self.assertEqual(resolved["model"], "host-default")
        self.assertEqual(resolved["policy"], "balanced")
        with self.assertRaises(TypeError):
            resolved["model"] = "changed"
        with self.assertRaises(
            telemetry.NodeTelemetryError
        ) as raised:
            telemetry.resolve_node_model_policy(
                "balanced",
                {
                    **configuration,
                    "policies": {
                        "balanced": configuration["policies"]["balanced"]
                    },
                },
            )
        self.assertEqual(
            raised.exception.code,
            "MODEL_POLICY_CONFIGURATION_INVALID",
        )


if __name__ == "__main__":
    unittest.main()
