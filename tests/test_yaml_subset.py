"""Parser coverage for the YAML subset used by workflow definitions."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator import yaml_subset
from dev_flow_orchestrator.product import MODEL_VERSION, WORKFLOW_SCHEMA


class YamlSubsetParserTest(unittest.TestCase):
    def test_nested_block_mapping(self) -> None:
        document = (
            f"schema: {WORKFLOW_SCHEMA}\n"
            "id: lite\n"
            f"version: {MODEL_VERSION}\n"
            "entry: preflight\n"
            "nodes:\n"
            "  implement:\n"
            "    action_id: implementation.record\n"
            "    handler: artifact.record\n"
            "    target: {node: verify, status: VERIFYING}\n"
            "    payload:\n"
            "      summary: string\n"
        )
        value = yaml_subset.load(document)
        self.assertEqual(value["schema"], WORKFLOW_SCHEMA)
        self.assertEqual(value["id"], "lite")
        self.assertEqual(value["version"], MODEL_VERSION)
        self.assertEqual(value["entry"], "preflight")
        implement = value["nodes"]["implement"]
        self.assertEqual(implement["action_id"], "implementation.record")
        self.assertEqual(implement["target"], {"node": "verify", "status": "VERIFYING"})
        self.assertEqual(implement["payload"], {"summary": "string"})

    def test_block_sequence_of_mapping_items(self) -> None:
        document = (
            "writes:\n"
            "  - /current_node\n"
            "  - /revision\n"
            "  - kind: evidence\n"
            "    count: 2\n"
        )
        value = yaml_subset.load(document)
        self.assertEqual(
            value["writes"],
            ["/current_node", "/revision", {"kind": "evidence", "count": 2}],
        )

    def test_flow_collections(self) -> None:
        document = (
            "target: {node: done, status: DONE}\n"
            "list: [a, b, c]\n"
            "empty_map: {}\n"
            "empty_list: []\n"
        )
        value = yaml_subset.load(document)
        self.assertEqual(value["target"], {"node": "done", "status": "DONE"})
        self.assertEqual(value["list"], ["a", "b", "c"])
        self.assertEqual(value["empty_map"], {})
        self.assertEqual(value["empty_list"], [])

    def test_nested_flow_collection(self) -> None:
        value = yaml_subset.load("driver: {tool: openspec, tags: [a, b]}\n")
        self.assertEqual(value["driver"], {"tool": "openspec", "tags": ["a", "b"]})

    def test_comments(self) -> None:
        document = (
            "# full-line comment\n"
            "id: lite  # trailing comment\n"
            "nodes:\n"
            "  done: {terminal: true}  # sink\n"
        )
        value = yaml_subset.load(document)
        self.assertEqual(value["id"], "lite")
        self.assertEqual(value["nodes"]["done"], {"terminal": True})

    def test_hash_without_preceding_space_is_plain_scalar_content(self) -> None:
        value = yaml_subset.load(
            "action: task.preflight#current\n"
            "description: fixes issue#123 # real comment\n"
            "url: https://example.test/run#phase\n"
        )
        self.assertEqual(value["action"], "task.preflight#current")
        self.assertEqual(value["description"], "fixes issue#123")
        self.assertEqual(value["url"], "https://example.test/run#phase")

    def test_quoted_strings(self) -> None:
        document = (
            'description: "a \\"quoted\\" value"\n'
            "path: '/tmp/x'\n"
            "escaped: 'it''s'\n"
        )
        value = yaml_subset.load(document)
        self.assertEqual(value["description"], 'a "quoted" value')
        self.assertEqual(value["path"], "/tmp/x")
        self.assertEqual(value["escaped"], "it's")

    def test_boolean_and_integer_scalars(self) -> None:
        value = yaml_subset.load("a: true\nb: false\nc: null\nd: -3\n")
        self.assertIs(value["a"], True)
        self.assertIs(value["b"], False)
        self.assertIsNone(value["c"])
        self.assertEqual(value["d"], -3)

    def test_yes_and_no_stay_strings(self) -> None:
        value = yaml_subset.load("a: yes\nb: on\n")
        self.assertEqual(value["a"], "yes")
        self.assertEqual(value["b"], "on")

    def test_json_documents_parse_via_fallback(self) -> None:
        document = (
            f'{{"schema": "{WORKFLOW_SCHEMA}", "id": "lite", '
            '"target": {"node": "done", "status": "DONE"}}'
        )
        value = yaml_subset.load_or_json(document)
        self.assertEqual(value["id"], "lite")
        self.assertEqual(value["target"], {"node": "done", "status": "DONE"})

    def test_rejects_duplicate_json_keys_without_yaml_fallback(self) -> None:
        for document in (
            '{"id": "a", "id": "b"}',
            '{"node": {"status": "A", "status": "B"}}',
        ):
            with self.assertRaises(ValueError) as context:
                yaml_subset.load_or_json(document)
            self.assertIn("duplicate JSON key", str(context.exception))

    def test_rejects_non_finite_json_numbers(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load_or_json('{"value": NaN}')
        self.assertIn("non-finite JSON number", str(context.exception))

    def test_rejects_tab_indentation(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a: 1\n\tb: 2\n")
        self.assertIn("tab", str(context.exception))
        self.assertIn("line 2", str(context.exception))

    def test_rejects_duplicate_block_keys(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a: 1\na: 2\n")
        self.assertIn("duplicate key", str(context.exception))

    def test_rejects_duplicate_flow_keys(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("target: {node: x, node: y}\n")
        self.assertIn("duplicate key", str(context.exception))

    def test_rejects_anchors_aliases_and_tags(self) -> None:
        for line in ("a: &anchor value\n", "a: *alias\n", "a: !tag value\n"):
            with self.assertRaises(ValueError) as context:
                yaml_subset.load(line)
            self.assertIn("not supported", str(context.exception))

    def test_rejects_block_scalars(self) -> None:
        for scalar in ("|", ">"):
            with self.assertRaises(ValueError) as context:
                yaml_subset.load("a: {}\n".replace("{}", scalar))
            self.assertIn("not supported", str(context.exception))

    def test_rejects_unterminated_quotes(self) -> None:
        for line in ('a: "unterminated\n', "a: 'unterminated\n"):
            with self.assertRaises(ValueError) as context:
                yaml_subset.load(line)
            self.assertIn("unterminated", str(context.exception))

    def test_rejects_unterminated_flow(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a: {b: 1\n")
        self.assertIn("flow", str(context.exception))

    def test_rejects_trailing_content(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a: 1\nb: 2\nextra garbage\n")
        self.assertIn("expected a mapping entry", str(context.exception))

    def test_rejects_unexpected_indentation(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a: 1\n  b: 2\n")
        self.assertIn("indentation", str(context.exception))

    def test_rejects_missing_value(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a: 1\nb:\nc: 3\n")
        self.assertIn("has no value", str(context.exception))

    def test_rejects_empty_document(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("")
        self.assertIn("empty", str(context.exception))

    def test_rejects_nested_sequence_items(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a:\n  - - x\n")
        self.assertIn("nested sequence items", str(context.exception))

    def test_rejects_sequence_inside_mapping_item(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("a:\n  - x: 1\n    - y\n")
        self.assertIn("sequence inside a mapping item", str(context.exception))

    def test_rejects_mapping_then_sequence_block(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load(
                "driver:\n"
                "  tool: openspec\n"
                "  - [ignored, mode, unsafe]\n"
            )
        self.assertIn("mixed mapping and sequence", str(context.exception))
        self.assertIn("line 3", str(context.exception))

    def test_rejects_sequence_then_mapping_block(self) -> None:
        with self.assertRaises(ValueError) as context:
            yaml_subset.load("driver:\n  - openspec\n  mode: unsafe\n")
        self.assertIn("mixed mapping and sequence", str(context.exception))
        self.assertIn("line 3", str(context.exception))


if __name__ == "__main__":
    unittest.main()
