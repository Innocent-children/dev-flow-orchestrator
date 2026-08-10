from __future__ import annotations

import json
import unittest

from jsonschema import Draft202012Validator

from dev_flow_orchestrator.engine import validate_action_payload
from dev_flow_orchestrator.mcp.guidance import guidance_for_projection
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.payload_contract import effective_payload_contract
from dev_flow_orchestrator.product import DRIVER_RESULT_SCHEMA, WORKFLOW_IDS
from dev_flow_orchestrator.workflows import load_definition


def _value(field: str, field_type: str) -> object:
    if field == "driver_result":
        return {"schema": DRIVER_RESULT_SCHEMA}
    if field_type == "string":
        return "value"
    if field_type == "boolean":
        return False
    if field_type == "integer":
        return 0
    if field_type == "sha256":
        return "a" * 64
    return {}


class EffectivePayloadContractTests(unittest.TestCase):
    def test_every_official_node_shares_one_closed_payload_field_set(self) -> None:
        nodes = []
        for workflow_id in WORKFLOW_IDS:
            definition = load_definition(workflow_id)
            for node_id, node in definition.nodes.items():
                if node.action_id:
                    nodes.append((workflow_id, node_id, node))

        self.assertTrue(nodes)
        for workflow_id, node_id, node in nodes:
            with self.subTest(workflow=workflow_id, node=node_id):
                effective = effective_payload_contract(
                    node,
                    repository_ids=("repository-a", "repository-b"),
                    criterion_ids=("criterion-a", "criterion-b"),
                )
                schema = effective.schema_dict()
                Draft202012Validator.check_schema(schema)
                fields = set(effective.field_types)
                self.assertEqual(set(schema["properties"]), fields)
                self.assertEqual(set(schema["required"]), fields)
                self.assertEqual(len(schema["required"]), len(fields))
                self.assertIs(schema["additionalProperties"], False)

                payload = {
                    field: _value(field, field_type)
                    for field, field_type in effective.field_types.items()
                }
                accepted = validate_action_payload(node, payload)
                self.assertEqual(set(accepted), fields)
                for field in effective.required_fields:
                    incomplete = dict(payload)
                    del incomplete[field]
                    with self.assertRaises(DevFlowError) as missing:
                        validate_action_payload(node, incomplete)
                    self.assertEqual(missing.exception.code, "NODE_OUTPUT_INVALID")
                    self.assertEqual(missing.exception.details["missing_fields"], [field])
                with self.assertRaises(DevFlowError) as unknown:
                    validate_action_payload(node, {**payload, "unknown_field": True})
                self.assertEqual(unknown.exception.code, "NODE_OUTPUT_INVALID")
                self.assertEqual(
                    unknown.exception.details["unknown_fields"],
                    ["unknown_field"],
                )

                action = node.as_dict()
                action["payload"] = schema
                guidance = guidance_for_projection({"action": action, "done": False})
                rendered = json.dumps(guidance, sort_keys=True)
                for candidate in ("impact_manifest", "ownership_claims"):
                    if candidate in rendered:
                        self.assertIn(candidate, fields)

    def test_legacy_replay_compatibility_is_explicit_and_not_live(self) -> None:
        impact = load_definition("lite").nodes["impact"]
        historical_payload = {
            field: _value(field, field_type)
            for field, field_type in impact.payload_types.items()
        }
        with self.assertRaises(DevFlowError) as strict:
            validate_action_payload(impact, historical_payload)
        self.assertEqual(strict.exception.details["missing_fields"], ["impact_manifest"])
        replayed = validate_action_payload(
            impact,
            historical_payload,
            legacy_compatibility=True,
        )
        self.assertEqual(dict(replayed), historical_payload)


if __name__ == "__main__":
    unittest.main()
