"""The integrated Web UI must not fork the sealed current product identity."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
APP_JS = SRC / "dev_flow_orchestrator" / "web_assets" / "app.js"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.product import (
    PLUGIN_DATA_NAMESPACE,
    PRODUCT_IDENTITY,
    RELEASE_VERSION,
    MODEL_VERSION,
    product_document,
)


def javascript_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{",
        source,
    )
    if match is None:
        raise AssertionError(f"JavaScript function not found: {name}")
    brace_start = match.end() - 1
    depth = 0
    for index in range(brace_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"JavaScript function is incomplete: {name}")


class WebUiProductIdentityTests(unittest.TestCase):
    def test_current_product_identity_remains_exactly_pinned(self) -> None:
        self.assertEqual(MODEL_VERSION, "0.4.0")
        self.assertEqual(RELEASE_VERSION, "0.6.0")
        self.assertEqual(PLUGIN_DATA_NAMESPACE, "0.4.0")
        self.assertEqual(
            PRODUCT_IDENTITY,
            "0cafdc0d0146a705146f7e9e723924f865b324b064c0974bb5a3b47b5b932d88",
        )

    def test_product_document_has_no_web_ui_protocol_authority(self) -> None:
        serialized = json.dumps(product_document(), sort_keys=True).lower()
        for forbidden in (
            "web_ui_version",
            "webui_version",
            "web-ui-version",
            "dev-flow-web-ui",
            "/api/" + "v" + "1",
            "web_ui_namespace",
            "web_ui_schema",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

    def test_detail_requests_are_latest_selection_wins(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        api_source = javascript_function(source, "api")
        current_source = javascript_function(source, "isCurrentDetailRequest")
        abort_source = javascript_function(source, "isAbortError")
        load_source = javascript_function(source, "loadDetail")
        timeline_source = javascript_function(source, "renderTimeline")
        tasks_source = javascript_function(source, "renderTasks")

        self.assertIn("async function api(path, {signal} = {})", api_source)
        self.assertRegex(api_source, r"fetch\(path,\s*\{[\s\S]*\bsignal\b")
        self.assertIn(
            "return generation === detailRequestGeneration && taskId === selectedTask;",
            current_source,
        )
        self.assertIn('return error && error.name === "AbortError";', abort_source)

        ordered_contract = (
            "selectedTask = taskId;",
            "const requestGeneration = ++detailRequestGeneration;",
            "detailRequestController.abort();",
            "const controller = new AbortController();",
            "detailRequestController = controller;",
            "{signal: controller.signal}",
            "if (!isCurrentDetailRequest(requestGeneration, taskId)) return;",
            "renderDetail(response);",
        )
        cursor = 0
        for statement in ordered_contract:
            with self.subTest(statement=statement):
                position = load_source.find(statement, cursor)
                self.assertGreaterEqual(position, 0)
                cursor = position + len(statement)

        self.assertIn(
            "if (isAbortError(error) || !isCurrentDetailRequest(requestGeneration, taskId)) return;",
            load_source,
        )
        self.assertRegex(
            load_source,
            r"if \(requestGeneration === detailRequestGeneration\) \{\s*"
            r"detailRequestController = null;\s*liveButton\.disabled = !selectedTask;",
        )
        self.assertEqual(source.count('api("/api/tasks/"'), 1)
        self.assertEqual(source.count("renderDetail(response);"), 1)
        self.assertEqual(timeline_source.count("list.append(item);"), 1)
        self.assertIn("loadDetail(taskId, false", timeline_source)
        self.assertIn("loadDetail(task.task_id, false)", tasks_source)
        self.assertIn(
            'liveButton.addEventListener("click", () => { if (selectedTask) '
            "loadDetail(selectedTask, true); });",
            source,
        )

    def test_web_ui_uses_neither_background_polling_nor_persistent_storage(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        for forbidden in (
            "setInterval(",
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "caches.open(",
            "navigator.storage",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_recovery_projection_renders_only_allowlisted_summary_fields(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        rendering_source = "\n".join(
            javascript_function(source, name)
            for name in (
                "renderWhyNext",
                "renderRecoveryAssurance",
                "renderRecoveryEvidence",
                "renderRecovery",
                "renderDetail",
            )
        )

        for required in (
            "whyNext.outcome",
            "whyNext.readiness",
            "whyNext.declared_action",
            "blocker.reason",
            "blocker.evidence",
            "blocker.recovery_choices",
            "recovery.retry",
            "recovery.assurance",
            "assurance.budget",
            "recovery.outstanding_assurance",
            "recovery.exhausted_assurance",
            "recovery.freshness",
            "recovery.review",
            "recovery.dossier",
            "recovery.repositories",
            "recovery.recent_timeline",
            '"Retry and assurance"',
            '"Outstanding assurance"',
            '"Exhausted assurance"',
            '"Evidence status"',
            '"Repository identities"',
            '"Recent timeline"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, rendering_source)

        for forbidden in (
            "recovery.binding",
            "recovery.inputs",
            "recovery.original_contract",
            "recovery.records",
            "recovery.raw",
            "blocker.details",
            "blocker.message",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendering_source)


if __name__ == "__main__":
    unittest.main()
