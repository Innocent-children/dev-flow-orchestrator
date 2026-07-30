from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import MappingProxyType


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "runtime_adapters.py"
)
EXTERNAL_TOOLS_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "external_tools.py"
)
ORCHESTRATION_RESULTS_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "orchestration_results.py"
)
TELEMETRY_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "node_telemetry.py"
)
EXECUTOR_MANIFEST_PATH = (
    ROOT / "workflows" / "runtime" / "executors.json"
)
FIXTURE_PATH = (
    Path(__file__).with_name("fixtures")
    / "runtime_adapters"
    / "codex_exec_success.jsonl"
)


def load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime_module() -> object:
    name = "dev_flow_runtime_adapter_tests"
    spec = importlib.util.spec_from_loader(name, loader=None)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    for path in (EXTERNAL_TOOLS_PATH, MODULE_PATH):
        source = path.read_bytes()
        exec(compile(source, str(path), "exec"), module.__dict__)
    return module


runtime = load_runtime_module()
telemetry = load_module(
    "dev_flow_runtime_adapter_telemetry_tests", TELEMETRY_PATH
)
orchestration = load_module(
    "dev_flow_runtime_adapter_orchestration_tests",
    ORCHESTRATION_RESULTS_PATH,
)


PROMPT = "Implement only the assigned bounded node and return NodeResult."
BUNDLE = "b" * 64
INPUT = "c" * 64
QUIESCENCE = "d" * 64
AUTHORIZATION = "e" * 64


def schema_sha256() -> str:
    return hashlib.sha256(
        runtime.canonical_runtime_adapter_bytes(
            runtime.codex_exec_result_candidate_schema()
        )
    ).hexdigest()


def prompt_sha256() -> str:
    return hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()


def external_tool_grant(
    *,
    revision: int = 1,
    task_id: str = "task-a",
    node_id: str = "node-a",
    repository_id: str = "repo-a",
) -> object:
    capability = runtime.ExternalToolCapability(
        capability_id="tool.codebase-memory.read/v1",
        tool_id="codebase-memory",
        operations=("external-read",),
        result_schema=runtime.CODEBASE_MEMORY_RESULT_SCHEMA,
        scopes=("files",),
    )
    baseline = runtime.CodebaseMemoryBinding(
        phase="baseline",
        generation="generation-1",
        repository_id=repository_id,
        source_snapshot_sha256="1" * 64,
        project_id="baseline-project-1",
    )
    current = runtime.CodebaseMemoryBinding(
        phase="current-generation-workspace",
        generation="generation-1",
        repository_id=repository_id,
        source_snapshot_sha256="2" * 64,
        project_id="current-project-1",
    )
    assignment = runtime.build_codebase_memory_assignment(
        capability,
        current,
        controller_revision=revision,
        scopes=("files",),
    )
    request = runtime.build_codebase_memory_request(
        assignment, query="find changed files"
    )
    return runtime.build_external_tool_execution_grant(
        task_id=task_id,
        workflow_bundle_sha256=BUNDLE,
        node_instance_id=node_id,
        action_id="full.workspace-ready.record-workspace-index.v1",
        execution_id="execution-1",
        effect_id="workspace-index.effect",
        attempt=1,
        declarations=(capability,),
        edge_capability_ids=(capability.capability_id,),
        capability_id=capability.capability_id,
        assignment=assignment,
        request=request,
        controller_project_bindings=(baseline, current),
    )


def orchestration_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def orchestration_content_id(kind: str, value: str) -> str:
    return f"{kind}:{orchestration_digest(value)}"


