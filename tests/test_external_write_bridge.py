from __future__ import annotations

import copy
import importlib.util
import pickle
import sys
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "scripts"
    / "dev_flow_parts"
    / "external_write_bridge.py"
)


def load_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge_contract = load_module(
    "dev_flow_external_write_bridge_tests", MODULE_PATH
)


def digest(character: str) -> str:
    return character * 64


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self.seen: list[tuple[object, object]] = []

    def __call__(self, request: object, target: object) -> object:
        self.calls += 1
        self.seen.append((request, target))
        if self.fail:
            raise RuntimeError("provider failed after invocation")
        return {"provider": "fake", "sequence": self.calls}


class ExternalWriteBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.issuer = (
            bridge_contract.WorkflowWriteAuthorizationIssuer(
                monotonic_clock=self.clock
            )
        )
        self.gate = bridge_contract.WorkflowWriteGateDecision(
            gate_id="external.publish",
            decision="approved",
            controller_revision=17,
            decision_sha256=digest("a"),
        )
        self.binding = bridge_contract.WorkflowWriteBinding(
            bundle_sha256=digest("b"),
            action_id="release.publish",
            execution_id="execution-17",
            effect_id="provider-write-1",
            gate_sha256=self.gate.sha256,
            nonce=digest("c"),
        )
        self.request = {
            "schema": "fake-provider-request/v1",
            "operation": "publish",
            "payload": {"name": "candidate"},
        }
        self.target = {
            "provider": "fake",
            "account": "sandbox",
            "resource": "artifact-17",
        }

    def authorization(
        self,
        *,
        binding: object | None = None,
        request: object | None = None,
        target: object | None = None,
        gate: object | None = None,
        ttl_seconds: float = 10,
    ) -> object:
        return self.issuer.issue(
            binding=self.binding if binding is None else binding,
            request=self.request if request is None else request,
            target=self.target if target is None else target,
            gate=self.gate if gate is None else gate,
            ttl_seconds=ttl_seconds,
        )

    @staticmethod
    def approving_host(
        challenge: object, request: object, target: object
    ) -> object:
        return challenge.approve(request=request, target=target)

    def bridge(
        self,
        provider: object,
        approval_callback: object | None = None,
    ) -> object:
        return bridge_contract.HostOwnedExternalWriteBridge(
            issuer=self.issuer,
            approval_callback=(
                self.approving_host
                if approval_callback is None
                else approval_callback
            ),
            provider=provider,
            wall_clock_ns=lambda: 123456789,
        )

    def invoke(
        self,
        serial_bridge: object,
        authorization: object,
        *,
        binding: object | None = None,
        request: object | None = None,
        target: object | None = None,
        **claims: object,
    ) -> object:
        return serial_bridge.invoke(
            authorization=authorization,
            binding=self.binding if binding is None else binding,
            request=self.request if request is None else request,
            target=self.target if target is None else target,
            **claims,
        )

    def test_exact_serial_workflow_and_host_approval_invokes_once(self) -> None:
        events: list[str] = []
        provider = FakeProvider()

        def host(
            challenge: object, request: object, target: object
        ) -> object:
            events.append("host-approval")
            return challenge.approve(request=request, target=target)

        def ordered_provider(request: object, target: object) -> object:
            events.append("provider")
            return provider(request, target)

        serial_bridge = self.bridge(ordered_provider, host)
        authorization = self.authorization()
        outcome = self.invoke(serial_bridge, authorization)

        self.assertEqual(events, ["host-approval", "provider"])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            outcome.receipt.request_sha256,
            bridge_contract.canonical_external_write_request_sha256(
                self.request
            ),
        )
        self.assertEqual(
            outcome.receipt.target_sha256,
            bridge_contract.canonical_external_write_target_sha256(
                self.target
            ),
        )
        self.assertEqual(
            outcome.receipt.workflow_binding_sha256,
            self.binding.sha256,
        )
        with self.assertRaisesRegex(
            bridge_contract.ExternalWriteError, "consumed"
        ):
            self.invoke(serial_bridge, authorization)
        self.assertEqual(provider.calls, 1)

    def test_missing_or_denied_workflow_gate_never_invokes(self) -> None:
        provider = FakeProvider()
        serial_bridge = self.bridge(provider)
        with self.assertRaisesRegex(
            bridge_contract.ExternalWriteError, "requires a current gate"
        ):
            self.issuer.issue(
                binding=self.binding,
                request=self.request,
                target=self.target,
                gate=None,
            )
        denied_gate = bridge_contract.WorkflowWriteGateDecision(
            gate_id=self.gate.gate_id,
            decision="denied",
            controller_revision=self.gate.controller_revision,
            decision_sha256=digest("d"),
        )
        denied_binding = bridge_contract.WorkflowWriteBinding(
            bundle_sha256=self.binding.bundle_sha256,
            action_id=self.binding.action_id,
            execution_id=self.binding.execution_id,
            effect_id=self.binding.effect_id,
            gate_sha256=denied_gate.sha256,
            nonce=digest("e"),
        )
        with self.assertRaisesRegex(
            bridge_contract.ExternalWriteError, "does not permit"
        ):
            self.issuer.issue(
                binding=denied_binding,
                request=self.request,
                target=self.target,
                gate=denied_gate,
            )
        self.assertEqual(provider.calls, 0)
        self.assertTrue(serial_bridge.writes_available)

    def test_missing_denied_or_boolean_host_approval_burns_authorization(self) -> None:
        provider = FakeProvider()
        callbacks = (
            lambda challenge, request, target: None,
            lambda challenge, request, target: False,
            lambda challenge, request, target: True,
            lambda challenge, request, target: {
                "approved": True,
                "request": request,
                "target": target,
            },
        )
        for index, callback in enumerate(callbacks, start=1):
            with self.subTest(callback=repr(callback)):
                binding = bridge_contract.WorkflowWriteBinding(
                    bundle_sha256=self.binding.bundle_sha256,
                    action_id=self.binding.action_id,
                    execution_id=self.binding.execution_id,
                    effect_id=self.binding.effect_id,
                    gate_sha256=self.binding.gate_sha256,
                    nonce=digest(f"{index:x}"),
                )
                authorization = self.authorization(
                    binding=binding
                )
                serial_bridge = self.bridge(provider, callback)
                with self.assertRaisesRegex(
                    bridge_contract.ExternalWriteError,
                    "approval is absent or denied",
                ):
                    self.invoke(
                        serial_bridge,
                        authorization,
                        binding=binding,
                    )
        self.assertEqual(provider.calls, 0)

    def test_host_approval_must_bind_current_request_and_target(self) -> None:
        provider = FakeProvider()

        def wrong_request(
            challenge: object, request: object, target: object
        ) -> object:
            return challenge.approve(
                request={"operation": "different"}, target=target
            )

        def wrong_target(
            challenge: object, request: object, target: object
        ) -> object:
            return challenge.approve(
                request=request, target={"resource": "other"}
            )

        for index, callback in enumerate(
            (wrong_request, wrong_target), start=1
        ):
            binding = bridge_contract.WorkflowWriteBinding(
                bundle_sha256=self.binding.bundle_sha256,
                action_id=self.binding.action_id,
                execution_id=self.binding.execution_id,
                effect_id=self.binding.effect_id,
                gate_sha256=self.binding.gate_sha256,
                nonce=(f"{index:x}" * 64)[:64],
            )
            authorization = self.authorization(binding=binding)
            with self.assertRaisesRegex(
                bridge_contract.ExternalWriteError,
                "does not bind the current exact request",
            ):
                self.invoke(
                    self.bridge(provider, callback),
                    authorization,
                    binding=binding,
                )
        self.assertEqual(provider.calls, 0)

    def test_wrong_request_target_or_workflow_binding_burns_handle(self) -> None:
        provider = FakeProvider()
        serial_bridge = self.bridge(provider)
        cases = (
            {
                "request": {
                    **self.request,
                    "operation": "delete",
                }
            },
            {
                "target": {
                    **self.target,
                    "resource": "other",
                }
            },
            {
                "binding": bridge_contract.WorkflowWriteBinding(
                    bundle_sha256=self.binding.bundle_sha256,
                    action_id=self.binding.action_id,
                    execution_id=self.binding.execution_id,
                    effect_id="provider-write-2",
                    gate_sha256=self.binding.gate_sha256,
                    nonce=self.binding.nonce,
                )
            },
        )
        for index, changed in enumerate(cases, start=1):
            binding = bridge_contract.WorkflowWriteBinding(
                bundle_sha256=self.binding.bundle_sha256,
                action_id=self.binding.action_id,
                execution_id=self.binding.execution_id,
                effect_id=self.binding.effect_id,
                gate_sha256=self.binding.gate_sha256,
                nonce=(f"{index + 4:x}" * 64)[:64],
            )
            authorization = self.authorization(binding=binding)
            arguments = {"binding": binding, **changed}
            with self.assertRaises(bridge_contract.ExternalWriteError):
                self.invoke(
                    serial_bridge, authorization, **arguments
                )
            with self.assertRaisesRegex(
                bridge_contract.ExternalWriteError, "consumed"
            ):
                self.invoke(
                    serial_bridge,
                    authorization,
                    binding=binding,
                )
        self.assertEqual(provider.calls, 0)

    def test_expired_and_replayed_authorizations_never_invoke(self) -> None:
        provider = FakeProvider()
        serial_bridge = self.bridge(provider)
        authorization = self.authorization(ttl_seconds=1)
        self.clock.advance(1)
        with self.assertRaisesRegex(
            bridge_contract.ExternalWriteError, "expired"
        ):
            self.invoke(serial_bridge, authorization)
        with self.assertRaisesRegex(
            bridge_contract.ExternalWriteError, "consumed"
        ):
            self.invoke(serial_bridge, authorization)
        self.assertEqual(provider.calls, 0)

    def test_caller_booleans_model_fields_and_receipts_are_never_approval(self) -> None:
        provider = FakeProvider()
        serial_bridge = self.bridge(provider)
        claims = (
            {"approved": True},
            {"host_approved": True},
            {"model_approval": "approved"},
            {"worker_host_approval": {"approved": True}},
            {"approval_receipt": {"schema": "old-receipt/v1"}},
        )
        for index, claim in enumerate(claims, start=1):
            binding = bridge_contract.WorkflowWriteBinding(
                bundle_sha256=self.binding.bundle_sha256,
                action_id=self.binding.action_id,
                execution_id=self.binding.execution_id,
                effect_id=self.binding.effect_id,
                gate_sha256=self.binding.gate_sha256,
                nonce=(f"{index + 8:x}" * 64)[:64],
            )
            authorization = self.authorization(binding=binding)
            with self.assertRaisesRegex(
                bridge_contract.ExternalWriteError,
                "cannot authorize",
            ):
                self.invoke(
                    serial_bridge,
                    authorization,
                    binding=binding,
                    **claim,
                )
        self.assertEqual(provider.calls, 0)

    def test_unavailable_bridge_keeps_reads_but_never_writes(self) -> None:
        provider = FakeProvider()
        unavailable = bridge_contract.HostOwnedExternalWriteBridge(
            issuer=self.issuer,
            approval_callback=None,
            provider=provider,
        )
        authorization = self.authorization()
        with self.assertRaises(
            bridge_contract.ExternalWriteUnavailable
        ):
            self.invoke(unavailable, authorization)
        self.assertEqual(provider.calls, 0)

        access = bridge_contract.ExternalProviderAccess(
            read_provider=lambda request: {"echo": request}
        )
        self.assertTrue(access.reads_available)
        self.assertFalse(access.writes_available)
        self.assertEqual(
            access.read({"query": "safe"}),
            {"echo": {"query": "safe"}},
        )
        with self.assertRaises(
            bridge_contract.ExternalWriteUnavailable
        ):
            access.write(
                authorization=authorization,
                binding=self.binding,
                request=self.request,
                target=self.target,
            )
        self.assertEqual(provider.calls, 0)

    def test_provider_failure_consumes_authorization(self) -> None:
        provider = FakeProvider(fail=True)
        serial_bridge = self.bridge(provider)
        authorization = self.authorization()
        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            self.invoke(serial_bridge, authorization)
        self.assertEqual(provider.calls, 1)
        with self.assertRaisesRegex(
            bridge_contract.ExternalWriteError, "consumed"
        ):
            self.invoke(serial_bridge, authorization)
        self.assertEqual(provider.calls, 1)

    def test_one_handle_race_has_exactly_one_provider_invocation(self) -> None:
        provider = FakeProvider()
        serial_bridge = self.bridge(provider)
        authorization = self.authorization()
        start = threading.Barrier(3)
        outcomes: list[str] = []
        lock = threading.Lock()

        def run() -> None:
            start.wait()
            try:
                self.invoke(serial_bridge, authorization)
                value = "success"
            except bridge_contract.ExternalWriteError:
                value = "rejected"
            with lock:
                outcomes.append(value)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sorted(outcomes), ["rejected", "success"])
        self.assertEqual(provider.calls, 1)

    def test_authorization_and_host_objects_hide_raw_secrets(self) -> None:
        captured: dict[str, object] = {}

        def host(
            challenge: object, request: object, target: object
        ) -> object:
            grant = challenge.approve(
                request=request, target=target
            )
            captured["challenge"] = challenge
            captured["grant"] = grant
            return grant

        provider = FakeProvider()
        authorization = self.authorization()
        self.invoke(self.bridge(provider, host), authorization)
        opaque_values = (
            self.issuer,
            authorization,
            captured["challenge"],
            captured["grant"],
        )
        for value in opaque_values:
            with self.subTest(value=type(value).__name__):
                self.assertFalse(hasattr(value, "__dict__"))
                self.assertNotIn(self.binding.nonce, repr(value))
                self.assertNotIn(self.request["operation"], repr(value))
                with self.assertRaises(TypeError):
                    copy.copy(value)
                with self.assertRaises(TypeError):
                    pickle.dumps(value)


if __name__ == "__main__":
    unittest.main()
