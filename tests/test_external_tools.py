from __future__ import annotations

import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "external_tools.py"
)


def load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


external = load_module("dev_flow_external_tools_tests", MODULE_PATH)


def digest(character: str) -> str:
    return character * 64


class ExternalToolContractTests(unittest.TestCase):
    def capability(self) -> object:
        return external.ExternalToolCapability(
            capability_id="tool.codebase-memory/v1",
            tool_id=external.CODEBASE_MEMORY_TOOL_ID,
            operations=("external-read",),
            result_schema=external.CODEBASE_MEMORY_RESULT_SCHEMA,
            scopes=("src", "tests"),
        )

    def binding(
        self,
        phase: str,
        *,
        generation: str = "generation-7",
        repository_id: str = "repo-api",
        source: str = "a",
        project_id: str = "project-baseline",
    ) -> object:
        return external.CodebaseMemoryBinding(
            phase=phase,
            generation=generation,
            repository_id=repository_id,
            source_snapshot_sha256=digest(source),
            project_id=project_id,
        )

    def pair(self) -> tuple[object, object]:
        return (
            self.binding(
                external.CODEBASE_MEMORY_BASELINE_PHASE,
                source="a",
                project_id="project-baseline",
            ),
            self.binding(
                external.CODEBASE_MEMORY_CURRENT_PHASE,
                source="b",
                project_id="project-current-7",
            ),
        )

    def contracts(
        self,
        binding: object,
        *,
        revision: int = 8,
        scopes: tuple[str, ...] = ("src", "tests"),
        covered_scopes: tuple[str, ...] = ("src", "tests"),
        material: bool = True,
    ) -> tuple[object, object, object, object]:
        capability = self.capability()
        assignment = external.build_codebase_memory_assignment(
            capability,
            binding,
            controller_revision=revision,
            scopes=scopes,
        )
        request = external.build_codebase_memory_request(
            assignment,
            query="Find callers and verify them in the bound source.",
        )
        conclusion = external.ExternalConclusion(
            conclusion_id="call-path",
            claim="The public handler reaches the bound implementation.",
            material=material,
        )
        candidates = tuple(
            external.ExternalSourceCandidate(
                binding=binding,
                scope=scope,
                locator=f"{scope}/bound.py:10",
                source_sha256=digest(
                    "c" if scope == "src" else "d"
                ),
            )
            for scope in covered_scopes
        )
        result = external.CodebaseMemoryResult(
            assignment_sha256=assignment.sha256,
            request_sha256=request.sha256,
            binding=binding,
            controller_revision=revision,
            result_schema=capability.result_schema,
            covered_scopes=covered_scopes,
            source_candidates=candidates,
            conclusions=(conclusion,),
        )
        confirmation = external.BoundSourceConfirmation(
            binding=binding,
            conclusion_sha256=conclusion.sha256,
            scope="src",
            locator="src/bound.py:10",
            source_sha256=digest("c"),
            confirmed=True,
        )
        return assignment, request, result, confirmation

    def validate(
        self,
        binding: object,
        assignment: object,
        request: object,
        result: object,
        confirmations: tuple[object, ...],
        *,
        revision: int = 8,
    ) -> object:
        return external.validate_codebase_memory_result(
            capability=self.capability(),
            assignment=assignment,
            request=request,
            result=result,
            current_binding=binding,
            controller_project_bindings=self.pair(),
            current_controller_revision=revision,
            source_confirmations=confirmations,
        )

    def test_baseline_and_current_contracts_bind_distinct_projects(self) -> None:
        baseline, current = self.pair()
        external.validate_codebase_memory_project_pair(
            baseline, current
        )
        self.assertNotEqual(baseline.project_id, current.project_id)

        for binding in (baseline, current):
            assignment, request, result, confirmation = self.contracts(
                binding
            )
            decision = self.validate(
                binding,
                assignment,
                request,
                result,
                (confirmation,),
            )
            self.assertTrue(decision.accepted_candidate)
            self.assertTrue(decision.complete_evidence)
            self.assertEqual(assignment.binding, binding)
            self.assertEqual(request.binding, binding)
            self.assertEqual(result.binding, binding)
            self.assertEqual(
                external.parse_codebase_memory_assignment(
                    assignment.as_dict()
                ),
                assignment,
            )
            self.assertEqual(
                external.parse_codebase_memory_request(
                    request.as_dict()
                ),
                request,
            )
            self.assertEqual(
                external.parse_codebase_memory_result(
                    result.as_dict()
                ),
                result,
            )

    def test_project_identity_cannot_be_reused_across_phases(self) -> None:
        baseline, _ = self.pair()
        reused = self.binding(
            external.CODEBASE_MEMORY_CURRENT_PHASE,
            source="b",
            project_id=baseline.project_id,
        )
        with self.assertRaisesRegex(
            external.ExternalToolContractError,
            "project identities must differ",
        ):
            external.validate_codebase_memory_project_pair(
                baseline, reused
            )

        assignment, request, result, confirmation = self.contracts(
            baseline
        )
        with self.assertRaisesRegex(
            external.ExternalToolContractError,
            "project identities must differ",
        ):
            external.validate_codebase_memory_result(
                capability=self.capability(),
                assignment=assignment,
                request=request,
                result=result,
                current_binding=baseline,
                controller_project_bindings=(baseline, reused),
                current_controller_revision=8,
                source_confirmations=(confirmation,),
            )

    def test_assignment_request_and_result_require_exact_binding(self) -> None:
        _, current = self.pair()
        assignment, request, result, confirmation = self.contracts(
            current
        )
        mismatches = (
            self.binding(
                external.CODEBASE_MEMORY_BASELINE_PHASE,
                source="b",
                project_id="project-other",
            ),
            self.binding(
                external.CODEBASE_MEMORY_CURRENT_PHASE,
                generation="generation-8",
                source="b",
                project_id="project-current-7",
            ),
            self.binding(
                external.CODEBASE_MEMORY_CURRENT_PHASE,
                repository_id="repo-web",
                source="b",
                project_id="project-current-7",
            ),
            self.binding(
                external.CODEBASE_MEMORY_CURRENT_PHASE,
                source="e",
                project_id="project-current-7",
            ),
            self.binding(
                external.CODEBASE_MEMORY_CURRENT_PHASE,
                source="b",
                project_id="project-current-8",
            ),
        )
        for wrong_binding in mismatches:
            with self.subTest(binding=wrong_binding.as_dict()):
                with self.assertRaisesRegex(
                    external.ExternalToolContractError,
                    "binding",
                ):
                    self.validate(
                        current,
                        assignment,
                        request,
                        dataclasses.replace(
                            result, binding=wrong_binding
                        ),
                        (confirmation,),
                    )

        wrong_binding = mismatches[1]
        wrong_assignment = dataclasses.replace(
            assignment, binding=wrong_binding
        )
        with self.assertRaises(
            external.ExternalToolContractError
        ):
            self.validate(
                current,
                wrong_assignment,
                request,
                result,
                (confirmation,),
            )
        wrong_request = dataclasses.replace(
            request, binding=wrong_binding
        )
        with self.assertRaises(
            external.ExternalToolContractError
        ):
            self.validate(
                current,
                assignment,
                wrong_request,
                result,
                (confirmation,),
            )

        wrong_source_candidate = dataclasses.replace(
            result.source_candidates[0], binding=wrong_binding
        )
        wrong_source_result = dataclasses.replace(
            result,
            source_candidates=(
                wrong_source_candidate,
                result.source_candidates[1],
            ),
        )
        with self.assertRaisesRegex(
            external.ExternalToolContractError,
            "current source snapshot",
        ):
            self.validate(
                current,
                assignment,
                request,
                wrong_source_result,
                (confirmation,),
            )

    def test_stale_or_wrong_schema_result_fails_before_acceptance(self) -> None:
        _, current = self.pair()
        assignment, request, result, confirmation = self.contracts(
            current
        )
        with self.assertRaisesRegex(
            external.ExternalToolContractError, "not current"
        ):
            self.validate(
                current,
                assignment,
                request,
                dataclasses.replace(
                    result, controller_revision=7
                ),
                (confirmation,),
            )
        with self.assertRaisesRegex(
            external.ExternalToolContractError, "schema binding"
        ):
            self.validate(
                current,
                assignment,
                request,
                dataclasses.replace(
                    result, result_schema="unsupported-result/v1"
                ),
                (confirmation,),
            )

    def test_structural_source_candidates_do_not_confirm_material_claim(self) -> None:
        _, current = self.pair()
        assignment, request, result, confirmation = self.contracts(
            current
        )
        discovery_only = self.validate(
            current, assignment, request, result, ()
        )
        self.assertTrue(discovery_only.accepted_candidate)
        self.assertFalse(discovery_only.complete_evidence)
        self.assertEqual(
            discovery_only.reasons,
            ("material-conclusion-unconfirmed",),
        )

        confirmed = self.validate(
            current,
            assignment,
            request,
            result,
            (confirmation,),
        )
        self.assertTrue(confirmed.complete_evidence)

    def test_insufficient_source_coverage_cannot_complete_evidence(self) -> None:
        _, current = self.pair()
        assignment, request, result, confirmation = self.contracts(
            current, covered_scopes=("src",)
        )
        decision = self.validate(
            current,
            assignment,
            request,
            result,
            (confirmation,),
        )
        self.assertTrue(decision.accepted_candidate)
        self.assertFalse(decision.complete_evidence)
        self.assertEqual(
            decision.reasons, ("insufficient-source-coverage",)
        )

    def test_source_and_confirmation_scope_cannot_expand(self) -> None:
        _, current = self.pair()
        assignment, request, result, confirmation = self.contracts(
            current
        )
        expanded = dataclasses.replace(
            result,
            covered_scopes=("src", "tests", "vendor"),
            source_candidates=tuple(result.source_candidates)
            + (
                external.ExternalSourceCandidate(
                    binding=current,
                    scope="vendor",
                    locator="vendor/foreign.py:1",
                    source_sha256=digest("e"),
                ),
            ),
        )
        with self.assertRaisesRegex(
            external.ExternalToolContractError, "outside the exact request"
        ):
            self.validate(
                current,
                assignment,
                request,
                expanded,
                (confirmation,),
            )
        wrong_confirmation = dataclasses.replace(
            confirmation, scope="vendor"
        )
        with self.assertRaisesRegex(
            external.ExternalToolContractError,
            "outside the requested scope",
        ):
            self.validate(
                current,
                assignment,
                request,
                result,
                (wrong_confirmation,),
            )
        wrong_binding = self.binding(
            external.CODEBASE_MEMORY_CURRENT_PHASE,
            generation="generation-8",
            source="e",
            project_id="project-current-8",
        )
        with self.assertRaisesRegex(
            external.ExternalToolContractError,
            "not bound to the current snapshot",
        ):
            self.validate(
                current,
                assignment,
                request,
                result,
                (
                    dataclasses.replace(
                        confirmation, binding=wrong_binding
                    ),
                ),
            )

    def test_undeclared_tools_are_rejected_from_assignment_or_role(self) -> None:
        capability = self.capability()
        exposed = external.validate_tool_capability_exposure(
            (capability,), (capability.capability_id,)
        )
        self.assertEqual(exposed, (capability,))
        with self.assertRaisesRegex(
            external.ExternalToolContractError, "undeclared tool"
        ):
            external.validate_tool_capability_exposure(
                (capability,),
                (
                    capability.capability_id,
                    "tool.remote-writer/v1",
                ),
            )

    def test_catalog_role_and_execution_grant_bind_exact_content(self) -> None:
        capability = self.capability()
        graph = {
            "tool_capabilities": [
                {
                    key: value
                    for key, value in capability.identity_payload().items()
                }
            ]
        }
        declarations = (
            external.external_tool_capabilities_from_catalog(graph)
        )
        self.assertEqual(declarations, (capability,))
        profile = external.build_external_tool_role_profile(
            role_id="worker.read-only",
            declarations=declarations,
            exposed_capability_ids=(capability.capability_id,),
        )
        baseline, current = self.pair()
        assignment, request, _, _ = self.contracts(current)
        grant = external.build_external_tool_execution_grant(
            task_id="task-8",
            workflow_bundle_sha256=digest("f"),
            node_instance_id="workspace-index-8",
            action_id="full.workspace-index.v1",
            execution_id="execution-8",
            effect_id="workspace-index.effect",
            attempt=1,
            declarations=declarations,
            edge_capability_ids=(capability.capability_id,),
            capability_id=capability.capability_id,
            assignment=assignment,
            request=request,
            controller_project_bindings=(baseline, current),
            role_profile=profile,
        )

        binding = grant.runtime_binding()
        self.assertEqual(binding["assignment_sha256"], assignment.sha256)
        self.assertEqual(binding["request_sha256"], request.sha256)
        self.assertEqual(binding["phase"], current.phase)
        self.assertEqual(binding["generation"], current.generation)
        self.assertEqual(binding["repository_id"], current.repository_id)
        self.assertEqual(
            binding["source_snapshot_sha256"],
            current.source_snapshot_sha256,
        )
        self.assertEqual(binding["controller_revision"], 8)
        self.assertEqual(
            grant.as_safe_inputs(),
            {"external_tool_grant": binding},
        )

    def test_undeclared_tool_disappears_from_role_and_execution(self) -> None:
        capability = self.capability()
        with self.assertRaisesRegex(
            external.ExternalToolContractError, "undeclared tool"
        ):
            external.build_external_tool_role_profile(
                role_id="worker.read-only",
                declarations=(capability,),
                exposed_capability_ids=("tool.remote-writer/v1",),
            )
        baseline, current = self.pair()
        assignment, request, _, _ = self.contracts(current)
        with self.assertRaisesRegex(
            external.ExternalToolContractError, "absent from its action"
        ):
            external.build_external_tool_execution_grant(
                task_id="task-8",
                workflow_bundle_sha256=digest("f"),
                node_instance_id="workspace-index-8",
                action_id="full.workspace-index.v1",
                execution_id="execution-8",
                effect_id="workspace-index.effect",
                attempt=1,
                declarations=(capability,),
                edge_capability_ids=(),
                capability_id=capability.capability_id,
                assignment=assignment,
                request=request,
                controller_project_bindings=(baseline, current),
            )

    def test_schema_and_content_id_are_strict(self) -> None:
        capability = self.capability()
        parsed = external.ExternalToolCapability.from_dict(
            capability.as_dict()
        )
        self.assertEqual(parsed, capability)
        changed = capability.as_dict()
        changed["sha256"] = digest("0")
        with self.assertRaisesRegex(
            external.ExternalToolContractError,
            "identity does not match",
        ):
            external.ExternalToolCapability.from_dict(changed)

        _, current = self.pair()
        assignment, _, result, _ = self.contracts(current)
        malformed = result.as_dict()
        malformed["unknown"] = True
        with self.assertRaisesRegex(
            external.ExternalToolContractError,
            "fields do not match",
        ):
            external.parse_codebase_memory_result(malformed)
        with self.assertRaisesRegex(
            external.ExternalToolContractError, "floating-point"
        ):
            external.canonical_external_tool_bytes({"value": 1.5})
        self.assertEqual(
            assignment.sha256,
            external.parse_codebase_memory_assignment(
                assignment.as_dict()
            ).sha256,
        )


if __name__ == "__main__":
    unittest.main()
