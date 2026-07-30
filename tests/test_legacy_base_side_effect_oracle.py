from __future__ import annotations

import ast
import contextlib
import copy
import errno
import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case


ROOT = Path(__file__).resolve().parents[1]
ORACLE_PATH = ROOT / "scripts" / "legacy_base_oracle.py"
FIXTURE_PATH = (
    Path(__file__).with_name("fixtures")
    / "workflow_legacy"
    / "side_effect_base_oracle.json"
)


def _load_oracle_module():
    specification = importlib.util.spec_from_file_location(
        "legacy_base_side_effect_oracle", ORACLE_PATH
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


oracle_module = _load_oracle_module()
dev_flow = test_case.dev_flow
git = test_case.git


def _events(task_dir: Path) -> list[dict]:
    path = task_dir / "events.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


class LegacyBaseOracleFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.oracle = oracle_module.load_frozen_oracle(FIXTURE_PATH)

    def test_fixture_binds_and_verifies_the_immutable_base_objects(self) -> None:
        self.assertEqual(
            self.oracle["base"]["commit"],
            oracle_module.BASE_COMMIT,
        )
        self.assertEqual(
            self.oracle["base"]["tree"],
            oracle_module.BASE_TREE,
        )
        verified = oracle_module.verify_base_objects(ROOT, self.oracle)
        expected_paths = [
            item["path"] for item in self.oracle["base"]["source_objects"]
        ]
        self.assertEqual(
            verified["verified_source_objects"], expected_paths
        )
        self.assertEqual(
            verified["base_cli_commands"],
            self.oracle["inventory"]["base_cli_commands"],
        )

    def test_base_and_candidate_command_inventories_are_complete(self) -> None:
        inventory = self.oracle["inventory"]
        classified = [
            command
            for commands in inventory["classifications"].values()
            for command in commands
        ]
        self.assertCountEqual(
            classified, inventory["base_cli_commands"]
        )
        self.assertEqual(len(classified), len(set(classified)))

        candidate = oracle_module.audit_candidate(ROOT, self.oracle)
        self.assertEqual(
            candidate["retained_base_commands"],
            inventory["base_cli_commands"],
        )
        self.assertEqual(
            set(candidate["verified_variants"]),
            set(inventory["variant_ids"]),
        )
        self.assertEqual(candidate["task_schema_versions"], [1, 2])
        self.assertTrue(
            set(inventory["base_cli_commands"]).issubset(
                candidate["candidate_cli_commands"]
            )
        )

    def test_command_phase_cross_product_consumes_every_frozen_observation(
        self,
    ) -> None:
        rows = self.oracle["cross_product"]
        self.assertEqual(
            {row["variant_id"] for row in rows},
            set(self.oracle["inventory"]["variant_ids"]),
        )
        self.assertEqual(
            {row["command"] for row in rows},
            set(
                self.oracle["inventory"][
                    "retained_side_effect_commands"
                ]
            ),
        )
        expected_fields = {
            "effect_start",
            "mutation_intent",
            "containment",
            "quarantine",
            "recovery",
            "revision_delta",
            "durable_event_batch",
            "error_code",
            "persisted_bytes",
        }
        used_profiles: set[str] = set()
        for row in rows:
            used_profiles.update(row["interruption_profiles"])
            self.assertTrue(row["effects"])
            self.assertTrue(row["phase"])
            for schema in ("1", "2"):
                scenarios = row["schemas"][schema]
                success = scenarios["success"]
                rejected = scenarios["pre_effect_rejection"]
                self.assertEqual(set(success), expected_fields)
                self.assertEqual(set(rejected), expected_fields)
                self.assertTrue(success["effect_start"])
                self.assertEqual(success["revision_delta"], 1)
                self.assertTrue(success["durable_event_batch"])
                self.assertIsNone(success["error_code"])
                self.assertFalse(rejected["effect_start"])
                self.assertEqual(rejected["revision_delta"], 0)
                self.assertEqual(rejected["durable_event_batch"], [])
                self.assertEqual(
                    rejected["error_code"], "REVISION_CONFLICT"
                )
        self.assertEqual(
            used_profiles, set(self.oracle["interruption_profiles"])
        )

        supported_stage_ids: set[str] = set()
        for profile in self.oracle["interruption_profiles"].values():
            for stage in profile["supported_stages"]:
                self.assertEqual(
                    set(stage["observation"]), expected_fields
                )
                supported_stage_ids.add(stage["id"])
        self.assertTrue(supported_stage_ids)
        self.assertTrue(self.oracle["unsupported_injection_points"])

    def test_base_evidence_is_content_bound_and_still_resolves(self) -> None:
        source_paths = {
            item["path"] for item in self.oracle["base"]["source_objects"]
        }
        identifiers = {
            identifier
            for record in self.oracle["base_test_evidence"]
            for identifier in record["tests"]
        }
        identifiers.update(
            identifier
            for profile in self.oracle[
                "interruption_profiles"
            ].values()
            for identifier in profile["base_evidence"]
            if identifier.startswith("tests.")
        )
        for identifier in sorted(identifiers):
            with self.subTest(identifier=identifier):
                module_name, class_name, method_name = identifier.rsplit(
                    ".", 2
                )
                source_path = module_name.replace(".", "/") + ".py"
                self.assertIn(source_path, source_paths)
                module = importlib.import_module(module_name)
                test_class = getattr(module, class_name)
                self.assertTrue(
                    callable(getattr(test_class, method_name, None))
                )

    def test_candidate_has_no_oracle_regeneration_or_write_path(self) -> None:
        tree = ast.parse(ORACLE_PATH.read_text(encoding="utf-8"))
        forbidden_methods = {
            "write_bytes",
            "write_text",
            "touch",
            "unlink",
            "mkdir",
            "replace",
        }
        forbidden_calls: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_methods
            ):
                forbidden_calls.append(node.func.attr)
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "open"
                and (
                    len(node.args) > 1
                    or any(
                        keyword.arg == "mode"
                        for keyword in node.keywords
                    )
                )
            ):
                forbidden_calls.append("open")
        self.assertEqual(forbidden_calls, [])

        with self.assertRaises(oracle_module.OracleError) as captured:
            oracle_module._run_git(ROOT, ["checkout", "HEAD"])
        self.assertEqual(
            captured.exception.code, "ORACLE_GIT_COMMAND_FORBIDDEN"
        )

    def test_wrong_base_identity_and_fixture_tampering_fail_closed(
        self,
    ) -> None:
        wrong_base = copy.deepcopy(self.oracle)
        wrong_base["base"]["commit"] = "0" * 40
        with self.assertRaises(oracle_module.OracleError) as captured:
            oracle_module.validate_oracle(wrong_base)
        self.assertEqual(
            captured.exception.code,
            "ORACLE_BASE_IDENTITY_MISMATCH",
        )

        tampered = copy.deepcopy(self.oracle)
        tampered["cross_product"][0]["schemas"]["1"]["success"][
            "revision_delta"
        ] = 0
        with self.assertRaises(oracle_module.OracleError) as captured:
            oracle_module.validate_oracle(tampered)
        self.assertEqual(
            captured.exception.code,
            "ORACLE_FIXTURE_IDENTITY_MISMATCH",
        )

    def test_candidate_serializers_match_frozen_exact_bytes(self) -> None:
        contracts = self.oracle["byte_contracts"]
        for name in ("state_json", "mutation_quarantine"):
            with self.subTest(contract=name):
                contract = contracts[name]
                expected = bytes.fromhex(contract["exact_hex"])
                self.assertEqual(
                    dev_flow._json_bytes(contract["vector"]), expected
                )

        event_contract = contracts["event_jsonl"]
        expected_event = bytes.fromhex(event_contract["exact_hex"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_path = root / "events.jsonl"
            dev_flow._append_event(
                event_path, copy.deepcopy(event_contract["vector"])
            )
            self.assertEqual(event_path.read_bytes(), expected_event)
            dev_flow._append_event(
                event_path, copy.deepcopy(event_contract["vector"])
            )
            self.assertEqual(event_path.read_bytes(), expected_event)

            state_path = root / "state.json"
            state_contract = contracts["state_json"]
            dev_flow._atomic_write_json(
                state_path, copy.deepcopy(state_contract["vector"])
            )
            self.assertEqual(
                state_path.read_bytes(),
                bytes.fromhex(state_contract["exact_hex"]),
            )


class LegacyBaseOracleRejectionTest(test_case.DevFlowTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.oracle = oracle_module.load_frozen_oracle(FIXTURE_PATH)

    def _legacy_task(self, schema_version: int) -> tuple[dict, Path]:
        repository, _ = self.make_repo(
            f"oracle-rejection-v{schema_version}"
        )
        task = self.start(
            repository,
            task_id=f"oracle-rejection-v{schema_version}",
        )["task"]
        if schema_version == 1:
            state_path = dev_flow._state_path(
                task["task_id"], self.data
            )
            legacy = json.loads(
                state_path.read_text(encoding="utf-8")
            )
            legacy["schema_version"] = dev_flow.SCHEMA_VERSION
            legacy.pop("confirmation_contract_version", None)
            legacy.pop("risk_assessment", None)
            for item in legacy["repositories"]:
                item.pop("workspace_index", None)
                item.pop("index_history", None)
            dev_flow._atomic_write_json(state_path, legacy)
            task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["schema_version"], schema_version)
        return task, repository

    def test_every_variant_rejects_stale_revision_before_effect(self) -> None:
        rows = {
            row["variant_id"]: row
            for row in self.oracle["cross_product"]
        }
        for schema_version in (1, 2):
            task, repository = self._legacy_task(schema_version)
            artifact = self.root / (
                f"oracle-rejection-v{schema_version}.txt"
            )
            artifact.write_bytes(b"must remain unchanged\n")
            task_dir = dev_flow._task_dir(task["task_id"], self.data)
            state_path = task_dir / "state.json"
            events_path = task_dir / "events.jsonl"
            registry_path = self.data / "workspace-registry.json"
            invocations = {
                "baseline.fetch": (
                    "baseline",
                    ("--fetch",),
                ),
                "baseline.materialize": (
                    "baseline",
                    ("--materialize",),
                ),
                "preflight.capture": ("preflight", ()),
                "prepare-workspace.execute": (
                    "prepare-workspace",
                    ("--execute",),
                ),
                "prepare-workspace.plan": (
                    "prepare-workspace",
                    (),
                ),
                "record-artifact.observe": (
                    "record-artifact",
                    ("--kind", "oracle", "--path", str(artifact)),
                ),
                "record-test.fingerprint": (
                    "record-test",
                    (
                        "--name",
                        "oracle",
                        "--command",
                        "python3 -m unittest",
                        "--exit-code",
                        "0",
                    ),
                ),
                "review-snapshot.capture": (
                    "review-snapshot",
                    (),
                ),
            }
            for variant_id, (command, arguments) in invocations.items():
                with self.subTest(
                    schema=schema_version, variant=variant_id
                ):
                    state_before = state_path.read_bytes()
                    events_before = events_path.read_bytes()
                    artifact_before = artifact.read_bytes()
                    repository_before = (
                        git(repository, "rev-parse", "HEAD"),
                        git(repository, "status", "--porcelain=v2"),
                        git(repository, "for-each-ref", "--format=%(refname) %(objectname)"),
                    )
                    registry_before = (
                        registry_path.read_bytes()
                        if registry_path.exists()
                        else None
                    )
                    response = self.cli(
                        command,
                        task["task_id"],
                        "--expected-revision",
                        str(task["revision"] + 99),
                        *arguments,
                        expected_code=3,
                    )
                    expected = rows[variant_id]["schemas"][
                        str(schema_version)
                    ]["pre_effect_rejection"]
                    self.assertEqual(
                        response["error"]["code"],
                        expected["error_code"],
                    )
                    self.assertFalse(expected["effect_start"])
                    self.assertEqual(expected["revision_delta"], 0)
                    self.assertEqual(expected["durable_event_batch"], [])
                    self.assertEqual(state_path.read_bytes(), state_before)
                    self.assertEqual(
                        events_path.read_bytes(), events_before
                    )
                    self.assertEqual(artifact.read_bytes(), artifact_before)
                    self.assertEqual(
                        (
                            git(repository, "rev-parse", "HEAD"),
                            git(repository, "status", "--porcelain=v2"),
                            git(
                                repository,
                                "for-each-ref",
                                "--format=%(refname) %(objectname)",
                            ),
                        ),
                        repository_before,
                    )
                    self.assertEqual(
                        (
                            registry_path.read_bytes()
                            if registry_path.exists()
                            else None
                        ),
                        registry_before,
                    )
                    self.assertFalse(
                        (task_dir / "mutation-quarantine.json").exists()
                    )


class LegacyBaseOracleSuccessTest(test_case.DevFlowTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        oracle = oracle_module.load_frozen_oracle(FIXTURE_PATH)
        cls.rows = {
            row["variant_id"]: row
            for row in oracle["cross_product"]
        }

    def _downgrade_to_v1(self, task: dict) -> dict:
        state_path = dev_flow._state_path(task["task_id"], self.data)
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy["schema_version"] = dev_flow.SCHEMA_VERSION
        legacy.pop("confirmation_contract_version", None)
        legacy.pop("risk_assessment", None)
        for repository in legacy["repositories"]:
            repository.pop("workspace_index", None)
            repository.pop("index_history", None)
        dev_flow._atomic_write_json(state_path, legacy)
        return dev_flow.load_state(task["task_id"], self.data)

    def _capture(
        self,
        task: dict,
        variant_ids: tuple[str, ...],
        operation,
    ) -> tuple[dict, dict, list[str]]:
        task_dir = dev_flow._task_dir(task["task_id"], self.data)
        before_events = _events(task_dir)
        phases: list[str] = []
        real_update = dev_flow._update_mutation_intent

        def capture_phase(*args, **kwargs):
            phases.append(kwargs["phase"])
            return real_update(*args, **kwargs)

        with mock.patch.object(
            dev_flow,
            "_update_mutation_intent",
            side_effect=capture_phase,
        ):
            response = operation()
        current = dev_flow.load_state(task["task_id"], self.data)
        new_events = _events(task_dir)[len(before_events) :]
        event_batch = [event["type"] for event in new_events]
        for variant_id in variant_ids:
            expected = self.rows[variant_id]["schemas"][
                str(task["schema_version"])
            ]["success"]
            with self.subTest(
                schema=task["schema_version"], variant=variant_id
            ):
                self.assertTrue(expected["effect_start"])
                self.assertEqual(
                    current["revision"] - task["revision"],
                    expected["revision_delta"],
                )
                self.assertEqual(
                    event_batch, expected["durable_event_batch"]
                )
                self.assertIsNone(expected["error_code"])
                if expected["mutation_intent"] == "none":
                    self.assertEqual(phases, [])
                else:
                    self.assertIn("target_release_authorized", phases)
                    self.assertIn("child_quiescent", phases)
                self.assertFalse(
                    dev_flow._quarantine_path(task_dir).exists()
                )
        return response, current, phases

    def test_v1_v2_success_traces_match_every_frozen_variant(self) -> None:
        for schema_version in (1, 2):
            with self.subTest(schema=schema_version):
                repository, _ = self.make_repo(
                    f"oracle-success-v{schema_version}"
                )
                task = self.start(
                    repository,
                    task_id=f"oracle-success-v{schema_version}",
                )["task"]
                if schema_version == 1:
                    task = self._downgrade_to_v1(task)

                _, task, _ = self._capture(
                    task,
                    ("preflight.capture",),
                    lambda: self.mutate("preflight", task),
                )
                self.assertTrue(
                    task["repositories"][0]["preflight"][
                        "worktree_fingerprint_sha256"
                    ]
                )

                self.mutate(
                    "approve",
                    task,
                    "--gate",
                    "baseline-fetch",
                    "--note",
                    "immutable-base oracle approved local fetch",
                    "--allow-fetch",
                )
                task = dev_flow.load_state(task["task_id"], self.data)
                _, task, baseline_phases = self._capture(
                    task,
                    ("baseline.fetch", "baseline.materialize"),
                    lambda: self.mutate(
                        "baseline",
                        task,
                        "--fetch",
                        "--materialize",
                    ),
                )
                self.assertGreaterEqual(
                    baseline_phases.count("child_quiescent"), 2
                )
                recorded_repository = task["repositories"][0]
                self.assertTrue(recorded_repository["baseline"]["fetched"])
                self.assertTrue(
                    Path(
                        recorded_repository["analysis_workspace"]["path"]
                    ).is_dir()
                )

                self.mutate(
                    "record-index",
                    task,
                    "--index-id",
                    dev_flow._recommended_index_name(
                        task, task["repositories"][0], "baseline"
                    ),
                )
                task = dev_flow.load_state(task["task_id"], self.data)
                impact = self.root / (
                    f"oracle-success-v{schema_version}-impact.md"
                )
                impact.write_bytes(b"bounded oracle impact\n")
                impact_before = impact.read_bytes()
                artifact_response, task, _ = self._capture(
                    task,
                    ("record-artifact.observe",),
                    lambda: self.mutate(
                        "record-artifact",
                        task,
                        "--kind",
                        "impact",
                        "--path",
                        str(impact),
                    ),
                )
                self.assertEqual(impact.read_bytes(), impact_before)
                self.assertEqual(
                    artifact_response["artifact"]["sha256"],
                    dev_flow._sha256_file(impact),
                )

                self.mutate(
                    "set-route",
                    task,
                    "direct",
                    "--reason",
                    "bounded oracle route",
                )
                task = dev_flow.load_state(task["task_id"], self.data)
                self.mutate(
                    "approve",
                    task,
                    "--gate",
                    "route",
                    "--note",
                    "oracle impact reviewed",
                    "--artifact-sha256",
                    artifact_response["artifact"]["sha256"],
                )
                task = dev_flow.load_state(task["task_id"], self.data)
                plan_response, task, _ = self._capture(
                    task,
                    ("prepare-workspace.plan",),
                    lambda: self.mutate("prepare-workspace", task),
                )
                plan_path = Path(
                    plan_response["plan_artifact"]["path"]
                )
                self.assertTrue(plan_path.is_file())
                self.assertTrue(
                    (self.data / "workspace-registry.json").is_file()
                )
                self.assertFalse(
                    Path(plan_response["plans"][0]["path"]).exists()
                )

                self.mutate(
                    "approve",
                    task,
                    "--gate",
                    "workspace",
                    "--note",
                    "oracle workspace plan reviewed",
                    "--artifact-sha256",
                    plan_response["plan_artifact"]["sha256"],
                )
                task = dev_flow.load_state(task["task_id"], self.data)
                _, task, execute_phases = self._capture(
                    task,
                    ("prepare-workspace.execute",),
                    lambda: self.mutate(
                        "prepare-workspace", task, "--execute"
                    ),
                )
                self.assertIn("child_quiescent", execute_phases)
                workspace = Path(
                    task["repositories"][0]["workspace"]["path"]
                )
                self.assertTrue(workspace.is_dir())

                task = self.record_workspace_indexes(task)
                self.mutate("transition", task, "PLANNING")
                task = dev_flow.load_state(task["task_id"], self.data)
                contract = self.root / (
                    f"oracle-success-v{schema_version}-contract.md"
                )
                contract.write_text(
                    "bounded implementation contract\n",
                    encoding="utf-8",
                )
                contract_response = self.mutate(
                    "record-artifact",
                    task,
                    "--kind",
                    "direct-contract",
                    "--path",
                    str(contract),
                )
                task = dev_flow.load_state(task["task_id"], self.data)
                self.mutate(
                    "approve",
                    task,
                    "--gate",
                    "plan",
                    "--note",
                    "oracle contract reviewed",
                    "--artifact-sha256",
                    contract_response["artifact"]["sha256"],
                )
                task = dev_flow.load_state(task["task_id"], self.data)
                self.mutate("transition", task, "IMPLEMENTING")
                task = dev_flow.load_state(task["task_id"], self.data)
                (workspace / "oracle-untracked.txt").write_text(
                    "review me\n", encoding="utf-8"
                )
                task = self.record_workspace_indexes(task)
                self.mutate("transition", task, "VERIFYING")
                task = dev_flow.load_state(task["task_id"], self.data)

                _, task, _ = self._capture(
                    task,
                    ("record-test.fingerprint",),
                    lambda: self.mutate(
                        "record-test",
                        task,
                        "--name",
                        "oracle",
                        "--command",
                        "python3 -m unittest",
                        "--exit-code",
                        "0",
                    ),
                )
                fingerprint_reference = task["tests"][-1][
                    "fingerprints"
                ][task["repositories"][0]["id"]]
                self.assertTrue(
                    Path(fingerprint_reference["path"]).is_file()
                )

                review_response, task, _ = self._capture(
                    task,
                    ("review-snapshot.capture",),
                    lambda: self.mutate("review-snapshot", task),
                )
                manifest_path = Path(
                    review_response["snapshot"]["manifest_path"]
                )
                self.assertTrue(manifest_path.is_file())
                snapshot = task["review_snapshots"][-1]
                self.assertEqual(
                    snapshot["sha256"],
                    dev_flow._sha256_file(manifest_path),
                )
                review_fingerprint = snapshot["repositories"][0][
                    "fingerprint"
                ]
                self.assertTrue(
                    Path(review_fingerprint["path"]).is_file()
                )


class LegacyBaseOracleInterruptionTest(test_case.DevFlowTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        oracle = oracle_module.load_frozen_oracle(FIXTURE_PATH)
        cls.profiles = oracle["interruption_profiles"]

    def _profile_stages(self, name: str) -> dict[str, dict]:
        return {
            stage["id"]: stage["observation"]
            for stage in self.profiles[name]["supported_stages"]
        }

    def test_atomic_write_supported_stages_match_candidate(self) -> None:
        expected = self._profile_stages("atomic-write")
        destination = self.root / "atomic" / "state.json"
        dev_flow._atomic_write_bytes(destination, b"old\n")
        rollback = destination.parent / (
            f".{destination.name}{dev_flow._ROLLBACK_MARKER}oracle"
        )
        rollback.write_bytes(b"old\n")
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._atomic_write_bytes(destination, b"new\n")
        preexisting = expected["preexisting-rollback-block"]
        self.assertEqual(captured.exception.code, preexisting["error_code"])
        self.assertFalse(preexisting["effect_start"])
        self.assertEqual(destination.read_bytes(), b"old\n")
        rollback.unlink()

        real_permissions = dev_flow._set_private_permissions
        destination_checks = 0

        def fail_first_destination(path: Path, mode: int) -> None:
            nonlocal destination_checks
            if path == destination:
                destination_checks += 1
                if destination_checks == 1:
                    raise dev_flow.FlowError(
                        "PERMISSIONS_UNSAFE", "injected postcheck"
                    )
            real_permissions(path, mode)

        with mock.patch.object(
            dev_flow,
            "_set_private_permissions",
            side_effect=fail_first_destination,
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._atomic_write_bytes(destination, b"new\n")
        restored = expected["postcheck-restored"]
        self.assertEqual(captured.exception.code, restored["error_code"])
        self.assertTrue(restored["effect_start"])
        self.assertEqual(destination.read_bytes(), b"old\n")
        self.assertEqual(
            dev_flow._rollback_evidence_for(destination), []
        )

        destination_checks = 0
        real_replace = dev_flow.os.replace

        def fail_rollback_restore(source, target):
            if (
                Path(source).name.startswith(
                    f".{destination.name}{dev_flow._ROLLBACK_MARKER}"
                )
                and Path(target) == destination
            ):
                raise OSError(errno.EIO, "injected restore failure")
            return real_replace(source, target)

        with mock.patch.object(
            dev_flow,
            "_set_private_permissions",
            side_effect=fail_first_destination,
        ), mock.patch.object(
            dev_flow.os,
            "replace",
            side_effect=fail_rollback_restore,
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._atomic_write_bytes(
                    destination, b"uncertain\n"
                )
        uncertain = expected["postcheck-restore-uncertain"]
        self.assertEqual(captured.exception.code, uncertain["error_code"])
        self.assertTrue(uncertain["effect_start"])
        self.assertEqual(destination.read_bytes(), b"uncertain\n")
        evidence = dev_flow._rollback_evidence_for(destination)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].read_bytes(), b"old\n")

    def _review_cleanup_failure(
        self, *, cleanup_fails: bool
    ) -> tuple[str, Path]:
        repository = {"id": "repo", "path": str(self.root)}
        current = {
            "schema_version": 1,
            "task_id": "oracle-review-cleanup",
            "revision": 7,
            "status": "VERIFYING",
            "flow": "full",
            "repositories": [repository],
            "route": {"value": "direct"},
            "review_snapshots": [],
            "artifacts": [],
        }
        task_dir = self.root / (
            "review-cleanup-fails"
            if cleanup_fails
            else "review-cleanup-succeeds"
        )
        task_dir.mkdir()
        fingerprint = {"sha256": "a" * 64}

        @contextlib.contextmanager
        def locked(*_args, **_kwargs):
            yield task_dir, current

        def fail_after_write(
            snapshot_root: Path,
            _repository,
            *,
            task_dir=None,
            initial_fingerprint=None,
        ):
            partial = snapshot_root / "partial" / "section.patch"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"partial")
            raise dev_flow.FlowError(
                "REVIEW_SNAPSHOT_CHANGED", "injected drift"
            )

        arguments = types.SimpleNamespace(
            task_id=current["task_id"],
            task_option=None,
            data_dir=str(self.data),
            expected_revision=current["revision"],
            repo=None,
        )
        patches = [
            mock.patch.object(
                dev_flow, "_locked_state", side_effect=locked
            ),
            mock.patch.object(dev_flow, "_assert_flow"),
            mock.patch.object(dev_flow, "_assert_status"),
            mock.patch.object(
                dev_flow, "_require_current_workspace_indexes"
            ),
            mock.patch.object(dev_flow, "_require_workspace_ready"),
            mock.patch.object(dev_flow, "_require_current_plan_gate"),
            mock.patch.object(
                dev_flow, "_fingerprint_repo", return_value=fingerprint
            ),
            mock.patch.object(
                dev_flow,
                "_latest_passing_test_is_current",
                return_value=(True, None),
            ),
            mock.patch.object(
                dev_flow,
                "_repo_by_selector",
                return_value=[repository],
            ),
            mock.patch.object(
                dev_flow,
                "_write_review_repo",
                side_effect=fail_after_write,
            ),
        ]
        if cleanup_fails:
            patches.append(
                mock.patch.object(
                    dev_flow.shutil,
                    "rmtree",
                    side_effect=OSError(
                        errno.EIO, "injected cleanup failure"
                    ),
                )
            )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow.command_review_snapshot(arguments)
        return captured.exception.code, task_dir / "reviews"

    def test_review_cleanup_supported_stages_match_candidate(self) -> None:
        expected = self._profile_stages("review-cleanup")
        error_code, reviews = self._review_cleanup_failure(
            cleanup_fails=False
        )
        success = expected["capture-exception-cleanup-success"]
        self.assertEqual(error_code, success["error_code"])
        self.assertFalse(reviews.exists() and any(reviews.iterdir()))

        error_code, reviews = self._review_cleanup_failure(
            cleanup_fails=True
        )
        failed = expected["capture-exception-cleanup-failure"]
        self.assertEqual(error_code, failed["error_code"])
        self.assertTrue(reviews.exists() and any(reviews.iterdir()))

    def test_state_outbox_supported_stages_match_candidate(self) -> None:
        expected = self._profile_stages("state-outbox")
        repository, _ = self.make_repo("oracle-outbox")
        task = self.start(
            repository, task_id="oracle-outbox"
        )["task"]
        task_dir = dev_flow._task_dir(task["task_id"], self.data)
        current = dev_flow.load_state(task["task_id"], self.data)
        replacement = dev_flow._copy_state(current)
        replacement["requirement"] = "single pending oracle event"
        before_count = len(_events(task_dir))
        with mock.patch.object(
            dev_flow,
            "_append_event",
            side_effect=dev_flow.FlowError(
                "EVENT_APPEND_FAILED", "injected"
            ),
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._commit_state(
                    current,
                    replacement,
                    task_dir,
                    "oracle_event",
                )
        single = expected["event-append-interruption"]
        self.assertEqual(captured.exception.code, single["error_code"])
        persisted = json.loads(
            (task_dir / "state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            persisted["revision"] - current["revision"],
            single["revision_delta"],
        )
        self.assertIn("pending_event", persisted)
        self.assertEqual(len(_events(task_dir)), before_count)
        pending_id = persisted["pending_event"]["event_id"]
        dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            sum(
                event["event_id"] == pending_id
                for event in _events(task_dir)
            ),
            1,
        )

        current = dev_flow.load_state(task["task_id"], self.data)
        replacement = dev_flow._copy_state(current)
        replacement["requirement"] = "batched pending oracle events"
        real_append = dev_flow._append_event
        calls = 0

        def fail_second(path: Path, event: dict) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise dev_flow.FlowError(
                    "EVENT_APPEND_FAILED", "injected second append"
                )
            real_append(path, event)

        with mock.patch.object(
            dev_flow, "_append_event", side_effect=fail_second
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._commit_state(
                    current,
                    replacement,
                    task_dir,
                    "oracle_primary",
                    additional_events=[
                        ("oracle_linked", {"kind": "linked"})
                    ],
                )
        partial = expected["partial-batch-delivery"]
        self.assertEqual(captured.exception.code, partial["error_code"])
        persisted = json.loads(
            (task_dir / "state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            persisted["revision"] - current["revision"],
            partial["revision_delta"],
        )
        self.assertEqual(len(persisted["pending_events"]), 2)
        pending_ids = {
            event["event_id"] for event in persisted["pending_events"]
        }
        delivered = [
            event
            for event in _events(task_dir)
            if event["event_id"] in pending_ids
        ]
        self.assertEqual(
            len(delivered), len(partial["durable_event_batch"])
        )
        dev_flow.load_state(task["task_id"], self.data)
        recovered = [
            event
            for event in _events(task_dir)
            if event["event_id"] in pending_ids
        ]
        self.assertEqual(len(recovered), 2)
        self.assertEqual(
            len({event["event_id"] for event in recovered}), 2
        )

    def test_mutation_injection_inventory_is_bound_to_candidate_tests(
        self,
    ) -> None:
        profile = self.profiles["mutation-gate"]
        source = (
            ROOT / "scripts" / "dev_flow_parts" / "mutation.py"
        ).read_text(encoding="utf-8") + (
            ROOT / "scripts" / "dev_flow_parts" / "process.py"
        ).read_text(encoding="utf-8")
        phases = {
            "spawn_pending",
            "child_owned",
            "target_release_authorized",
            "interrupted_quiescent",
            "quiescence_unproven",
            "child_quiescent",
            "child_failed_quiescent",
        }
        for phase in phases:
            self.assertIn(f'"{phase}"', source)
        self.assertEqual(
            {
                stage["id"] for stage in profile["supported_stages"]
            },
            {
                "intent-write-failure",
                "spawn-pending-parent-crash",
                "target-release-parent-death",
                "communicate-interruption-quiescent",
                "communicate-interruption-unquiesced",
                "child-success-before-state-commit",
                "child-failed-quiescent",
                "gate-envelope-authentication-failure",
                "cleanup-interruption",
            },
        )
        for identifier in profile["base_evidence"]:
            module_name, class_name, method_name = identifier.rsplit(
                ".", 2
            )
            candidate_module = importlib.import_module(module_name)
            self.assertTrue(
                callable(
                    getattr(
                        getattr(candidate_module, class_name),
                        method_name,
                        None,
                    )
                )
            )

        task_dir = self.root / "mutation-intent-write"
        task_dir.mkdir()
        (task_dir / "state.json").write_text(
            '{"revision":1}\n', encoding="utf-8"
        )
        denied = dev_flow.FlowError(
            "ATOMIC_WRITE_FAILED", "injected intent write failure"
        )
        with dev_flow._task_lock(task_dir), mock.patch.object(
            dev_flow,
            "_atomic_write_json",
            side_effect=denied,
        ), mock.patch.object(dev_flow.subprocess, "Popen") as popen:
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._run(
                    ["git", "status"],
                    cwd=self.root,
                    mutation=True,
                )
        expected = self._profile_stages("mutation-gate")[
            "intent-write-failure"
        ]
        self.assertEqual(captured.exception.code, expected["error_code"])
        self.assertFalse(expected["effect_start"])
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
