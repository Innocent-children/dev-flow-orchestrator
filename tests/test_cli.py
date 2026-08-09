"""Current CLI subprocess journeys and machine-readable error contract."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Iterator
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from support import (
    assert_hermetic_subprocess_env,
    hermetic_subprocess_env,
    make_repository,
    probe_subprocess_runtime_roots,
)
from dev_flow_orchestrator import cli as cli_module
from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.runtime_paths import resolve_data_dir
from dev_flow_orchestrator.store import TaskStore
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    MODEL_VERSION,
    RECEIPT_SCHEMA,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    TASK_CHANGE_CLAIMS_SCHEMA,
    WORKFLOW_SCHEMA,
    WORKSPACE_FRESHNESS_SCHEMA,
    PRODUCT_IDENTITY,
)


class _LiveWebStateHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = json.dumps({"product_identity": PRODUCT_IDENTITY}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *arguments: object) -> None:
        pass


@contextmanager
def live_web_state(data_root: Path) -> Iterator[None]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LiveWebStateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    token = "hostile-parent-token-0123456789abcdef"
    runtime = data_root / "web-runtime"
    runtime.mkdir(parents=True)
    (runtime / "state.json").write_text(
        json.dumps(
            {
                "schema": "dev-flow-web-runtime",
                "instance_id": "hostile-parent-instance-0123456789",
                "pid": os.getpid(),
                "status": "running",
                "started_at": "2026-08-09T00:00:00Z",
                "host": "127.0.0.1",
                "port": port,
                "token": token,
                "url": "http://127.0.0.1:{}/#token={}".format(port, token),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def tree_bytes(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    """Capture names, entry kinds, and all regular-file bytes below ``root``."""

    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item).encode("utf-8")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            entries.append((relative, "symlink", os.fsencode(os.readlink(path))))
        elif path.is_dir():
            entries.append((relative, "directory", None))
        else:
            entries.append((relative, "file", path.read_bytes()))
    return tuple(entries)


def run_cli(
    data_dir: str,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    if environment is None:
        environment = hermetic_subprocess_env(
            Path(data_dir).resolve().parent,
            overrides={"PYTHONPATH": str(SRC)},
        )
    else:
        assert_hermetic_subprocess_env(Path(data_dir).resolve().parent, environment)
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts" / "dev_flow.py"),
            "--data-dir",
            data_dir,
            *arguments,
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = str(self.root / "data")
        self.repository = make_repository(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_mutation_freshness_false_and_unknown_are_successful_cli_results(self) -> None:
        cases = (
            (
                "changed",
                {
                    "status": False,
                    "observed_at": "2026-08-09T00:00:00Z",
                    "reasons": ["workspace_changed", "workspace_changed:repository"],
                },
                {"revision": 2, "status": "ANALYZING"},
            ),
            (
                "unknown",
                {
                    "status": "unknown",
                    "observed_at": None,
                    "reasons": ["observation_failed:OBSERVATION_FAILED"],
                },
                None,
            ),
        )
        for label, freshness, projection in cases:
            with self.subTest(freshness=label):
                receipt = {
                    "schema": RECEIPT_SCHEMA,
                    "task_id": "task-adapter-freshness",
                    "action_id": "task.preflight",
                    "committed_revision": 2,
                    "status": "ANALYZING",
                    "current_node": "impact",
                    "committed": True,
                    "workspace_freshness": {
                        "schema": WORKSPACE_FRESHNESS_SCHEMA,
                        **freshness,
                    },
                    "blind_retry": False,
                    "recovery": {
                        "kind": "read-after-write",
                        "tool": "dev_flow_get_next_action",
                        "task_id": "task-adapter-freshness",
                        "blind_retry": False,
                    },
                }
                mutation_result = {
                    "receipt": receipt,
                    "projection": projection,
                }
                controller = mock.Mock()
                controller.apply.return_value = mutation_result
                stdout = io.StringIO()
                with mock.patch.object(
                    cli_module,
                    "Controller",
                    return_value=controller,
                ), redirect_stdout(stdout):
                    exit_code = cli_module.main(
                        (
                            "--data-dir",
                            self.data_dir,
                            "apply",
                            "task-adapter-freshness",
                            "--action",
                            "task.preflight",
                            "--payload-json",
                            "{}",
                            "--binding-json",
                            "{}",
                        )
                    )

                self.assertEqual(exit_code, 0)
                self.assertEqual(
                    json.loads(stdout.getvalue()),
                    {
                        "ok": True,
                        "command": "apply",
                        **mutation_result,
                    },
                )
                controller.apply.assert_called_once_with(
                    "task-adapter-freshness",
                    "task.preflight",
                    {},
                    binding={},
                )

    def test_data_directory_defaults_to_codex_plugin_namespace(self) -> None:
        codex_root = self.root / "codex-home"
        environment = hermetic_subprocess_env(
            self.root,
            overrides={
                "CODEX_HOME": str(codex_root),
                "PYTHONPATH": str(SRC),
            },
            unset=("DEV_FLOW_DATA_DIR", "PLUGIN_DATA"),
        )
        resolved = Path(
            resolve_data_dir(None, environment=environment)
        ).resolve()
        expected_root = (
            codex_root
            / "plugins"
            / "data"
            / "dev-flow-orchestrator-personal"
        ).resolve()
        self.assertEqual(resolved, expected_root)
        resolved.relative_to(self.root.resolve())
        self.assertEqual(
            probe_subprocess_runtime_roots(self.root, environment)["data"],
            expected_root,
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow.py"),
                "web",
                "status",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "stopped")
        self.assertFalse(codex_root.exists())

    def test_default_data_root_ignores_hostile_parent_authorities(self) -> None:
        authority_cases = (
            ("data", ("DEV_FLOW_DATA_DIR",)),
            ("plugin", ("PLUGIN_DATA",)),
            ("codex", ("CODEX_HOME",)),
            ("data-plugin", ("DEV_FLOW_DATA_DIR", "PLUGIN_DATA")),
            ("data-codex", ("DEV_FLOW_DATA_DIR", "CODEX_HOME")),
            ("plugin-codex", ("PLUGIN_DATA", "CODEX_HOME")),
            (
                "all",
                ("DEV_FLOW_DATA_DIR", "PLUGIN_DATA", "CODEX_HOME"),
            ),
        )
        for label, selected in authority_cases:
            with self.subTest(authorities=label), tempfile.TemporaryDirectory(
                prefix="dev-flow-hostile-parent-"
            ) as external_temporary:
                external = Path(external_temporary)
                authority_roots = {
                    "DEV_FLOW_DATA_DIR": external / "data-override",
                    "PLUGIN_DATA": external / "plugin-data",
                    "CODEX_HOME": external / "codex-home",
                }
                redirected_runtime = external / "xdg-data-home"
                redirected_git_dir = external / "redirected-git-dir"
                redirected_work_tree = external / "redirected-work-tree"
                redirected_index = external / "redirected-index"
                for redirected in (
                    redirected_runtime,
                    redirected_git_dir,
                    redirected_work_tree,
                ):
                    redirected.mkdir()
                    (redirected / "redirect-sentinel.bin").write_bytes(
                        b"hostile redirect must remain byte-stable\x00\xfe"
                    )
                redirected_index.write_bytes(
                    b"hostile index redirect must remain byte-stable\x00\xfd"
                )
                for name in selected:
                    root = authority_roots[name]
                    root.mkdir(parents=True)
                    (root / "authority-sentinel.bin").write_bytes(
                        b"hostile authority must remain byte-stable\x00\xff"
                    )

                if "DEV_FLOW_DATA_DIR" in selected:
                    external_data = authority_roots["DEV_FLOW_DATA_DIR"]
                elif "PLUGIN_DATA" in selected:
                    external_data = authority_roots["PLUGIN_DATA"]
                else:
                    external_data = (
                        authority_roots["CODEX_HOME"]
                        / "plugins"
                        / "data"
                        / "dev-flow-orchestrator-personal"
                    )
                external_repository = make_repository(
                    external, "external-authority-repository"
                )
                external_task_id = "hostile-parent-task"
                Controller(str(external_data)).start(
                    requirement="External authority must never be observed",
                    workflow="lite",
                    repositories=(str(external_repository),),
                    task_id=external_task_id,
                )

                with live_web_state(external_data):
                    external_before = tree_bytes(external)
                    hostile = {
                        "DEV_FLOW_DATA_DIR": "",
                        "PLUGIN_DATA": "",
                        "CODEX_HOME": "",
                        "XDG_DATA_HOME": str(redirected_runtime),
                        "GIT_DIR": str(redirected_git_dir),
                        "GIT_WORK_TREE": str(redirected_work_tree),
                        "GIT_INDEX_FILE": str(redirected_index),
                    }
                    hostile.update(
                        {name: str(authority_roots[name]) for name in selected}
                    )
                    isolated_root = self.root / ("isolated-" + label)
                    isolated_root.mkdir()
                    isolated_codex = isolated_root / "codex-home"
                    with mock.patch.dict(os.environ, hostile, clear=False):
                        environment = hermetic_subprocess_env(
                            isolated_root,
                            overrides={
                                "CODEX_HOME": str(isolated_codex),
                                "PYTHONPATH": str(SRC),
                            },
                            unset=("DEV_FLOW_DATA_DIR", "PLUGIN_DATA"),
                        )
                    expected_data = (
                        isolated_codex
                        / "plugins"
                        / "data"
                        / "dev-flow-orchestrator-personal"
                    ).resolve()
                    observed = probe_subprocess_runtime_roots(
                        isolated_root, environment
                    )
                    self.assertEqual(observed["data"], expected_data)
                    expected_data.relative_to(isolated_root.resolve())
                    self.assertFalse((expected_data / "web-runtime").exists())
                    self.assertFalse(
                        (expected_data / MODEL_VERSION / "tasks").exists()
                    )

                    def invoke_default(*arguments: str) -> subprocess.CompletedProcess:
                        return subprocess.run(
                            [
                                sys.executable,
                                "-I",
                                "-S",
                                str(ROOT / "scripts" / "dev_flow.py"),
                                *arguments,
                            ],
                            text=True,
                            capture_output=True,
                            check=False,
                            env=environment,
                        )

                    status = invoke_default("web", "status")
                    listed = invoke_default("list")
                    self.assertEqual(status.returncode, 0, status.stderr)
                    self.assertEqual(
                        json.loads(status.stdout)["status"], "stopped"
                    )
                    self.assertEqual(listed.returncode, 0, listed.stderr)
                    self.assertEqual(json.loads(listed.stdout)["tasks"], [])
                    self.assertNotIn(external_task_id, listed.stdout)
                    self.assertFalse((expected_data / "web-runtime").exists())
                    self.assertFalse(
                        (expected_data / MODEL_VERSION / "tasks").exists()
                    )
                    self.assertEqual(
                        tree_bytes(external),
                        external_before,
                    )

    def test_data_directory_resolution_precedence_is_explicit_override_plugin_then_codex(self) -> None:
        explicit = self.root / "explicit"
        override = self.root / "override"
        plugin_data = self.root / "plugin-data"
        codex_root = self.root / "codex-root"
        complete = {
            "DEV_FLOW_DATA_DIR": str(override),
            "PLUGIN_DATA": str(plugin_data),
            "CODEX_HOME": str(codex_root),
        }
        self.assertEqual(
            resolve_data_dir(str(explicit), environment=complete),
            str(explicit.resolve()),
        )
        self.assertEqual(
            resolve_data_dir(None, environment=complete),
            str(override.resolve()),
        )
        self.assertEqual(
            resolve_data_dir(
                None,
                environment={
                    "PLUGIN_DATA": str(plugin_data),
                    "CODEX_HOME": str(codex_root),
                },
            ),
            str(plugin_data.resolve()),
        )
        self.assertEqual(
            resolve_data_dir(None, environment={"CODEX_HOME": str(codex_root)}),
            str(
                (
                    codex_root
                    / "plugins"
                    / "data"
                    / "dev-flow-orchestrator-personal"
                ).resolve()
            ),
        )

    def test_default_and_plugin_roots_read_current_tasks_without_mutation(self) -> None:
        plugin_data = self.root / "plugin-data"
        codex_root = self.root / "codex-home"
        default_data = (
            codex_root
            / "plugins"
            / "data"
            / "dev-flow-orchestrator-personal"
        )
        cases = (
            (
                "plugin",
                plugin_data,
                {"PLUGIN_DATA": str(plugin_data), "CODEX_HOME": str(codex_root)},
            ),
            ("default", default_data, {"CODEX_HOME": str(codex_root)}),
        )

        for label, expected_base, environment in cases:
            with self.subTest(source=label):
                task_id = "task-{}-data-root".format(label)
                completed = run_cli(
                    str(expected_base),
                    "start",
                    "--requirement",
                    "{} data root discovery".format(label),
                    "--workflow",
                    "lite",
                    "--repo",
                    str(self.repository),
                    "--task-id",
                    task_id,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

                state_path = (
                    expected_base
                    / MODEL_VERSION
                    / "tasks"
                    / task_id
                    / "state.json"
                )
                current_bytes = state_path.read_bytes()
                self.assertIn(b'"version":"0.4.0"', current_bytes)

                def snapshot() -> tuple:
                    return tuple(
                        (
                            str(path.relative_to(expected_base)),
                            path.read_bytes() if path.is_file() else None,
                        )
                        for path in sorted(expected_base.rglob("*"))
                    )

                before = snapshot()
                store = TaskStore(resolve_data_dir(None, environment=environment))
                self.assertEqual(store.root, expected_base.resolve())
                self.assertEqual(
                    store.tasks_root,
                    expected_base.resolve() / MODEL_VERSION / "tasks",
                )
                self.assertFalse(
                    (expected_base / MODEL_VERSION / MODEL_VERSION).exists()
                )

                entries, diagnostics = store.inspect_inventory()
                state, definition = store.inspect_with_definition(task_id)

                self.assertEqual(diagnostics, ())
                self.assertEqual(
                    tuple(item.task_id for item, _ in entries),
                    (task_id,),
                )
                self.assertEqual(state.task_id, task_id)
                self.assertEqual(definition.workflow_id, "lite")
                self.assertEqual(state_path.read_bytes(), current_bytes)
                self.assertEqual(snapshot(), before)

    def invoke_json(self, *arguments: str):
        completed = run_cli(self.data_dir, *arguments)
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                "CLI did not emit JSON: {}\nstdout={}\nstderr={}".format(
                    exc,
                    completed.stdout,
                    completed.stderr,
                )
            )
        return completed, value

    def invoke_success(self, *arguments: str) -> dict:
        completed, value = self.invoke_json(*arguments)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(value["ok"])
        return value

    def next_projection(self, task_id: str) -> dict:
        return self.invoke_success("next", task_id)["projection"]

    def apply_projection(
        self,
        task_id: str,
        projection: dict,
        payload: dict,
    ) -> dict:
        action = projection["action"]
        return self.invoke_success(
            "apply",
            task_id,
            "--action",
            action["action_id"],
            "--payload-json",
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "--binding-json",
            json.dumps(action["binding"], sort_keys=True, separators=(",", ":")),
        )

    def start_lite(self, requirement: str) -> dict:
        return self.invoke_success(
            "start",
            "--requirement",
            requirement,
            "--workflow",
            "lite",
            "--repo",
            str(self.repository),
        )

    def test_full_lite_lifecycle_via_cli(self) -> None:
        started = self.start_lite("cli feature")
        self.assertEqual(started["command"], "start")
        task_id = started["task"]["task_id"]
        repository_id = started["task"]["repositories"][0]["id"]
        self.assertEqual(started["task"]["workflow"]["version"], MODEL_VERSION)

        shown = self.invoke_success("show", task_id)
        self.assertEqual(shown["task"]["task_id"], task_id)
        self.assertEqual(shown["task"]["current_node"], "preflight")
        self.assertEqual(
            shown["task"]["current_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(len(shown["task"]["current_snapshot"]["repositories"]), 1)

        projection = self.next_projection(task_id)
        self.assertEqual(projection["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(len(projection["repository_set"]["repositories"]), 1)
        self.assertEqual(
            projection["repository_set"]["repositories"][0]["id"],
            repository_id,
        )
        self.assertEqual(projection["action"]["action_id"], "task.preflight")
        applied = self.apply_projection(task_id, projection, {})
        self.assertEqual(applied["receipt"]["status"], "ANALYZING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "impact.record")
        applied = self.apply_projection(task_id, projection, {
            "summary": "CLI impact confirmed",
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": "available",
            },
            "impact_manifest": {
                "confidence": "source-confirmed",
                "entries": [{
                    "repository_id": repository_id,
                    "path": "a.txt",
                    "symbol": None,
                    "criterion_ids": ["requirement"],
                }],
                "edges": [],
                "risk_triggers": [],
                "public_behavior": False,
                "documentation_required": False,
                "manual_evidence_required": False,
                "executable_reproduction_required": True,
                "overflow": False,
                "limitations": [],
            },
        })
        self.assertEqual(applied["receipt"]["status"], "IMPLEMENTING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "implementation.record")
        with (self.repository / "a.txt").open("a", encoding="utf-8") as stream:
            stream.write("implemented through CLI\n")
        applied = self.apply_projection(
            task_id,
            projection,
            {
                "summary": "Implemented through CLI",
                "ownership_claims": {
                    "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                    "claims": [{
                        "repository_id": repository_id,
                        "path": "a.txt",
                        "classification": "implementation",
                        "criterion_ids": ["requirement"],
                        "purpose": "Exercise CLI task-owned changes",
                    }],
                },
            },
        )
        self.assertEqual(applied["receipt"]["status"], "VERIFYING")

        projection = self.next_projection(task_id)
        self.assertEqual(projection["action"]["action_id"], "assurance.execute")
        obligation = projection["action"]["current_obligation"]
        self.assertEqual(obligation["repository_ids"], [repository_id])
        verification_command = "python3 -m unittest tests.test_cli"
        applied = self.apply_projection(
            task_id,
            projection,
            {
                "summary": "CLI lifecycle verified",
                "assurance_result": {
                    "obligation_id": obligation["obligation_id"],
                    "passed": True,
                    "evidence": [{
                        "kind": "command",
                        "reference": verification_command,
                        "summary": "CLI lifecycle verified",
                    }],
                    "limitations": [],
                },
            },
        )
        self.assertEqual(applied["receipt"]["status"], "FINALIZING")

        projection = self.next_projection(task_id)
        self.assertEqual(
            projection["action"]["action_id"],
            "delivery.finalize.success",
        )
        applied = self.apply_projection(
            task_id,
            projection,
            {
                "summary": "Delivered through CLI",
                "remaining_risks": {},
                "handoff": "Ready to use",
            },
        )
        self.assertEqual(applied["receipt"]["status"], "DONE")
        self.assertTrue(applied["projection"]["done"])
        self.assertEqual(applied["projection"]["dossier"]["outcome"], "success")
        self.assertEqual(
            applied["projection"]["dossier"]["schema"],
            DELIVERY_DOSSIER_SCHEMA,
        )
        self.assertTrue(applied["projection"]["dossier"]["current"])
        self.assertEqual(
            applied["projection"]["dossier"]["repository_set_id"],
            applied["projection"]["repository_set"]["id"],
        )

        shown = self.invoke_success("show", task_id)
        dossier = shown["task"]["records"][-1]["artifact"]["body"]
        self.assertEqual(dossier["schema"], DELIVERY_DOSSIER_SCHEMA)
        self.assertEqual(dossier["change_summary"], "Delivered through CLI")
        self.assertEqual(dossier["handoff_recommendation"], "Ready to use")
        self.assertEqual(dossier["coverage"]["requirement"]["status"], "proven")
        self.assertEqual(dossier["repository_set"]["members"][0]["repository_id"], repository_id)
        self.assertTrue(dossier["verification"]["assurance_execution"]["passed"])
        self.assertEqual(dossier["assurance_plan"]["profile"], "lite")
        self.assertTrue(dossier["aggregate_freshness"]["current"])
        self.assertEqual(
            dossier["repository_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertTrue(shown["task"]["dossier"]["current"])

    def test_cancel_after_preflight_and_list(self) -> None:
        started = self.start_lite("cancel me")
        task_id = started["task"]["task_id"]
        projection = self.next_projection(task_id)
        self.apply_projection(task_id, projection, {})

        cancelled = self.invoke_success(
            "cancel",
            task_id,
            "--reason",
            "No longer required",
        )
        self.assertEqual(cancelled["receipt"]["status"], "CANCELLED")
        listing = self.invoke_success("list")
        self.assertEqual(len(listing["tasks"]), 1)
        self.assertEqual(listing["tasks"][0]["task_id"], task_id)
        self.assertEqual(listing["tasks"][0]["status"], "CANCELLED")
        shown = self.invoke_success("show", task_id)
        self.assertEqual(
            shown["task"]["records"][-1]["snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )

    def test_workflow_accepts_custom_current_path(self) -> None:
        flow_path = self.root / "custom-lite.yaml"
        flow_path.write_text(
            (ROOT / "workflows" / "lite.yaml")
            .read_text(encoding="utf-8")
            .replace("id: lite\n", "id: custom-lite\n", 1),
            encoding="utf-8",
        )
        started = self.invoke_success(
            "start",
            "--requirement",
            "custom",
            "--workflow",
            str(flow_path),
            "--repo",
            str(self.repository),
        )
        self.assertEqual(started["task"]["workflow"]["id"], str(flow_path))
        self.assertEqual(
            started["task"]["workflow"]["schema"],
            WORKFLOW_SCHEMA,
        )
        self.assertEqual(started["task"]["workflow"]["version"], MODEL_VERSION)

    def test_missing_task_error_is_machine_readable(self) -> None:
        completed, value = self.invoke_json("show", "missing-task-id")
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(value["ok"])
        self.assertEqual(value["error"]["code"], "TASK_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
