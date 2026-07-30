# Loaded by scripts/dev_flow.py into its shared module namespace.
# Responsibility: audited thin CLI adapters for versioned recovery kernel
# capabilities.
from __future__ import annotations


def command_action_recovery_inspect(args: object) -> dict[str, object]:
    return workflow_action_recovery_inspect_v1(args)


def command_action_recovery_preview(args: object) -> dict[str, object]:
    return workflow_action_recovery_preview_v1(args)


def command_action_recovery_apply(args: object) -> dict[str, object]:
    return workflow_action_recovery_apply_v1(args)
