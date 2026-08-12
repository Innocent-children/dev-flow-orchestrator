# Activation and routing

This reference helps Codex decide whether to use Dev Flow and which existing
task to resume. It does not define Controller actions, payloads, states, or
transitions.

## Applicability

Use the Skill when either condition is true:

- The user explicitly invokes `$dev-flow`.
- The user requests substantive repository work—such as implementing a feature,
  fixing a bug, refactoring, investigating a defect, conducting a governed code
  review, or verifying a delivery—and the work benefits from resumability,
  acceptance evidence, or an authoritative next action.

Ordinarily skip it for conversational questions, isolated explanations, tiny
text-only edits, or status requests that do not need a Dev Flow task. Explicit invocation always wins.

## Repository scope

Derive the repository set from the user's requested change and the already
prepared Git worktrees. Normalize paths before task discovery. Include every
repository that the requested result must change or verify, and do not add a
repository merely because it is nearby on disk.

For more than one root, call `dev_flow_find_tasks_for_path` for each relevant
path and reconcile the returned candidate task ids. Task discovery does not
return or prove complete repository membership. For every candidate that might
be selected, call `dev_flow_get_next_action` and read the authoritative
`repository_set.repositories[].path` values from the current result.

Canonicalize the returned paths and compare them with the requested canonical
roots using both set equality and cardinality. Compatibility requires the same
members and the same number of members; a subset, superset, or different member
is a conflict. Do not execute work or call `dev_flow_apply_action` for a
conflicting candidate. Explain the mismatch and ask the user for direction.
Never combine parts of different tasks into a new inferred task.

## Discovery outcomes

- **No matching active task:** start one task for the exact repository set and
  the user's current requirement.
- **One compatible active task:** resume it using the fresh authoritative next
  action that proved exact repository-set equality.
- **One unrelated active task:** explain the conflict and ask whether to resume
  it, cancel it through the Controller, or leave it active. Do not decide for the
  user.
- **Several plausible tasks:** present the bounded choices and ask the user to
  select one. Do not pick by recency alone.
- **Inventory unavailable or inconsistent:** report the diagnostic and stop task
  selection until the authoritative inventory is available.

If the user explicitly identifies a task id, perform the same
`dev_flow_get_next_action` repository-set equality and cardinality check before
resuming it.

## Response uncertainty

After a timeout, disconnect, malformed response, or other uncertainty from a
mutating MCP call, assume neither success nor failure. Read the bounded task
summary with `dev_flow_get_task`, then call `dev_flow_get_next_action`. Retry only
when the refreshed Controller result explicitly shows that the original mutation
did not commit and the current binding still authorizes it.

## Boundary reminders

The current MCP result is authoritative. Skill prose is never evidence that an
action is allowed or complete. Do not synthesize action definitions, payload
fields, transitions, task-state files, or terminal outcomes from this reference.
Do not use legacy fail-open Hooks or introduce a shell-shaped MCP escape hatch.
