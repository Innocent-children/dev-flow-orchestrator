"""Request-scoped mutation identity retained through MCP response guards."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass
class MutationExecutionContext:
    tool: str
    task_id: Optional[str]

    def capture_result(self, value: object) -> None:
        """Capture authoritative task identity immediately after dispatch returns."""
        if not isinstance(value, Mapping):
            return
        candidate = value.get("task_id")
        if not isinstance(candidate, str) or not candidate:
            receipt = value.get("receipt")
            candidate = receipt.get("task_id") if isinstance(receipt, Mapping) else None
        if isinstance(candidate, str) and candidate:
            self.task_id = candidate


_CURRENT_MUTATION: ContextVar[Optional[MutationExecutionContext]] = ContextVar(
    "dev_flow_mcp_mutation_execution",
    default=None,
)


def bind_mutation_execution(
    tool: str,
    task_id: Optional[str],
) -> tuple[MutationExecutionContext, Optional[Token]]:
    """Reuse a server-owned scope or create one for a direct application call."""
    current = _CURRENT_MUTATION.get()
    if current is not None and current.tool == tool:
        if current.task_id is None and task_id:
            current.task_id = task_id
        return current, None
    execution = MutationExecutionContext(tool=tool, task_id=task_id)
    return execution, _CURRENT_MUTATION.set(execution)


def reset_mutation_execution(token: Optional[Token]) -> None:
    if token is not None:
        _CURRENT_MUTATION.reset(token)
