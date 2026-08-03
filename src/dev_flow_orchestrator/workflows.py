"""Current workflow definition loading: official assets and pinned custom paths.

Selection tokens are either a built-in id (the stem of a file under the
packaged ``workflows/`` directory) or an absolute path to a workflow
YAML/JSON document. The loaded definition is validated and pinned by its
identity digest; a task whose workflow file changed or moved fails fast
with a clear error instead of silently running a different flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from . import yaml_subset
from .model import DevFlowError, TaskState
from .workflow import WorkflowDefinition, validate_definition_document
from .product import WORKFLOW_IDS


BUILTIN_DIR = Path(__file__).resolve().parents[2] / "workflows"


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def list_builtin_ids() -> tuple:
    """Sorted stems of the packaged workflow files."""
    if not BUILTIN_DIR.is_dir():
        return ()
    return tuple(
        sorted(
            path.stem
            for path in BUILTIN_DIR.iterdir()
            if path.is_file() and path.suffix in (".yaml", ".yml", ".json")
        )
    )


def _load_document(path: Path, source: str) -> Mapping:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _error(
            "WORKFLOW_NOT_FOUND",
            "workflow file could not be read: {}".format(exc),
            path=source,
        ) from exc
    try:
        parsed = yaml_subset.load_or_json(text)
    except ValueError as exc:
        raise _error(
            "WORKFLOW_INVALID",
            "workflow file is not valid YAML/JSON: {}".format(exc),
            path=source,
        ) from exc
    if not isinstance(parsed, Mapping):
        raise _error(
            "WORKFLOW_INVALID",
            "workflow document must be a mapping",
            path=source,
        )
    return parsed


def load_definition(selector: str) -> WorkflowDefinition:
    """Load and validate a workflow by built-in id or absolute path."""
    if not isinstance(selector, str) or not selector:
        raise _error("WORKFLOW_NOT_FOUND", "workflow selector is required")
    if selector in WORKFLOW_IDS:
        path = BUILTIN_DIR / "{}.yaml".format(selector)
        if not path.is_file():
            raise _error(
                "WORKFLOW_NOT_FOUND",
                "built-in workflow {!r} has no packaged file".format(selector),
            )
        document = _load_document(path, str(path))
        declared_id = document.get("id")
        if declared_id != selector:
            raise _error(
                "WORKFLOW_INVALID",
                "built-in workflow {!r} must declare id: {!r}".format(
                    selector, selector
                ),
                path=str(path),
            )
        return validate_definition_document(
            document,
            workflow_id=selector,
            source=str(path),
        )
    path = Path(selector).expanduser()
    if not path.is_absolute():
        raise _error(
            "WORKFLOW_NOT_FOUND",
            "custom workflows must be selected by absolute path",
            selector=selector,
        )
    if not path.is_file():
        raise _error(
            "WORKFLOW_NOT_FOUND",
            "workflow file does not exist",
            path=str(path),
        )
    document = _load_document(path, str(path))
    return validate_definition_document(
        document,
        workflow_id=str(path),
        source=str(path),
    )


def task_definition(state: TaskState) -> WorkflowDefinition:
    """Load the definition pinned by a task and verify its identity."""
    definition = load_definition(state.workflow_id)
    if (
        definition.version != state.workflow_version
        or definition.schema != state.workflow_schema
    ):
        raise _error(
            "WORKFLOW_IDENTITY_MISMATCH",
            "task workflow language is not installed",
            task_id=state.task_id,
            expected={
                "version": state.workflow_version,
                "schema": state.workflow_schema,
            },
            loaded={
                "version": definition.version,
                "schema": definition.schema,
            },
        )
    if definition.identity != state.workflow_identity:
        raise _error(
            "WORKFLOW_IDENTITY_MISMATCH",
            "task workflow identity drifted: the workflow file changed since "
            "the task started",
            task_id=state.task_id,
        )
    return definition
