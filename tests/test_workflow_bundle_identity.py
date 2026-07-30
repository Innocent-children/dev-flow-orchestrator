from __future__ import annotations

import json
import struct
import unittest

from scripts import workflow_bundle_identity as identity


class WorkflowBundleIdentityTests(unittest.TestCase):
    def _vector_files(self) -> list[identity.BundleFile]:
        return [
            identity.BundleFile("blob.bin", "B", bytes.fromhex("00ff0a")),
            identity.BundleFile(
                "graph.json",
                "J",
                b'{"workflow_version":1,\r\n "workflow_id":"vector"}\r\n',
            ),
            identity.BundleFile("playbook.md", "T", b"Step one.\r\n"),
        ]

    def _vector_handler(self, result: bytes = b"True") -> identity.HandlerImplementation:
        return identity.HandlerImplementation(
            handler_id="guard.vector/v1",
            contract_id="dev-flow-guard/v1",
            files=(
                identity.BundleFile(
                    "scripts/vector_guard.py",
                    "T",
                    b"def guard(ctx):\r\n    return " + result + b"\r\n",
                ),
            ),
        )

    def test_normative_minimal_vector_matches_exact_digests(self) -> None:
        files = self._vector_files()
        handler = self._vector_handler()

        self.assertEqual(
            identity.canonical_binary_payload(files[0].source),
            bytes.fromhex("00ff0a"),
        )
        self.assertEqual(
            identity.canonical_json_payload(files[1].source),
            b'{"workflow_id":"vector","workflow_version":1}',
        )
        self.assertEqual(
            identity.canonical_text_payload(files[2].source),
            b"Step one.\n",
        )
        self.assertEqual(
            identity.graph_sha256(files[1].source),
            "d2933a444dbd4bc91552fabe14840fbafdd663e25b4eccef9855d45b6cedf52c",
        )
        self.assertEqual(
            identity.handler_implementation_sha256(
                handler.handler_id,
                handler.contract_id,
                handler.files,
            ),
            "2a725499ab81891164ea25f08b8fbb9cfb89c316c051b6c7c91c5370628f8d80",
        )
        self.assertEqual(
            identity.bundle_sha256(files, [handler]),
            "e7330dd1bd61cba66e19cd4c687be98d3a484a42216ddb411196e292f5b6fb2a",
        )

        combined = identity.compute_workflow_bundle_identity(
            files[1].source,
            files,
            [handler],
        )
        self.assertEqual(
            combined.graph_sha256,
            "d2933a444dbd4bc91552fabe14840fbafdd663e25b4eccef9855d45b6cedf52c",
        )
        self.assertEqual(
            combined.handler_digests(),
            {
                "guard.vector/v1": (
                    "2a725499ab81891164ea25f08b8fbb9cfb89c316c051b6c7c91c5370628f8d80"
                )
            },
        )
        self.assertEqual(
            combined.bundle_sha256,
            "e7330dd1bd61cba66e19cd4c687be98d3a484a42216ddb411196e292f5b6fb2a",
        )

    def test_normative_newline_variants_keep_the_declared_digests(self) -> None:
        files = self._vector_files()
        lf_files = [
            files[0],
            files[1],
            identity.BundleFile("playbook.md", "T", b"Step one.\n"),
        ]
        lf_handler = identity.HandlerImplementation(
            "guard.vector/v1",
            "dev-flow-guard/v1",
            [
                identity.BundleFile(
                    "scripts/vector_guard.py",
                    "T",
                    b"def guard(ctx):\n    return True\n",
                )
            ],
        )
        self.assertEqual(
            identity.handler_implementation_sha256(
                lf_handler.handler_id,
                lf_handler.contract_id,
                lf_handler.files,
            ),
            "2a725499ab81891164ea25f08b8fbb9cfb89c316c051b6c7c91c5370628f8d80",
        )
        self.assertEqual(
            identity.bundle_sha256(lf_files, [lf_handler]),
            "e7330dd1bd61cba66e19cd4c687be98d3a484a42216ddb411196e292f5b6fb2a",
        )

    def test_normative_handler_only_drift_changes_only_handler_and_bundle(self) -> None:
        files = self._vector_files()
        original = self._vector_handler()
        drifted = self._vector_handler(b"False")

        self.assertEqual(
            identity.graph_sha256(files[1].source),
            "d2933a444dbd4bc91552fabe14840fbafdd663e25b4eccef9855d45b6cedf52c",
        )
        self.assertEqual(
            identity.handler_implementation_sha256(
                drifted.handler_id,
                drifted.contract_id,
                drifted.files,
            ),
            "9fb28a7f17498bfe38925dad0b97efa0345c667d801cfe7733da559346a7442c",
        )
        self.assertEqual(
            identity.bundle_sha256(files, [drifted]),
            "d3a9189eb355c773d215e80901d8424a88c3ade5678cdb5480d0d20b40e23c87",
        )
        self.assertNotEqual(
            identity.bundle_sha256(files, [original]),
            identity.bundle_sha256(files, [drifted]),
        )

    def test_u64be_and_domains_are_exact(self) -> None:
        self.assertEqual(identity.u64be(0), b"\x00" * 8)
        self.assertEqual(identity.u64be(2**64 - 1), b"\xff" * 8)
        self.assertEqual(identity.u64be(258), struct.pack(">Q", 258))
        self.assertTrue(
            identity.graph_preimage(b"{}").startswith(b"dev-flow-graph-v1\x00")
        )
        with self.assertRaisesRegex(
            identity.WorkflowBundleIdentityError,
            "does not fit U64BE",
        ) as caught:
            identity.u64be(2**64)
        self.assertEqual(caught.exception.code, "BUNDLE_IDENTITY_U64_INVALID")

    def test_json_whitespace_and_key_order_are_insignificant(self) -> None:
        first = b'{"z":[3,2,1],"a":{"enabled":true,"value":null}}'
        second = (
            b'{\r\n "a": { "value": null, "enabled": true },'
            b'\r\n "z": [3, 2, 1]\r\n}\r\n'
        )
        expected = b'{"a":{"enabled":true,"value":null},"z":[3,2,1]}'
        self.assertEqual(identity.canonical_json_payload(first), expected)
        self.assertEqual(identity.canonical_json_payload(second), expected)
        self.assertEqual(identity.graph_sha256(first), identity.graph_sha256(second))

    def test_json_rejects_every_ambiguous_semantic_form(self) -> None:
        invalid = (
            (b'{"a":1,"a":2}', "BUNDLE_JSON_DUPLICATE_KEY"),
            (b'{"a":1.0}', "BUNDLE_JSON_FLOAT_FORBIDDEN"),
            (b'{"a":1e0}', "BUNDLE_JSON_FLOAT_FORBIDDEN"),
            (b'{"a":9223372036854775808}', "BUNDLE_JSON_INTEGER_OUT_OF_RANGE"),
            (b'{"a":-9223372036854775809}', "BUNDLE_JSON_INTEGER_OUT_OF_RANGE"),
            (
                '{"a":"e\u0301"}'.encode("utf-8"),
                "BUNDLE_JSON_STRING_NOT_NFC",
            ),
            (
                '{"e\u0301":"value"}'.encode("utf-8"),
                "BUNDLE_JSON_KEY_NOT_NFC",
            ),
            (b"\xef\xbb\xbf{}", "BUNDLE_IDENTITY_BOM_FORBIDDEN"),
            (b'{"a":NaN}', "BUNDLE_JSON_NONFINITE_FORBIDDEN"),
            (b'{"a":Infinity}', "BUNDLE_JSON_NONFINITE_FORBIDDEN"),
            (b'{"a":-Infinity}', "BUNDLE_JSON_NONFINITE_FORBIDDEN"),
            (b'{"a":"\\ud800"}', "BUNDLE_JSON_UNICODE_INVALID"),
            (b'{"a":\xff}', "BUNDLE_IDENTITY_UTF8_INVALID"),
        )
        for payload, code in invalid:
            with self.subTest(payload=payload, code=code):
                with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
                    identity.canonical_json_payload(payload)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.as_dict()["code"], code)

    def test_json_accepts_signed_int64_boundaries_only(self) -> None:
        payload = b'{"max":9223372036854775807,"min":-9223372036854775808}'
        self.assertEqual(
            identity.canonical_json_payload(payload),
            payload,
        )
        very_large = b'{"value":' + (b"9" * 5000) + b"}"
        with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
            identity.canonical_json_payload(very_large)
        self.assertEqual(
            caught.exception.code,
            "BUNDLE_JSON_INTEGER_OUT_OF_RANGE",
        )

    def test_text_newline_binary_and_nfc_contracts(self) -> None:
        self.assertEqual(
            identity.canonical_text_payload(b"a\r\nb\rc\n"),
            b"a\nb\nc\n",
        )
        binary = bytes(range(256))
        self.assertIs(identity.canonical_binary_payload(binary), binary)
        for payload, code in (
            (b"\xef\xbb\xbftext", "BUNDLE_IDENTITY_BOM_FORBIDDEN"),
            ("e\u0301".encode("utf-8"), "BUNDLE_TEXT_NOT_NFC"),
            (b"\xff", "BUNDLE_IDENTITY_UTF8_INVALID"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
                    identity.canonical_text_payload(payload)
                self.assertEqual(caught.exception.code, code)

    def test_paths_reject_nonportable_spelling_globs_and_nfc_violations(self) -> None:
        invalid = (
            "",
            "/absolute",
            "//server/share",
            "C:/drive",
            "scripts\\guard.py",
            "./graph.json",
            "nodes/../graph.json",
            "nodes//graph.json",
            "nodes/*.json",
            "nodes/\x00graph.json",
            "nodes/e\u0301.json",
        )
        for path in invalid:
            with self.subTest(path=path):
                with self.assertRaises(identity.WorkflowBundleIdentityError):
                    identity.validate_bundle_path(path)

        encoded, portable = identity.validate_bundle_path(
            "playbooks/\u00e9tape.md"
        )
        self.assertEqual(encoded, "playbooks/\u00e9tape.md".encode("utf-8"))
        self.assertEqual(portable, "playbooks/\u00e9tape.md".casefold())

    def test_manifest_paths_are_unique_under_nfc_plus_casefold(self) -> None:
        for first, second in (
            ("Graph.json", "graph.JSON"),
            ("Stra\u00dfe.md", "STRASSE.md"),
        ):
            with self.subTest(first=first, second=second):
                with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
                    identity.canonical_manifest_files(
                        [
                            identity.BundleFile(first, "T", b"a"),
                            identity.BundleFile(second, "T", b"b"),
                        ]
                    )
                self.assertEqual(caught.exception.code, "BUNDLE_PATH_COLLISION")

        with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
            identity.canonical_manifest_files(
                [
                    identity.BundleFile("graph.json", "J", b"{}"),
                    identity.BundleFile("graph.json", "J", b"{}"),
                ]
            )
        self.assertEqual(caught.exception.code, "BUNDLE_PATH_DUPLICATE")

    def test_manifest_and_handler_order_do_not_affect_identity(self) -> None:
        files = self._vector_files()
        first_handler = self._vector_handler()
        second_handler = identity.HandlerImplementation(
            "action.vector/v1",
            "dev-flow-action/v1",
            [identity.BundleFile("scripts/action.py", "T", b"VALUE = 1\r\n")],
        )
        first = identity.bundle_sha256(
            files,
            [first_handler, second_handler],
        )
        second = identity.bundle_sha256(
            reversed(files),
            [second_handler, first_handler],
        )
        self.assertEqual(first, second)

    def test_handler_file_set_is_exact_nonempty_and_canonical(self) -> None:
        with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
            identity.handler_implementation_sha256(
                "guard.empty/v1",
                "dev-flow-guard/v1",
                [],
            )
        self.assertEqual(caught.exception.code, "BUNDLE_HANDLER_FILE_SET_EMPTY")

        with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
            identity.handler_implementation_sha256(
                "guard.duplicate/v1",
                "dev-flow-guard/v1",
                [
                    identity.BundleFile("scripts/guard.py", "T", b"a"),
                    identity.BundleFile("scripts/guard.py", "T", b"b"),
                ],
            )
        self.assertEqual(caught.exception.code, "BUNDLE_PATH_DUPLICATE")

    def test_unsupported_kind_and_nonbyte_sources_fail_structurally(self) -> None:
        for entry, code in (
            (
                identity.BundleFile("graph.json", "j", b"{}"),
                "BUNDLE_CONTENT_KIND_UNSUPPORTED",
            ),
            (
                identity.BundleFile("graph.json", "J", "{}"),  # type: ignore[arg-type]
                "BUNDLE_IDENTITY_SOURCE_INVALID",
            ),
        ):
            with self.subTest(code=code):
                with self.assertRaises(identity.WorkflowBundleIdentityError) as caught:
                    identity.canonical_manifest_files([entry])
                self.assertEqual(caught.exception.code, code)

    def test_required_json_encoder_matches_the_standard_library_call(self) -> None:
        source = '{"é":"café","items":[2,1],"ok":true}'.encode("utf-8")
        expected = json.dumps(
            json.loads(source.decode("utf-8")),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(identity.canonical_json_payload(source), expected)


if __name__ == "__main__":
    unittest.main()
