"""Stable MCP tool catalog."""

from __future__ import annotations

from typing import Optional

from mcp.server import MCPServer
from mcp.types import CallToolResult, ToolAnnotations

from .application import MCPApplication
from .schemas import (
    Cursor,
    JsonObject,
    PageLimit,
    PageOffset,
    PathText,
    RepositoryList,
    ShortText,
    StatusList,
    StrictFlag,
    TaskId,
    WorkflowRef,
    WorkflowList,
)


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
MUTATION = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
GOVERNANCE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


def register_tools(server: MCPServer, application: MCPApplication) -> None:
    def register(name: str, description: str, annotations: ToolAnnotations):
        return server.tool(
            name=name,
            description=description,
            annotations=annotations,
            meta={"dev-flow/taskSupport": "forbidden"},
            structured_output=False,
        )

    @register("dev_flow_server_info", "Return bounded Dev Flow release, model, interface, catalog, transport, and health identity.", READ_ONLY)
    def server_info() -> CallToolResult:
        return application.call("dev_flow_server_info", {})

    @register("dev_flow_list_tasks", "List bounded stored task summaries without live Git capture. Use the opaque cursor for the next page.", READ_ONLY)
    def list_tasks(
        statuses: StatusList = [],
        workflows: WorkflowList = [],
        terminal: Optional[StrictFlag] = None,
        cursor: Optional[Cursor] = None,
        limit: PageLimit = 20,
    ) -> CallToolResult:
        return application.call("dev_flow_list_tasks", {
            "statuses": statuses, "workflows": workflows, "terminal": terminal,
            "cursor": cursor, "limit": limit,
        })

    @register("dev_flow_find_tasks_for_path", "Discover active tasks containing a canonical repository path without selecting or mutating a task.", READ_ONLY)
    def find_tasks_for_path(path: PathText) -> CallToolResult:
        return application.call("dev_flow_find_tasks_for_path", {"path": path})

    @register("dev_flow_get_task", "Return a bounded stored task summary, governance state, timeline page, and terminal Dossier summary.", READ_ONLY)
    def get_task(task_id: TaskId, offset: PageOffset = 0, limit: PageLimit = 20) -> CallToolResult:
        return application.call("dev_flow_get_task", {"task_id": task_id, "offset": offset, "limit": limit})

    @register("dev_flow_get_next_action", "Capture the exact repository set and return the authoritative current action, binding, and bounded guidance.", READ_ONLY)
    def get_next_action(task_id: TaskId) -> CallToolResult:
        return application.call("dev_flow_get_next_action", {"task_id": task_id})

    @register("dev_flow_start_task", "Start one task over an exact immutable set of user-prepared Git repository roots.", MUTATION)
    def start_task(
        requirement: ShortText,
        workflow: WorkflowRef,
        repositories: RepositoryList,
        task_id: Optional[TaskId] = None,
        contract: Optional[JsonObject] = None,
    ) -> CallToolResult:
        return application.call("dev_flow_start_task", {
            "requirement": requirement, "workflow": workflow, "repositories": repositories,
            "task_id": task_id, "contract": contract,
        })

    @register("dev_flow_apply_action", "Apply exactly the projected action with its closed payload and unmodified current binding.", MUTATION)
    def apply_action(task_id: TaskId, action_id: ShortText, payload: JsonObject, binding: JsonObject) -> CallToolResult:
        return application.call("dev_flow_apply_action", {
            "task_id": task_id, "action_id": action_id, "payload": payload, "binding": binding,
        })

    @register("dev_flow_revise_contract", "Record an authorized contract revision with current ownership claims, reason, and actor label.", GOVERNANCE)
    def revise_contract(
        task_id: TaskId,
        contract: JsonObject,
        reason: ShortText,
        actor_label: ShortText,
        ownership_claims: Optional[JsonObject] = None,
    ) -> CallToolResult:
        return application.call("dev_flow_revise_contract", {
            "task_id": task_id, "contract": contract, "reason": reason,
            "actor_label": actor_label, "ownership_claims": ownership_claims,
        })

    @register("dev_flow_record_decision", "Record one exact current-model governance decision for a task.", GOVERNANCE)
    def record_decision(task_id: TaskId, decision: JsonObject) -> CallToolResult:
        return application.call("dev_flow_record_decision", {"task_id": task_id, "decision": decision})

    @register("dev_flow_dispose_finding", "Record one exact finding disposition with explicit actor authorization.", GOVERNANCE)
    def dispose_finding(task_id: TaskId, disposition: JsonObject, actor_authorized: StrictFlag) -> CallToolResult:
        return application.call("dev_flow_dispose_finding", {
            "task_id": task_id, "disposition": disposition, "actor_authorized": actor_authorized,
        })

    @register("dev_flow_cancel_task", "Cancel only through the current workflow stage's declared cancellation action.", GOVERNANCE)
    def cancel_task(task_id: TaskId, reason: ShortText) -> CallToolResult:
        return application.call("dev_flow_cancel_task", {"task_id": task_id, "reason": reason})

    # The SDK intentionally defaults argument models to ignoring unknown fields.
    # Dev Flow's transport contract is closed, so rebuild each generated model
    # with Pydantic's fail-closed extra-field policy and publish that exact schema.
    for tool in server._tool_manager.list_tools():
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)
        if tool.name == "dev_flow_start_task":
            tool.parameters["properties"]["repositories"]["uniqueItems"] = True