def authoritative_node_result() -> dict[str, object]:
    value = {
        "schema": orchestration.ORCHESTRATION_NODE_RESULT_SCHEMA,
        "task_id": "task-1",
        "workflow_bundle_sha256": orchestration_digest("b"),
        "map_epoch": 3,
        "repository_id": "api",
        "node_instance_id": "node-api",
        "attempt": 1,
        "assignment_id": orchestration_content_id(
            "worker-assignment", "assignment-api"
        ),
        "lease_id": orchestration_content_id(
            "worker-lease", "lease-api"
        ),
        "lease_nonce": orchestration_digest("nonce-api"),
        "input_sha256": orchestration_digest("i"),
        "output_sha256": orchestration_digest("o"),
        "worktree_sha256": orchestration_digest("g"),
        "changed_paths_sha256": orchestration_digest("h"),
        "verification_sha256": orchestration_digest("v"),
        "outcome": "SUCCEEDED",
        "summary": "api result",
        "blockers": [],
        "plan_drift": {"detected": False, "reasons": []},
        "artifact_refs": [
            {
                "id": "artifact-api",
                "semantic_sha256": orchestration_digest(
                    "artifact-contract"
                ),
                "sha256": orchestration_digest("r"),
                "size": 321,
                "kind": "application.json",
                "locator": "artifact-api",
            }
        ],
        "evidence_refs": [
            {
                "id": "evidence-api",
                "semantic_sha256": orchestration_digest("e"),
                "sha256": orchestration_digest("r"),
                "size": 321,
                "kind": "test.report.v1",
                "locator": "evidence-api",
            }
        ],
        "runtime_handle": None,
    }
    bound = orchestration.bind_node_result_identity(value)
    return orchestration._orchestration_thaw(bound)


def authoritative_request() -> object:
    return runtime.build_runtime_execution_request(
        executor_id="executor.codex-exec/v1",
        task_id="task-1",
        workflow_bundle_sha256=orchestration_digest("b"),
        node_instance_id="node-api",
        repository_id="api",
        revision=7,
        attempt=1,
        input_sha256=orchestration_digest("i"),
        effect_classification="external-read",
        logical_model_policy="critical",
        workspace_path="/worktrees/api",
        prompt_sha256=prompt_sha256(),
        output_schema_sha256="a" * 64,
    )


def codex_request(
    *,
    attempt: int = 1,
    revision: int = 7,
    effect: str = "external-read",
    task_id: str = "task-a",
    node_id: str = "node-a",
    repository_id: str | None = "repo-a",
) -> object:
    approved_paths: tuple[str, ...] = ()
    if effect == "repository-write":
        approved_paths = ("src", "tests")
    return runtime.build_runtime_execution_request(
        executor_id="executor.codex-exec/v1",
        task_id=task_id,
        workflow_bundle_sha256=BUNDLE,
        node_instance_id=node_id,
        repository_id=repository_id,
        revision=revision,
        attempt=attempt,
        input_sha256=INPUT,
        effect_classification=effect,
        logical_model_policy="balanced",
        workspace_path="/worktrees/repo-a",
        approved_paths=approved_paths,
        prompt_sha256=prompt_sha256(),
        output_schema_sha256=schema_sha256(),
    )


def thread_request(
    *,
    attempt: int = 1,
    revision: int = 7,
    input_sha256: str = INPUT,
) -> object:
    return runtime.build_runtime_execution_request(
        executor_id="executor.codex-thread/v1",
        task_id="task-a",
        workflow_bundle_sha256=BUNDLE,
        node_instance_id="node-a",
        repository_id="repo-a",
        revision=revision,
        attempt=attempt,
        input_sha256=input_sha256,
        effect_classification="repository-write",
        logical_model_policy="balanced",
        workspace_path="/worktrees/repo-a",
        approved_paths=("src",),
        prompt_sha256="f" * 64,
    )


def parse_fixture(
    data: bytes | str | None = None,
    *,
    request: object | None = None,
) -> object:
    return runtime.parse_codex_exec_jsonl(
        FIXTURE_PATH.read_bytes() if data is None else data,
        request=codex_request() if request is None else request,
    )


def fixture_events() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
    ]


def encode_events(events: list[dict[str, object]]) -> bytes:
    return (
        "\n".join(
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for event in events
        )
        + "\n"
    ).encode("utf-8")


def final_node_result(
    events: list[dict[str, object]],
) -> dict[str, object]:
    for event in events:
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
        ):
            return json.loads(str(item["text"]))
    raise AssertionError("fixture has no final agent message")


def replace_final_node_result(
    events: list[dict[str, object]], value: object
) -> None:
    for event in events:
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
        ):
            item["text"] = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            return
    raise AssertionError("fixture has no final agent message")


