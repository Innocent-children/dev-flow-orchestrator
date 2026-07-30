from __future__ import annotations

import pickle
import unittest

from tests.support import load_controller, runtime_services


def digest(character: str) -> str:
    return character * 64


class V4ExternalToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.namespace = load_controller()
        cls.full = runtime_services().catalog.bundles[("full", 4)]

    def test_least_capability_codebase_memory_evidence_is_source_bound(
        self,
    ) -> None:
        n = self.namespace
        capability = n["ExternalToolCapability"](
            capability_id="tool.codebase-memory/v1",
            tool_id=n["CODEBASE_MEMORY_TOOL_ID"],
            operations=("external-read",),
            result_schema=n["CODEBASE_MEMORY_RESULT_SCHEMA"],
            scopes=("src", "tests"),
        )
        baseline = n["CodebaseMemoryBinding"](
            phase=n["CODEBASE_MEMORY_BASELINE_PHASE"],
            generation="generation-4",
            repository_id="repo-api",
            source_snapshot_sha256=digest("a"),
            project_id="project-baseline",
        )
        current = n["CodebaseMemoryBinding"](
            phase=n["CODEBASE_MEMORY_CURRENT_PHASE"],
            generation="generation-4",
            repository_id="repo-api",
            source_snapshot_sha256=digest("b"),
            project_id="project-current",
        )
        n["validate_codebase_memory_project_pair"](baseline, current)
        self.assertNotEqual(baseline.project_id, current.project_id)

        assignment = n["build_codebase_memory_assignment"](
            capability,
            current,
            controller_revision=8,
            scopes=("src", "tests"),
        )
        request = n["build_codebase_memory_request"](
            assignment,
            query="Find callers and confirm them in the bound source.",
        )
        conclusion = n["ExternalConclusion"](
            conclusion_id="call-path",
            claim="The public handler reaches the bound implementation.",
            material=True,
        )
        candidates = tuple(
            n["ExternalSourceCandidate"](
                binding=current,
                scope=scope,
                locator=f"{scope}/bound.py:10",
                source_sha256=digest(
                    "c" if scope == "src" else "d"
                ),
            )
            for scope in ("src", "tests")
        )
        result = n["CodebaseMemoryResult"](
            assignment_sha256=assignment.sha256,
            request_sha256=request.sha256,
            binding=current,
            controller_revision=8,
            result_schema=capability.result_schema,
            covered_scopes=("src", "tests"),
            source_candidates=candidates,
            conclusions=(conclusion,),
        )
        confirmation = n["BoundSourceConfirmation"](
            binding=current,
            conclusion_sha256=conclusion.sha256,
            scope="src",
            locator="src/bound.py:10",
            source_sha256=digest("c"),
            confirmed=True,
        )
        decision = n["validate_codebase_memory_result"](
            capability=capability,
            assignment=assignment,
            request=request,
            result=result,
            current_binding=current,
            controller_project_bindings=(baseline, current),
            current_controller_revision=8,
            source_confirmations=(confirmation,),
        )
        self.assertTrue(decision.accepted_candidate)
        self.assertTrue(decision.complete_evidence)
        self.assertEqual(assignment.binding, current)
        self.assertEqual(result.binding, current)

    def test_serialized_host_workflow_write_boundary_is_one_shot(self) -> None:
        n = self.namespace
        clock = [100.0]
        issuer = n["WorkflowWriteAuthorizationIssuer"](
            monotonic_clock=lambda: clock[0]
        )
        gate = n["WorkflowWriteGateDecision"](
            gate_id="external.publish",
            decision="approved",
            controller_revision=17,
            decision_sha256=digest("a"),
        )
        binding = n["WorkflowWriteBinding"](
            bundle_sha256=digest("b"),
            action_id="release.publish",
            execution_id="execution-17",
            effect_id="provider-write-1",
            gate_sha256=gate.sha256,
            nonce=digest("c"),
        )
        request = {
            "schema": "fake-provider-request/v1",
            "operation": "publish",
            "payload": {"name": "candidate"},
        }
        target = {
            "provider": "fake",
            "account": "sandbox",
            "resource": "artifact-17",
        }
        authorization = issuer.issue(
            binding=binding,
            request=request,
            target=target,
            gate=gate,
            ttl_seconds=10,
        )
        events = []
        provider_calls = []

        def approve(challenge, approved_request, approved_target):
            events.append("host-approval")
            return challenge.approve(
                request=approved_request, target=approved_target
            )

        def provider(provider_request, provider_target):
            events.append("provider")
            provider_calls.append((provider_request, provider_target))
            return {"provider": "fake", "sequence": len(provider_calls)}

        bridge = n["HostOwnedExternalWriteBridge"](
            issuer=issuer,
            approval_callback=approve,
            provider=provider,
            wall_clock_ns=lambda: 123456789,
        )
        outcome = bridge.invoke(
            authorization=authorization,
            binding=binding,
            request=request,
            target=target,
        )
        self.assertEqual(events, ["host-approval", "provider"])
        self.assertEqual(len(provider_calls), 1)
        self.assertEqual(
            outcome.receipt.request_sha256,
            n["canonical_external_write_request_sha256"](request),
        )
        self.assertEqual(
            outcome.receipt.target_sha256,
            n["canonical_external_write_target_sha256"](target),
        )
        self.assertEqual(
            outcome.receipt.workflow_binding_sha256, binding.sha256
        )
        with self.assertRaisesRegex(n["ExternalWriteError"], "consumed"):
            bridge.invoke(
                authorization=authorization,
                binding=binding,
                request=request,
                target=target,
            )
        self.assertEqual(len(provider_calls), 1)
        with self.assertRaises(TypeError):
            pickle.dumps(authorization)

    def test_full_placements_bind_read_only_external_policy(self) -> None:
        placements = [
            edge
            for edge in self.full.action_edges
            if "v4-external-tools" in edge["required_suites"]
        ]
        self.assertTrue(placements)
        for edge in placements:
            policy = edge["tool_policy"]
            self.assertTrue(policy["capabilities"])
            self.assertEqual(policy["write_gate"], "read-only")
            self.assertEqual(
                policy["source_validation"],
                "source-confirmation-required",
            )


if __name__ == "__main__":
    unittest.main()
