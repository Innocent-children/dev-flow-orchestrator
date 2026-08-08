"""Controller-only application mapping for the stable MCP tools."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import traceback
from typing import Callable, Mapping, Optional

from mcp.types import CallToolResult

from ..controller import Controller
from ..model import DevFlowError
from ..product import (
    MAX_ACTION_PAYLOAD_BYTES,
    MAX_REPOSITORY_COUNT,
    MIN_REPOSITORY_COUNT,
    PLUGIN_DATA_NAMESPACE,
    WORKFLOW_IDS,
)
from .catalog import GUIDANCE_CATALOG_DIGEST, TOOL_CATALOG_DIGEST
from .concurrency import (
    BoundedCoordinator,
    CancellationCheck,
    cooperative_cancellation_requested,
)
from .guidance import guidance_for_projection
from .identity import SUPPORTED_PYTHON, interface_identity
from .logging import emit
from .projection import compact_current_action
from .results import (
    MCPRuntimeFailure,
    cancelled_failure,
    completion_uncertain_failure,
    domain_error,
    internal_error,
    new_request_id,
    runtime_error,
    success,
)
from .schemas import validate_current_action


MAX_COMPACT_ACTION_BYTES = 128 * 1024
MAX_STRUCTURED_RESULT_BYTES = 512 * 1024
MAX_INVENTORY_PAGE_BYTES = 256 * 1024
MAX_TASK_SUMMARY_BYTES = 2 * 1024
MUTATION_TOOLS = frozenset({
    "dev_flow_start_task",
    "dev_flow_apply_action",
    "dev_flow_revise_contract",
    "dev_flow_record_decision",
    "dev_flow_dispose_finding",
    "dev_flow_cancel_task",
})
LIVE_TOOLS = frozenset({"dev_flow_get_next_action"})
FRESH_ACTION_MUTATIONS = MUTATION_TOOLS - {"dev_flow_start_task"}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class MCPApplication:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        try:
            canonical_data_dir = str(Path(data_dir).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            canonical_data_dir = data_dir
        self._redactions = tuple({data_dir, canonical_data_dir})
        self._controller: Optional[Controller] = None
        self.coordinator = BoundedCoordinator()

    @property
    def controller(self) -> Controller:
        """Construct the Controller lazily, after transport validation."""
        if self._controller is None:
            self._controller = Controller(self.data_dir)
        return self._controller

    @staticmethod
    def _cursor(offset: int) -> str:
        return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")

    @staticmethod
    def _offset(cursor: Optional[str]) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            value = base64.b64decode(
                padded.encode("ascii"), altchars=b"-_", validate=True
            ).decode("ascii")
            if not value or not value.isdigit():
                raise ValueError("cursor is not a decimal offset")
            offset = int(value)
        except (UnicodeError, ValueError) as exc:
            raise DevFlowError("CURSOR_INVALID", "task cursor is invalid") from exc
        if offset > 1_000_000:
            raise DevFlowError("CURSOR_INVALID", "task cursor exceeds the supported range")
        return offset

    @staticmethod
    def _task_id(arguments: Mapping[str, object]) -> Optional[str]:
        value = arguments.get("task_id")
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _recovery_tool(tool: str) -> str:
        if tool == "dev_flow_start_task":
            return "dev_flow_get_task"
        return "dev_flow_get_next_action"

    def _data_root_health(self) -> tuple[bool, Optional[str]]:
        """Check availability without returning or logging the protected path."""
        try:
            root = Path(self.data_dir).expanduser()
            if root.is_symlink():
                return False, "DATA_PATH_UNSAFE"
            if root.exists():
                if not root.is_dir() or not os.access(root, os.R_OK | os.W_OK | os.X_OK):
                    return False, "DATA_PATH_UNSAFE"
            else:
                parent = root.parent
                while not parent.exists() and parent != parent.parent:
                    parent = parent.parent
                if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
                    return False, "DATA_PATH_FAILED"
            # Construction validates the canonical root but does not create state.
            self.controller.inspect_product()
        except DevFlowError as exc:
            return False, exc.code
        except (OSError, ValueError):
            return False, "DATA_PATH_FAILED"
        return True, None

    def call(
        self,
        tool: str,
        arguments: Mapping[str, object],
        *,
        cancellation_check: Optional[CancellationCheck] = None,
    ) -> CallToolResult:
        request_id = new_request_id()
        task_id = self._task_id(arguments)
        is_mutation = tool in MUTATION_TOOLS
        entered_mutation = False
        controller_returned = False
        check = cancellation_check or cooperative_cancellation_requested

        def cancellation_checkpoint() -> None:
            if check():
                raise cancelled_failure()

        try:
            try:
                _canonical_bytes(arguments)
            except (TypeError, ValueError, UnicodeError) as exc:
                raise MCPRuntimeFailure(
                    "INTERNAL_ERROR",
                    "Tool input escaped canonical transport validation.",
                    recovery={"kind": "correct-request", "blind_retry": False},
                ) from exc
            payload = arguments.get("payload")
            if payload is not None:
                try:
                    payload_bytes = _canonical_bytes(payload)
                except (TypeError, ValueError, UnicodeError) as exc:
                    raise MCPRuntimeFailure(
                        "INTERNAL_ERROR",
                        "Action payload escaped canonical transport validation.",
                        recovery={"kind": "correct-request", "blind_retry": False},
                    ) from exc
                if len(payload_bytes) > MAX_ACTION_PAYLOAD_BYTES:
                    raise DevFlowError(
                        "PAYLOAD_LIMIT",
                        "action payload exceeds the current product byte limit",
                    )
            if check():
                raise cancelled_failure()

            if is_mutation:
                coordination_key = task_id or "__admission__"
                with self.coordinator.mutation(
                    coordination_key,
                    cancellation_check=check,
                ):
                    if check():
                        raise cancelled_failure()
                    entered_mutation = True
                    data, summary = self._dispatch(
                        tool,
                        arguments,
                        cancellation_checkpoint=cancellation_checkpoint,
                    )
                    controller_returned = True
            elif tool in LIVE_TOOLS:
                with self.coordinator.capture(cancellation_check=check):
                    if check():
                        raise cancelled_failure()
                    data, summary = self._dispatch(tool, arguments)
            else:
                data, summary = self._dispatch(tool, arguments)

            if check():
                if is_mutation:
                    task_id = task_id or (
                        str(data.get("task_id"))
                        if isinstance(data, Mapping) and data.get("task_id")
                        else None
                    )
                    raise completion_uncertain_failure(
                        task_id=task_id,
                        recovery_tool=self._recovery_tool(tool),
                    )
                raise cancelled_failure()

            self._enforce_result_limits(tool, data)
            result = success(tool, data, summary, request_id)
            if len(_canonical_bytes(result.structured_content)) > MAX_STRUCTURED_RESULT_BYTES:
                raise MCPRuntimeFailure(
                    "MCP_RESULT_LIMIT",
                    "MCP structured result exceeds 512 KiB.",
                    recovery={"kind": "narrow-request", "blind_retry": False},
                )
            return result
        except MCPRuntimeFailure as exc:
            if is_mutation and entered_mutation and (
                controller_returned
                or exc.code in {"MCP_RESULT_LIMIT", "INTERNAL_ERROR"}
            ):
                exc = completion_uncertain_failure(
                    task_id=task_id,
                    recovery_tool=self._recovery_tool(tool),
                )
            emit(
                level="warning" if exc.code in {"REQUEST_CANCELLED", "MCP_RUNTIME_UNAVAILABLE"} else "error",
                event="tool_failed",
                request_id=request_id,
                tool=tool,
                code=exc.code,
                redactions=self._redactions,
            )
            return runtime_error(tool, exc, request_id, redactions=self._redactions)
        except DevFlowError as exc:
            if exc.code == "MCP_RESULT_LIMIT":
                failure = MCPRuntimeFailure(
                    "MCP_RESULT_LIMIT",
                    "The authoritative result exceeds the bounded MCP representation.",
                    recovery={"kind": "narrow-request", "blind_retry": False},
                )
                if is_mutation and entered_mutation:
                    failure = completion_uncertain_failure(
                        task_id=task_id,
                        recovery_tool=self._recovery_tool(tool),
                    )
                emit(
                    level="error",
                    event="tool_failed",
                    request_id=request_id,
                    tool=tool,
                    code=failure.code,
                    redactions=self._redactions,
                )
                return runtime_error(tool, failure, request_id, redactions=self._redactions)
            if exc.code.startswith("MCP_"):
                # Adapter-internal pseudo-domain codes are never exposed as domain authority.
                return self._unexpected(tool, request_id, exc, possible_commit=is_mutation and entered_mutation, task_id=task_id)
            emit(
                level="warning",
                event="tool_failed",
                request_id=request_id,
                tool=tool,
                code=exc.code,
                redactions=self._redactions,
            )
            return domain_error(
                tool,
                exc,
                request_id,
                task_id=task_id,
                redactions=self._redactions,
            )
        except Exception as exc:
            return self._unexpected(
                tool,
                request_id,
                exc,
                possible_commit=is_mutation and entered_mutation,
                task_id=task_id,
            )

    def _unexpected(
        self,
        tool: str,
        request_id: str,
        exc: Exception,
        *,
        possible_commit: bool,
        task_id: Optional[str],
    ) -> CallToolResult:
        frames = [
            {
                "file": Path(frame.filename).name[:128],
                "line": frame.lineno,
                "function": frame.name[:128],
            }
            for frame in traceback.extract_tb(exc.__traceback__)[-8:]
        ]
        code = "MCP_COMPLETION_UNCERTAIN" if possible_commit else "INTERNAL_ERROR"
        emit(
            level="error",
            event="tool_failed",
            request_id=request_id,
            tool=tool,
            code=code,
            frames=frames,
            redactions=self._redactions,
        )
        if possible_commit:
            return runtime_error(
                tool,
                completion_uncertain_failure(
                    task_id=task_id,
                    recovery_tool=self._recovery_tool(tool),
                ),
                request_id,
                redactions=self._redactions,
            )
        return internal_error(tool, request_id)

    @staticmethod
    def _enforce_result_limits(tool: str, data: object) -> None:
        encoded = _canonical_bytes(data)
        if tool == "dev_flow_get_next_action" and len(encoded) > MAX_COMPACT_ACTION_BYTES:
            raise MCPRuntimeFailure(
                "MCP_RESULT_LIMIT",
                "The compact current action exceeds 128 KiB.",
                recovery={"kind": "narrow-request", "blind_retry": False},
            )
        if tool in FRESH_ACTION_MUTATIONS and isinstance(data, Mapping):
            current = data.get("current")
            validate_current_action(current)
            if current is not None and len(_canonical_bytes(current)) > MAX_COMPACT_ACTION_BYTES:
                raise MCPRuntimeFailure(
                    "MCP_RESULT_LIMIT",
                    "The fresh compact current action exceeds 128 KiB.",
                    recovery={"kind": "narrow-request", "blind_retry": False},
                )
        if tool in {"dev_flow_list_tasks", "dev_flow_find_tasks_for_path"}:
            if len(encoded) > MAX_INVENTORY_PAGE_BYTES:
                raise MCPRuntimeFailure(
                    "MCP_RESULT_LIMIT",
                    "The inventory or discovery page exceeds 256 KiB.",
                    recovery={"kind": "narrow-request", "blind_retry": False},
                )
            items = data.get("tasks", ()) if isinstance(data, Mapping) else ()
            if any(len(_canonical_bytes(item)) > MAX_TASK_SUMMARY_BYTES for item in items):
                raise MCPRuntimeFailure(
                    "MCP_RESULT_LIMIT",
                    "A task summary exceeds 2 KiB.",
                    recovery={"kind": "narrow-request", "blind_retry": False},
                )

    def _dispatch(
        self,
        tool: str,
        arguments: Mapping[str, object],
        *,
        cancellation_checkpoint: Optional[Callable[[], None]] = None,
    ) -> tuple[object, str]:
        commit_guard = (
            {"cancellation_check": cancellation_checkpoint}
            if cancellation_checkpoint is not None
            else {}
        )
        if tool == "dev_flow_server_info":
            available, health_code = self._data_root_health()
            return {
                **interface_identity(),
                "model_namespace": PLUGIN_DATA_NAMESPACE,
                "transport": "stdio",
                "python": SUPPORTED_PYTHON,
                "workflow_ids": list(WORKFLOW_IDS),
                "repository_count": {
                    "minimum": MIN_REPOSITORY_COUNT,
                    "maximum": MAX_REPOSITORY_COUNT,
                },
                "registration_mode": "unknown",
                "tool_catalog_digest": TOOL_CATALOG_DIGEST,
                "guidance_catalog_digest": GUIDANCE_CATALOG_DIGEST,
                "health": {
                    "status": "ready" if available else "unavailable",
                    "code": health_code,
                },
                "data_root_available": available,
            }, "Dev Flow MCP is ready." if available else "Dev Flow MCP data is unavailable."
        if tool == "dev_flow_list_tasks":
            limit = int(arguments.get("limit", 20))
            offset = self._offset(arguments.get("cursor") if isinstance(arguments.get("cursor"), str) else None)
            view = self.controller.inspect_tasks(
                statuses=tuple(arguments.get("statuses", ())),
                workflows=tuple(arguments.get("workflows", ())),
                terminal=arguments.get("terminal") if isinstance(arguments.get("terminal"), bool) else None,
                offset=offset,
                limit=limit,
            )
            raw_result = view.get("result", {})
            if not isinstance(raw_result, Mapping):
                raise RuntimeError("task inventory projection is invalid")
            result = dict(raw_result)
            page = result.get("page", {})
            result["next_cursor"] = (
                self._cursor(int(page["next_offset"]))
                if isinstance(page, Mapping) and isinstance(page.get("next_offset"), int)
                else None
            )
            return result, "Returned the bounded stored task inventory."
        if tool == "dev_flow_find_tasks_for_path":
            diagnostics = list(self.controller.inventory_diagnostics())
            if diagnostics:
                return {
                    "classification": "inventory-unavailable",
                    "tasks": [],
                    "diagnostics": diagnostics,
                }, "Task inventory is unavailable; no task was selected."
            try:
                states = self.controller.tasks_for_path(str(arguments["path"]))
            except DevFlowError as exc:
                if exc.code != "LEASE_INTEGRITY_CONFLICT":
                    raise
                task_ids = exc.as_dict().get("error", {}).get("details", {}).get("task_ids", [])
                return {
                    "classification": "ambiguous",
                    "tasks": [{"task_id": task_id} for task_id in task_ids],
                    "diagnostics": [{"code": exc.code}],
                }, "Multiple active tasks match; select one explicit task ID."
            tasks = [
                {"task_id": state.task_id, "status": state.status, "workflow_id": state.workflow_id}
                for state in states
            ]
            return {
                "classification": "single" if len(tasks) == 1 else "none",
                "tasks": tasks,
                "diagnostics": diagnostics,
            }, "Found {} active task(s); no task was mutated.".format(len(tasks))
        if tool == "dev_flow_get_task":
            view = self.controller.inspect_task(
                str(arguments["task_id"]),
                offset=int(arguments.get("offset", 0)),
                limit=int(arguments.get("limit", 20)),
            )
            result = view.get("result")
            if not isinstance(result, Mapping):
                raise RuntimeError("stored task projection is invalid")
            return dict(result), "Returned the stored view for task {}.".format(arguments["task_id"])
        if tool == "dev_flow_get_next_action":
            projection = self.controller.next(str(arguments["task_id"]))
            guidance = guidance_for_projection(projection)
            result = compact_current_action(projection, guidance)
            action = result.get("action") if isinstance(result, Mapping) else None
            action_id = action.get("id") if isinstance(action, Mapping) else None
            summary = (
                "Task {} current action is {}.".format(arguments["task_id"], action_id)
                if action_id
                else "Task {} is terminal; no executable action was returned.".format(arguments["task_id"])
            )
            return result, summary
        if tool == "dev_flow_start_task":
            state = self.controller.start(
                requirement=str(arguments["requirement"]),
                workflow=str(arguments["workflow"]),
                repositories=tuple(arguments["repositories"]),
                task_id=arguments.get("task_id") if isinstance(arguments.get("task_id"), str) else None,
                contract=arguments.get("contract") if isinstance(arguments.get("contract"), Mapping) else None,
                **commit_guard,
            )
            return {
                "task_id": state.task_id,
                "revision": state.revision,
                "status": state.status,
                "current_node": state.current_node,
                "repository_set": {
                    "repository_set_id": state.repository_set_id,
                    "repository_ids": [item.repository_id for item in state.repositories],
                    "count": len(state.repositories),
                },
                "next": {
                    "tool": "dev_flow_get_next_action",
                    "task_id": state.task_id,
                },
            }, "Started task {}; call dev_flow_get_next_action.".format(state.task_id)
        if tool == "dev_flow_apply_action":
            value = self.controller.apply(
                str(arguments["task_id"]),
                str(arguments["action_id"]),
                arguments.get("payload") if isinstance(arguments.get("payload"), Mapping) else {},
                binding=arguments["binding"],
                **commit_guard,
            )
            return self._mutation_view(value), "Applied the current action for task {}.".format(arguments["task_id"])
        if tool == "dev_flow_revise_contract":
            value = self.controller.revise_contract(
                str(arguments["task_id"]),
                contract=arguments["contract"],
                ownership_claims=arguments.get("ownership_claims"),
                reason=str(arguments["reason"]),
                actor_label=str(arguments["actor_label"]),
                **commit_guard,
            )
            return self._mutation_view(value), "Recorded the contract revision."
        if tool == "dev_flow_record_decision":
            value = self.controller.decide(
                str(arguments["task_id"]),
                decision=arguments["decision"],
                **commit_guard,
            )
            return self._mutation_view(value), "Recorded the exact decision."
        if tool == "dev_flow_dispose_finding":
            value = self.controller.dispose_finding(
                str(arguments["task_id"]),
                disposition=arguments["disposition"],
                actor_authorized=bool(arguments["actor_authorized"]),
                **commit_guard,
            )
            return self._mutation_view(value), "Recorded the finding disposition."
        if tool == "dev_flow_cancel_task":
            value = self.controller.cancel(
                str(arguments["task_id"]),
                reason=str(arguments["reason"]),
                **commit_guard,
            )
            return self._mutation_view(value), "Controller confirmed terminal cancellation."
        raise RuntimeError("unknown registered tool dispatch")

    @staticmethod
    def _mutation_view(value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise RuntimeError("mutation result is invalid")
        receipt = value.get("receipt")
        projection = value.get("projection")
        if not isinstance(receipt, Mapping) or not isinstance(projection, Mapping):
            raise RuntimeError("mutation receipt or projection is invalid")
        guidance = guidance_for_projection(projection)
        return {
            "receipt": dict(receipt),
            "current": compact_current_action(projection, guidance),
        }