class RuntimeAdapterRegistryTests(unittest.TestCase):
    def test_builtin_registry_covers_the_seven_versioned_surfaces(self) -> None:
        contracts = runtime.runtime_adapter_contracts()

        self.assertEqual(
            set(contracts),
            {
                "executor.barrier/v1",
                "executor.codex-exec/v1",
                "executor.codex-thread/v1",
                "executor.deterministic/v1",
                "executor.external-tool/v1",
                "executor.human-gate/v1",
                "executor.native-subagents/v1",
            },
        )
        self.assertIsInstance(contracts, MappingProxyType)
        self.assertTrue(all(item.result_schema == "dev-flow-node-result/v1"
                            for item in contracts.values()))
        self.assertTrue(
            contracts["executor.native-subagents/v1"].requires_host_isolation
        )
        self.assertEqual(
            contracts["executor.codex-thread/v1"].optional_runtime,
            "codex-sdk",
        )
        self.assertTrue(
            contracts["executor.codex-thread/v1"].supports_resume
        )
        self.assertFalse(
            contracts["executor.codex-exec/v1"].supports_resume
        )
        with self.assertRaises(TypeError):
            contracts["executor.new/v1"] = next(iter(contracts.values()))

        manifest = json.loads(
            EXECUTOR_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        entries = {item["id"]: item for item in manifest["entries"]}
        self.assertEqual(set(entries), set(contracts))
        for identifier, contract in contracts.items():
            self.assertEqual(
                entries[identifier]["contract_id"],
                contract.contract_version,
            )
            self.assertEqual(
                sorted(entries[identifier]["authority"]),
                list(contract.authority),
            )

    def test_registry_rejects_late_or_duplicate_registration(self) -> None:
        registry = runtime.RuntimeAdapterContractRegistry()
        contract = runtime.runtime_adapter_contracts()[
            "executor.barrier/v1"
        ]
        registry.register(contract)
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            registry.register(contract)
        self.assertEqual(
            raised.exception.code, "RUNTIME_CONTRACT_DUPLICATE"
        )

        registry.seal()
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            registry.register(contract)
        self.assertEqual(
            raised.exception.code, "RUNTIME_REGISTRY_SEALED"
        )

    def test_runtime_module_imports_no_optional_sdk(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])

        self.assertEqual(
            imports,
            {
                "__future__",
                "dataclasses",
                "hashlib",
                "json",
                "ntpath",
                "posixpath",
                "re",
                "types",
                "typing",
                "unicodedata",
            },
        )
        self.assertFalse(
            {"openai", "agents", "codex_sdk", "importlib"} & imports
        )

    def test_all_contracts_build_typed_requests_without_dispatch(self) -> None:
        cases = {
            "executor.deterministic/v1": ("controller", None, (), None),
            "executor.native-subagents/v1": (
                "repository-write",
                "repo-a",
                ("src",),
                "/worktrees/repo-a",
            ),
            "executor.codex-thread/v1": (
                "repository-write",
                "repo-a",
                ("src",),
                "/worktrees/repo-a",
            ),
            "executor.external-tool/v1": (
                "external-read",
                "repo-a",
                (),
                None,
            ),
            "executor.barrier/v1": ("barrier", None, (), None),
            "executor.human-gate/v1": ("approval", None, (), None),
        }
        for executor_id, (
            effect,
            repository_id,
            paths,
            workspace,
        ) in cases.items():
            with self.subTest(executor=executor_id):
                value = runtime.build_runtime_execution_request(
                    executor_id=executor_id,
                    task_id="task-a",
                    workflow_bundle_sha256=BUNDLE,
                    node_instance_id="node-a",
                    repository_id=repository_id,
                    revision=1,
                    attempt=1,
                    input_sha256=INPUT,
                    effect_classification=effect,
                    logical_model_policy=(
                        "balanced"
                        if "codex" in executor_id
                        or "subagents" in executor_id
                        else None
                    ),
                    capabilities=(),
                    workspace_path=workspace,
                    approved_paths=paths,
                    prompt_sha256=(
                        "a" * 64
                        if executor_id
                        in {
                            "executor.codex-thread/v1",
                            "executor.native-subagents/v1",
                            "executor.external-tool/v1",
                        }
                        else None
                    ),
                    external_tool_grant=(
                        external_tool_grant()
                        if executor_id == "executor.external-tool/v1"
                        else None
                    ),
                )
                self.assertEqual(value.executor_id, executor_id)
                self.assertTrue(value.request_id.startswith("runtime-request:"))

    def test_external_tool_uses_named_content_bound_grant(self) -> None:
        grant = external_tool_grant()
        value = runtime.build_runtime_execution_request(
            executor_id="executor.external-tool/v1",
            task_id=grant.task_id,
            workflow_bundle_sha256=grant.workflow_bundle_sha256,
            node_instance_id=grant.node_instance_id,
            repository_id=grant.binding.repository_id,
            revision=grant.assignment.controller_revision,
            attempt=grant.attempt,
            input_sha256=INPUT,
            effect_classification="external-read",
            external_tool_grant=grant,
        )

        self.assertEqual(value.capabilities, ())
        self.assertEqual(
            value.as_dict()["external_tool_grant"]["sha256"],
            grant.sha256,
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.build_runtime_execution_request(
                executor_id="executor.external-tool/v1",
                task_id=grant.task_id,
                workflow_bundle_sha256=grant.workflow_bundle_sha256,
                node_instance_id=grant.node_instance_id,
                repository_id=grant.binding.repository_id,
                revision=grant.assignment.controller_revision,
                attempt=grant.attempt,
                input_sha256=INPUT,
                effect_classification="external-read",
                capabilities=("repository.read/v1",),
                external_tool_grant=grant,
            )
        self.assertEqual(
            raised.exception.code,
            "RUNTIME_EXTERNAL_TOOL_CAPABILITY_CHANNEL_FORBIDDEN",
        )

    def test_external_tool_grant_binding_is_exact(self) -> None:
        grant = external_tool_grant()
        for field, replacement in (
            ("task_id", "other-task"),
            ("repository_id", "other-repo"),
            ("revision", 2),
            ("attempt", 2),
        ):
            kwargs = {
                "executor_id": "executor.external-tool/v1",
                "task_id": grant.task_id,
                "workflow_bundle_sha256": grant.workflow_bundle_sha256,
                "node_instance_id": grant.node_instance_id,
                "repository_id": grant.binding.repository_id,
                "revision": grant.assignment.controller_revision,
                "attempt": grant.attempt,
                "input_sha256": INPUT,
                "effect_classification": "external-read",
                "external_tool_grant": grant,
            }
            kwargs[field] = replacement
            with self.subTest(field=field), self.assertRaises(
                runtime.RuntimeAdapterError
            ) as raised:
                runtime.build_runtime_execution_request(**kwargs)
            self.assertEqual(
                raised.exception.code,
                "RUNTIME_EXTERNAL_TOOL_BINDING_MISMATCH",
            )

    def test_write_scope_and_paths_are_fail_closed(self) -> None:
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.build_runtime_execution_request(
                executor_id="executor.native-subagents/v1",
                task_id="task-a",
                workflow_bundle_sha256=BUNDLE,
                node_instance_id="node-a",
                revision=1,
                attempt=1,
                input_sha256=INPUT,
                effect_classification="repository-write",
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_WRITE_SCOPE_REQUIRED"
        )

        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.build_runtime_execution_request(
                executor_id="executor.native-subagents/v1",
                task_id="task-a",
                workflow_bundle_sha256=BUNDLE,
                node_instance_id="node-a",
                repository_id="repo-a",
                revision=1,
                attempt=1,
                input_sha256=INPUT,
                effect_classification="repository-write",
                workspace_path="/worktrees/repo-a",
                approved_paths=("../outside",),
            )
        self.assertEqual(raised.exception.code, "RUNTIME_PATH_INVALID")


class CodexExecContractTests(unittest.TestCase):
    def test_invocation_uses_jsonl_schema_stdin_and_read_only_sandbox(
        self,
    ) -> None:
        request = codex_request()
        invocation = runtime.build_codex_exec_invocation(
            request,
            prompt=PROMPT,
            output_schema_path="/controller/schema/node-result.json",
            resolved_model="host-resolved-model",
        )

        self.assertEqual(invocation.stdin_bytes, PROMPT.encode("utf-8"))
        self.assertNotIn(PROMPT, invocation.argv)
        self.assertEqual(invocation.argv[:2], ("codex", "exec"))
        self.assertIn("--json", invocation.argv)
        self.assertIn("--output-schema", invocation.argv)
        self.assertIn("--ephemeral", invocation.argv)
        self.assertIn("--ignore-user-config", invocation.argv)
        self.assertNotIn("--add-dir", invocation.argv)
        self.assertNotIn(
            "--dangerously-bypass-approvals-and-sandbox",
            invocation.argv,
        )
        self.assertEqual(
            invocation.argv[
                invocation.argv.index("--sandbox") + 1
            ],
            "read-only",
        )
        self.assertEqual(invocation.argv[-1], "-")
        self.assertEqual(
            hashlib.sha256(invocation.output_schema_bytes).hexdigest(),
            request.output_schema_sha256,
        )
        schema = json.loads(invocation.output_schema_bytes)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["$id"],
            "dev-flow-codex-exec-result-candidate/v1",
        )
        self.assertNotEqual(schema["$id"], "dev-flow-node-result/v1")
        self.assertNotIn("usage", schema["properties"])
        self.assertNotIn("runtime_handle", schema["properties"])

    def test_repository_write_uses_exact_worktree_and_workspace_sandbox(
        self,
    ) -> None:
        request = codex_request(effect="repository-write")
        invocation = runtime.build_codex_exec_invocation(
            request,
            prompt=PROMPT,
            output_schema_path="/controller/schema/node-result.json",
            resolved_model="host-resolved-model",
        )

        self.assertEqual(
            invocation.argv[
                invocation.argv.index("--sandbox") + 1
            ],
            "workspace-write",
        )
        self.assertEqual(
            invocation.argv[invocation.argv.index("--cd") + 1],
            "/worktrees/repo-a",
        )
        self.assertEqual(request.approved_paths, ("src", "tests"))

    def test_prompt_and_output_schema_are_content_bound(self) -> None:
        request = codex_request()
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.build_codex_exec_invocation(
                request,
                prompt=PROMPT + " changed",
                output_schema_path="/controller/schema/node-result.json",
            )
        self.assertEqual(
            raised.exception.code, "CODEX_EXEC_PROMPT_MISMATCH"
        )

        bad_schema = runtime.codex_exec_result_candidate_schema()
        bad_schema["title"] = "drift"
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.build_codex_exec_invocation(
                request,
                prompt=PROMPT,
                output_schema_path="/controller/schema/node-result.json",
                output_schema=bad_schema,
            )
        self.assertEqual(
            raised.exception.code,
            "CODEX_EXEC_OUTPUT_SCHEMA_MISMATCH",
        )

    def test_success_jsonl_returns_strict_result_and_official_usage(
        self,
    ) -> None:
        result = parse_fixture()

        self.assertEqual(
            result.thread_id, "019fa12c-2afd-72b2-a336-cace019c13f3"
        )
        self.assertFalse(result.authoritative)
        self.assertEqual(
            result.result_profile_id,
            "codex-exec-result-candidate/v1",
        )
        self.assertEqual(
            result.structured_result["schema"],
            "dev-flow-codex-exec-result-candidate/v1",
        )
        self.assertNotEqual(
            result.structured_result["schema"],
            "dev-flow-node-result/v1",
        )
        self.assertTrue(
            result.structured_result["candidate_id"].startswith(
                "codex-candidate-"
            )
        )
        self.assertEqual(result.structured_result["task_id"], "task-a")
        self.assertEqual(result.structured_result["attempt"], 1)
        self.assertEqual(
            result.structured_result["repository_id"], "repo-a"
        )
        self.assertEqual(result.usage["input_tokens"], 100)
        self.assertEqual(result.usage["cached_input_tokens"], 40)
        self.assertEqual(result.usage["output_tokens"], 20)
        self.assertEqual(result.usage["reasoning_output_tokens"], 10)
        self.assertIsNone(result.usage_diagnostic)
        self.assertEqual(result.event_count, 5)
        self.assertEqual(
            result.response_bytes, len(FIXTURE_PATH.read_bytes())
        )
        observation = telemetry.build_node_telemetry(
            task_id="task-a",
            bundle_sha256=BUNDLE,
            node_instance_id="node-a",
            repository_id="repo-a",
            revision=7,
            attempt=1,
            executor_policy="executor.codex-exec/v1",
            model_policy="balanced",
            orchestration_role="worker",
            adapter_outcome="SUCCEEDED",
            evidence_outcome="SUCCEEDED",
            started_at="2026-07-27T00:00:00.000Z",
            ended_at="2026-07-27T00:00:00.100Z",
            duration_ms=100,
            response_bytes=result.response_bytes,
            artifact_bytes=0,
            usage=result.usage,
        )
        self.assertEqual(observation.usage["status"], "available")
        self.assertEqual(observation.usage["input_tokens"], 100)
        with self.assertRaises(TypeError):
            result.structured_result["outcome"] = "FAILED"

    def test_injected_authoritative_result_uses_orchestration_validator(
        self,
    ) -> None:
        events = fixture_events()
        replace_final_node_result(events, authoritative_node_result())

        result = runtime.parse_codex_exec_jsonl(
            encode_events(events),
            request=authoritative_request(),
            node_result_validator=(
                orchestration.validate_orchestration_node_result
            ),
            result_profile=(
                runtime.ORCHESTRATION_NODE_RESULT_PROFILE
            ),
        )

        self.assertTrue(result.authoritative)
        self.assertEqual(
            result.result_profile_id,
            "orchestration-node-result/v1",
        )
        self.assertEqual(
            result.structured_result["schema"],
            "dev-flow-node-result/v1",
        )
        self.assertTrue(
            result.structured_result["result_id"].startswith(
                "node-result-"
            )
        )

    def test_missing_or_contradictory_usage_is_observational_only(
        self,
    ) -> None:
        events = fixture_events()
        events[-1].pop("usage")
        result = parse_fixture(encode_events(events))
        self.assertEqual(
            result.structured_result["outcome"], "SUCCEEDED"
        )
        self.assertIsNone(result.usage)
        self.assertEqual(
            result.usage_diagnostic["reason"],
            "turn-completed-usage-missing",
        )

        events = fixture_events()
        events[-1]["usage"]["cached_input_tokens"] = 101
        result = parse_fixture(encode_events(events))
        self.assertEqual(
            result.structured_result["outcome"], "SUCCEEDED"
        )
        self.assertIsNone(result.usage)
        self.assertEqual(
            result.usage_diagnostic["reason"],
            "turn-completed-usage-contradictory",
        )

    def test_node_result_exact_binding_is_enforced_beyond_validator(self) -> None:
        for field, value in (
            ("workflow_bundle_sha256", "a" * 64),
            ("node_instance_id", "other-node"),
            ("attempt", 2),
            ("repository_id", "other-repo"),
        ):
            with self.subTest(field=field):
                events = fixture_events()
                node_result = final_node_result(events)
                node_result[field] = value
                replace_final_node_result(events, node_result)
                with self.assertRaises(
                    runtime.RuntimeAdapterError
                ) as raised:
                    parse_fixture(encode_events(events))
                self.assertEqual(
                    raised.exception.code,
                    "CODEX_EXEC_NODE_RESULT_BINDING_MISMATCH",
                )

    def test_free_form_incomplete_or_model_minted_metadata_is_rejected(
        self,
    ) -> None:
        events = fixture_events()
        replace_final_node_result(events, "done")
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            parse_fixture(encode_events(events))
        self.assertEqual(
            raised.exception.code, "CODEX_EXEC_FINAL_OUTPUT_INVALID"
        )

        events = fixture_events()
        node_result = final_node_result(events)
        node_result.pop("plan_drift")
        replace_final_node_result(events, node_result)
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            parse_fixture(encode_events(events))
        self.assertEqual(
            raised.exception.code, "CODEX_EXEC_NODE_RESULT_INCOMPLETE"
        )

        for field, value in (
            (
                "runtime_handle",
                {"kind": "codex-thread", "handle_id": "invented"},
            ),
            (
                "usage",
                {
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                },
            ),
        ):
            with self.subTest(field=field):
                events = fixture_events()
                node_result = final_node_result(events)
                node_result[field] = value
                replace_final_node_result(events, node_result)
                with self.assertRaises(
                    runtime.RuntimeAdapterError
                ) as raised:
                    parse_fixture(encode_events(events))
                self.assertEqual(
                    raised.exception.code,
                    "CODEX_EXEC_NODE_RESULT_AUTHORITY_INVALID",
                )

    def test_event_stream_ambiguity_failure_and_order_are_rejected(
        self,
    ) -> None:
        events = fixture_events()
        events.insert(4, events[3].copy())
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            parse_fixture(encode_events(events))
        self.assertEqual(
            raised.exception.code,
            "CODEX_EXEC_FINAL_OUTPUT_AMBIGUOUS",
        )

        events = fixture_events()
        events.insert(
            -1,
            {
                "type": "turn.failed",
                "error": {"message": "subprocess interrupted"},
            },
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            parse_fixture(encode_events(events))
        self.assertEqual(
            raised.exception.code, "CODEX_EXEC_TURN_FAILED"
        )

        events = fixture_events()
        events.append({"type": "diagnostic", "message": "late"})
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            parse_fixture(encode_events(events))
        self.assertEqual(
            raised.exception.code, "CODEX_EXEC_EVENT_ORDER_INVALID"
        )

    def test_json_duplicate_keys_and_missing_validator_fail_closed(
        self,
    ) -> None:
        data = (
            '{"type":"thread.started","type":"thread.started",'
            '"thread_id":"thread-a"}\n'
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.parse_codex_exec_jsonl(
                data,
                request=codex_request(),
            )
        self.assertEqual(
            raised.exception.code, "CODEX_EXEC_JSON_DUPLICATE_KEY"
        )

        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.parse_codex_exec_jsonl(
                FIXTURE_PATH.read_bytes(),
                request=codex_request(),
                result_profile=(
                    runtime.ORCHESTRATION_NODE_RESULT_PROFILE
                ),
            )
        self.assertEqual(
            raised.exception.code,
            "RUNTIME_NODE_RESULT_VALIDATOR_UNAVAILABLE",
        )


class RuntimeHandleRecoveryTests(unittest.TestCase):
    def test_handle_record_and_workflow_reference_are_separate(self) -> None:
        request = thread_request()
        handle = runtime.build_runtime_handle_record(
            request, handle_id="thread-a"
        )
        record = runtime.build_runtime_attempt_record(
            request, phase="running", runtime_handle=handle
        )

        self.assertEqual(handle.availability, "available")
        self.assertEqual(record.runtime_handle_id, "thread-a")
        reference = handle.workflow_reference()
        self.assertEqual(
            set(reference),
            {
                "schema",
                "handle_id",
                "kind",
                "task_id",
                "node_instance_id",
                "repository_id",
                "attempt",
            },
        )
        self.assertNotIn("availability", reference)
        self.assertNotIn("request_id", reference)
        self.assertNotIn("executor_id", reference)
        self.assertNotIn("state", handle.as_dict())
        self.assertNotIn("status", handle.as_dict())
        self.assertNotIn("evidence", handle.as_dict())

    def test_new_attempt_starts_and_exact_available_handle_resumes(self) -> None:
        request = thread_request()
        decision = runtime.plan_runtime_dispatch(request)
        self.assertEqual(decision.action, "start")

        handle = runtime.build_runtime_handle_record(
            request, handle_id="thread-a"
        )
        attempt = runtime.build_runtime_attempt_record(
            request, phase="running", runtime_handle=handle
        )
        decision = runtime.plan_runtime_dispatch(
            request, attempts=(attempt,), handles=(handle,)
        )
        self.assertEqual(decision.action, "resume")
        self.assertEqual(decision.runtime_handle_id, "thread-a")
        self.assertEqual(decision.attempt, 1)

    def test_unavailable_handle_never_restarts_same_attempt(self) -> None:
        request = thread_request()
        handle = runtime.build_runtime_handle_record(
            request, handle_id="thread-a"
        )
        unavailable = runtime.update_runtime_handle(
            handle, availability="unavailable"
        )
        attempt = runtime.build_runtime_attempt_record(
            request, phase="unavailable", runtime_handle=unavailable
        )

        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                request,
                attempts=(attempt,),
                handles=(unavailable,),
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_HANDLE_UNAVAILABLE"
        )

        reattached = runtime.reattach_runtime_handle(
            unavailable, observed_handle_id="thread-a"
        )
        decision = runtime.plan_runtime_dispatch(
            request, attempts=(attempt,), handles=(reattached,)
        )
        self.assertEqual(decision.action, "resume")

    def test_duplicate_nonresumable_attempt_and_conflict_fail_closed(
        self,
    ) -> None:
        request = codex_request()
        attempt = runtime.build_runtime_attempt_record(
            request, phase="running"
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                request, attempts=(attempt,)
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_DUPLICATE_ATTEMPT"
        )

        changed_request = codex_request(revision=8)
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                changed_request, attempts=(attempt,)
            )
        self.assertEqual(
            raised.exception.code,
            "RUNTIME_DUPLICATE_ATTEMPT_CONFLICT",
        )

        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                request, attempts=(attempt, attempt)
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_DUPLICATE_ATTEMPT"
        )

    def test_orphan_or_mismatched_handle_blocks_dispatch(self) -> None:
        request = thread_request()
        handle = runtime.build_runtime_handle_record(
            request, handle_id="thread-a"
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                request, handles=(handle,)
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_ORPHAN_HANDLE"
        )

        attempt = runtime.build_runtime_attempt_record(
            request, phase="running", runtime_handle=handle
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                request, attempts=(attempt,)
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_HANDLE_UNAVAILABLE"
        )

    def test_unavailable_is_not_quiescence_and_cannot_authorize_replacement(
        self,
    ) -> None:
        first = thread_request()
        handle = runtime.build_runtime_handle_record(
            first, handle_id="thread-a"
        )
        unavailable = runtime.update_runtime_handle(
            handle, availability="unavailable"
        )
        attempt = runtime.build_runtime_attempt_record(
            first, phase="unavailable", runtime_handle=unavailable
        )
        second = thread_request(attempt=2, revision=8)

        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                second,
                attempts=(attempt,),
                handles=(unavailable,),
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_REPLACEMENT_NOT_QUIESCED"
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.build_runtime_replacement_proof(
                attempt,
                next_attempt=2,
                authorization_sha256=AUTHORIZATION,
                reason="recovery",
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_REPLACEMENT_NOT_QUIESCED"
        )

    def test_safe_replacement_requires_matching_quiescence_and_authority(
        self,
    ) -> None:
        first = thread_request()
        handle = runtime.build_runtime_handle_record(
            first, handle_id="thread-a"
        )
        running = runtime.build_runtime_attempt_record(
            first, phase="running", runtime_handle=handle
        )
        quiesced_handle = runtime.update_runtime_handle(
            handle,
            availability="quiesced",
            quiescence_evidence_sha256=QUIESCENCE,
        )
        quiesced_attempt = runtime.update_runtime_attempt(
            running,
            phase="quiesced",
            runtime_handle=quiesced_handle,
            quiescence_evidence_sha256=QUIESCENCE,
        )
        second = thread_request(attempt=2, revision=8)

        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_runtime_dispatch(
                second,
                attempts=(quiesced_attempt,),
                handles=(quiesced_handle,),
            )
        self.assertEqual(
            raised.exception.code,
            "RUNTIME_REPLACEMENT_PROOF_REQUIRED",
        )

        proof = runtime.build_runtime_replacement_proof(
            quiesced_attempt,
            next_attempt=2,
            authorization_sha256=AUTHORIZATION,
            reason="recovery",
        )
        decision = runtime.plan_runtime_dispatch(
            second,
            attempts=(quiesced_attempt,),
            handles=(quiesced_handle,),
            replacement_proof=proof,
        )
        self.assertEqual(decision.action, "replace")
        self.assertEqual(decision.replaced_attempt, 1)
        self.assertEqual(decision.attempt, 2)

    def test_handle_cannot_be_replaced_or_revived_within_attempt(self) -> None:
        request = thread_request()
        handle = runtime.build_runtime_handle_record(
            request, handle_id="thread-a"
        )
        attempt = runtime.build_runtime_attempt_record(
            request, phase="running", runtime_handle=handle
        )
        other = runtime.build_runtime_handle_record(
            request, handle_id="thread-b"
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.update_runtime_attempt(
                attempt, phase="running", runtime_handle=other
            )
        self.assertEqual(
            raised.exception.code,
            "RUNTIME_HANDLE_REPLACEMENT_FORBIDDEN",
        )

        quiesced = runtime.update_runtime_handle(
            handle,
            availability="quiesced",
            quiescence_evidence_sha256=QUIESCENCE,
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.update_runtime_handle(
                quiesced, availability="available"
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_HANDLE_TERMINAL"
        )


if __name__ == "__main__":
    unittest.main()
