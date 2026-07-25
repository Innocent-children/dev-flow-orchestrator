from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_flow.py"
SUPPORT = Path(__file__).resolve().with_name("support.py")
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_mutation_gate_crash", SCRIPT
)
assert SPEC and SPEC.loader
dev_flow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dev_flow
SPEC.loader.exec_module(dev_flow)


class MutationGateCrashTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "state"
        self.task_dir = self.data / "tasks" / "gate-crash-task"
        dev_flow._ensure_private_dir(self.task_dir)
        self.state = {
            "schema_version": dev_flow.SCHEMA_VERSION,
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "task_id": "gate-crash-task",
            "status": "INTAKE",
            "revision": 1,
            "repositories": [],
            "artifacts": [],
            "approvals": {},
            "tests": [],
            "review_snapshots": [],
            "mutation_recoveries": [],
            "impact_generation": 0,
            "planning_generation": 0,
            "workspace": {
                "strategy": "worktree",
                "ready": False,
                "generation": 0,
            },
            "blocked": None,
            "cancelled": None,
        }
        dev_flow._atomic_write_json(
            self.task_dir / "state.json", self.state
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_parent_crash_before_pid_persistence_never_starts_target(
        self,
    ) -> None:
        target_marker = self.root / "real-target-started"
        crashed = subprocess.run(
            [
                sys.executable,
                str(SUPPORT),
                "crash-after-gate-spawn",
                str(SCRIPT),
                str(self.task_dir),
                str(target_marker),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        self.assertEqual(
            crashed.returncode,
            91,
            (crashed.stdout, crashed.stderr),
        )
        self.assertFalse(target_marker.exists())

        quarantine_path = dev_flow._quarantine_path(self.task_dir)
        quarantine = json.loads(
            quarantine_path.read_text(encoding="utf-8")
        )
        self.assertEqual(quarantine["gate_protocol_version"], 1)
        self.assertEqual(quarantine["phase"], "spawn_pending")
        self.assertIsNone(quarantine["pid"])
        self.assertIsNone(quarantine["process_group"])
        self.assertIs(
            quarantine["target_release_authorized"], False
        )
        self.assertFalse(
            dev_flow._quarantine_processes_alive(quarantine)
        )

        recovered = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "recover-quarantine",
                self.state["task_id"],
                "--expected-revision",
                str(self.state["revision"]),
                "--data-dir",
                str(self.data),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        self.assertEqual(
            recovered.returncode,
            0,
            (recovered.stdout, recovered.stderr),
        )
        response = json.loads(recovered.stdout.decode("utf-8"))
        self.assertTrue(response["recovered"])
        self.assertFalse(quarantine_path.exists())
        self.assertFalse(target_marker.exists())
        current = dev_flow.load_state(self.state["task_id"], self.data)
        self.assertEqual(current["revision"], 2)
        self.assertEqual(len(current["mutation_recoveries"]), 1)

    def test_parent_death_after_release_quiesces_owned_tree(
        self,
    ) -> None:
        target_marker = self.root / "released target started"
        crashed = subprocess.run(
            [
                sys.executable,
                str(SUPPORT),
                "crash-after-target-release",
                str(SCRIPT),
                str(self.task_dir),
                str(target_marker),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        self.assertNotEqual(
            crashed.returncode,
            0,
            (crashed.stdout, crashed.stderr),
        )
        self.assertTrue(target_marker.exists())

        quarantine_path = dev_flow._quarantine_path(self.task_dir)
        quarantine = json.loads(
            quarantine_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            quarantine["phase"], "target_release_authorized"
        )
        self.assertIs(
            quarantine["target_release_authorized"], True
        )
        self.assertIs(quarantine["containment_established"], True)
        self.assertEqual(
            quarantine["containment_kind"],
            (
                "windows_job_kill_on_close"
                if os.name == "nt"
                else "posix_process_group"
            ),
        )

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not dev_flow._quarantine_processes_alive(
                quarantine
            ):
                break
            time.sleep(0.05)
        else:
            self.fail("released mutation process tree remained active")

        recovered = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "recover-quarantine",
                self.state["task_id"],
                "--expected-revision",
                str(self.state["revision"]),
                "--data-dir",
                str(self.data),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        self.assertEqual(
            recovered.returncode,
            0,
            (recovered.stdout, recovered.stderr),
        )
        self.assertTrue(
            json.loads(recovered.stdout.decode("utf-8"))["recovered"]
        )
        self.assertFalse(quarantine_path.exists())

    def test_real_target_cannot_spoof_gate_spawn_failure(self) -> None:
        first_marker = self.root / "first mutation"
        forged_marker = self.root / "forged spawn failure"
        forged_command = [
            sys.executable,
            str(SUPPORT),
            "spoof-old-gate-protocol",
            str(forged_marker),
        ]
        with dev_flow._task_lock(self.task_dir):
            first = dev_flow._run(
                [
                    sys.executable,
                    str(SUPPORT),
                    "write-marker",
                    str(first_marker),
                ],
                mutation=True,
            )
            self.assertEqual(first.returncode, 0)
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._run(forged_command, mutation=True)

        self.assertEqual(captured.exception.code, "COMMAND_FAILED")
        self.assertEqual(
            captured.exception.details["failure_kind"], "exit"
        )
        self.assertEqual(captured.exception.details["returncode"], 252)
        self.assertTrue(first_marker.exists())
        self.assertTrue(forged_marker.exists())
        quarantine = json.loads(
            dev_flow._quarantine_path(self.task_dir).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(quarantine["operations"]), 2)
        self.assertEqual(quarantine["command"], forged_command)
        self.assertEqual(
            quarantine["phase"], "child_failed_quiescent"
        )
        self.assertIs(
            quarantine["target_release_authorized"], True
        )

    def test_first_target_cannot_spoof_gate_spawn_failure(
        self,
    ) -> None:
        forged_marker = self.root / "first forged spawn failure"
        command = [
            sys.executable,
            str(SUPPORT),
            "spoof-old-gate-protocol",
            str(forged_marker),
        ]
        with dev_flow._task_lock(self.task_dir):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._run(command, mutation=True)
        self.assertEqual(captured.exception.code, "COMMAND_FAILED")
        self.assertEqual(
            captured.exception.details["failure_kind"], "exit"
        )
        self.assertTrue(forged_marker.exists())
        quarantine = json.loads(
            dev_flow._quarantine_path(self.task_dir).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(quarantine["operations"]), 1)
        self.assertEqual(quarantine["command"], command)
        self.assertEqual(
            quarantine["phase"], "child_failed_quiescent"
        )

    def test_known_outer_and_inner_spawn_errors_are_structured(
        self,
    ) -> None:
        with dev_flow._task_lock(self.task_dir), mock.patch.object(
            dev_flow.subprocess,
            "Popen",
            side_effect=ValueError("injected invalid Popen arguments"),
        ):
            with self.assertRaises(dev_flow.FlowError) as outer:
                dev_flow._run(
                    [sys.executable, "-c", "pass"],
                    mutation=True,
                )
        self.assertEqual(outer.exception.code, "COMMAND_FAILED")
        self.assertEqual(
            outer.exception.details["failure_kind"], "spawn"
        )
        self.assertFalse(
            dev_flow._quarantine_path(self.task_dir).exists()
        )

        with dev_flow._task_lock(self.task_dir):
            with self.assertRaises(dev_flow.FlowError) as inner:
                dev_flow._run(
                    [sys.executable, "embedded\0nul"],
                    mutation=True,
                )
        self.assertEqual(inner.exception.code, "COMMAND_FAILED")
        self.assertEqual(
            inner.exception.details["failure_kind"], "spawn"
        )
        self.assertFalse(
            dev_flow._quarantine_path(self.task_dir).exists()
        )

    def test_non_keyboard_communicate_error_quiesces_before_unlock(
        self,
    ) -> None:
        class Process:
            pid = 7373
            returncode = None

            def communicate(self):
                raise RuntimeError("injected communicate failure")

        process = Process()
        with dev_flow._task_lock(self.task_dir), mock.patch.object(
            dev_flow.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            dev_flow,
            "_windows_kill_on_close_job",
            return_value=None,
        ), mock.patch.object(
            dev_flow,
            "_terminate_and_quiesce_owned_child",
            return_value=True,
        ) as quiesce:
            with self.assertRaisesRegex(
                RuntimeError, "communicate failure"
            ):
                dev_flow._run([sys.executable, "-c", "pass"])
        quiesce.assert_called_once_with(
            process,
            [sys.executable, "-c", "pass"],
            protected_child=True,
            windows_job=None,
        )

    @unittest.skipIf(
        os.name == "nt", "requires native POSIX process groups"
    )
    def test_cleanup_interruption_still_quarantines_and_forces_posix_kill(
        self,
    ) -> None:
        class Process:
            pid = 7474
            returncode = None

            def communicate(self):
                raise RuntimeError("initial child failure")

        process = Process()
        with dev_flow._task_lock(self.task_dir), mock.patch.object(
            dev_flow.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            dev_flow,
            "_terminate_and_quiesce_owned_child",
            side_effect=KeyboardInterrupt(),
        ), mock.patch.object(
            dev_flow.os, "killpg"
        ) as kill_group:
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._run([sys.executable, "-c", "pass"])
        self.assertEqual(
            captured.exception.code, "MUTATION_QUARANTINED"
        )
        kill_group.assert_called_once_with(process.pid, 9)
        self.assertTrue(
            dev_flow._quarantine_path(self.task_dir).is_file()
        )

    def test_cleanup_interruption_still_terminates_and_closes_windows_job(
        self,
    ) -> None:
        class Process:
            pid = 7575
            returncode = None
            _handle = 0x7575

            def communicate(self):
                raise RuntimeError("initial child failure")

        process = Process()
        fake_job = object()
        quarantine = self.task_dir / "simulated-windows-quarantine"
        with dev_flow._task_lock(self.task_dir), mock.patch.object(
            dev_flow.os, "name", "nt"
        ), mock.patch.object(
            dev_flow.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            dev_flow,
            "_windows_kill_on_close_job",
            return_value=fake_job,
        ), mock.patch.object(
            dev_flow,
            "_terminate_and_quiesce_owned_child",
            side_effect=KeyboardInterrupt(),
        ), mock.patch.object(
            dev_flow, "_terminate_windows_job"
        ) as terminate, mock.patch.object(
            dev_flow, "_close_windows_job"
        ) as close, mock.patch.object(
            dev_flow,
            "_persist_mutation_quarantine",
            return_value=quarantine,
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._run([sys.executable, "-c", "pass"])
        self.assertEqual(
            captured.exception.code, "MUTATION_QUARANTINED"
        )
        terminate.assert_called_once_with(fake_job)
        close.assert_called_once_with(fake_job)

    def test_posix_escalation_targets_group_after_leader_exit(
        self,
    ) -> None:
        process = mock.Mock()
        process.pid = 8484
        process.wait.return_value = 0
        with mock.patch.object(
            dev_flow.os, "name", "posix"
        ), mock.patch.object(
            dev_flow.os, "killpg", create=True
        ) as kill_group, mock.patch.object(
            dev_flow,
            "_posix_process_group_alive",
            side_effect=[True, True, False],
        ), mock.patch.object(
            dev_flow.time,
            "monotonic",
            side_effect=[0.0, 3.0, 3.0, 9.0],
        ), mock.patch.object(
            dev_flow.time, "sleep"
        ):
            quiescent = dev_flow._terminate_and_quiesce_owned_child(
                process,
                ["fixture"],
                protected_child=True,
                windows_job=None,
            )
        self.assertTrue(quiescent)
        self.assertEqual(
            kill_group.call_args_list,
            [mock.call(8484, 15), mock.call(8484, 9)],
        )


if __name__ == "__main__":
    unittest.main()
