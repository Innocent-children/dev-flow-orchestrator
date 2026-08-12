---
name: dev-flow
description: Start, resume, and drive authoritative Dev Flow tasks through the bundled dev-flow MCP. Use when the user invokes $dev-flow or asks Codex to implement, fix, refactor, investigate, review, verify, or otherwise carry out substantive multi-step repository work that should remain resumable and evidence-backed.
---

# Dev Flow

Use Dev Flow to keep repository work resumable and governed by the installed
Controller. Read [activation-and-routing.md](references/activation-and-routing.md)
before discovering or selecting a task.

## Activate

- Activate when the user explicitly invokes `$dev-flow`.
- Activate implicitly for substantive repository work described in the
  frontmatter, without requiring instructions in a project's `AGENTS.md`.
- Do not activate merely for a quick factual answer, a simple explanation, or
  another request that does not need a resumable repository task.
- Call `dev_flow_server_info` first. If the bundled `dev-flow` MCP is missing or
  unavailable, report that limitation; do not substitute another state store or
  workflow.

## Select Or Start The Task

1. Identify and canonicalize the exact user-prepared Git repository roots in
   scope. Do not create, switch, or otherwise manage branches or worktrees on
   the user's behalf.
2. Call `dev_flow_find_tasks_for_path` for every relevant root and reconcile the
   returned candidate task ids. Discovery does not return or prove a task's
   complete repository membership.
3. Before selecting any candidate, including a task id named by the user, call
   `dev_flow_get_next_action` for that candidate and read the authoritative
   `repository_set.repositories[].path` values from the current result.
4. Canonicalize those returned paths, then compare both set equality and
   cardinality with the requested roots. A task is compatible only when it has
   the same canonical paths and the same number of canonical roots. On any
   subset, superset, or different-member mismatch, do not execute or apply the
   candidate action; show the conflict and ask the user for direction.
5. Resume the one compatible active task when the result is unambiguous. If no
   active task id matches any relevant root, call `dev_flow_start_task` with the
   exact roots and the user's requirement. Select a workflow only from the
   current MCP tool contract and according to the task at hand.
6. If multiple tasks could match or the sole active task is unrelated, stop and
   ask the user to choose. Never cancel a task without explicit authorization.

## Drive The Controller

1. Use the fresh `dev_flow_get_next_action` result that established exact
   repository compatibility, or call it now if no current result is available.
2. If the Controller returns a terminal result, report that result and its
   Delivery Dossier. Do not invent a terminal status outside the Controller.
3. Otherwise, perform only the projected current action across its immutable
   repository set. Treat the returned action id, guidance, payload schema, and
   binding as the live contract.
4. Call `dev_flow_apply_action` with the exact current binding and a payload that
   conforms to the returned closed schema. Do not add speculative fields.
5. Continue from the action returned by a successful mutation, or refresh with
   `dev_flow_get_next_action` before doing more work.

If a mutating call has an uncertain or lost response, inspect the task with
`dev_flow_get_task` and refresh the current action before deciding whether a
retry is safe. Never blindly replay a mutation.

## Preserve The Authority Boundary

- The MCP Controller is the sole task-state writer and the sole authority for
  actions, payloads, transitions, review obligations, verification, and terminal
  outcomes.
- This Skill supplies activation and routing guidance only. Never encode a
  parallel action catalog, payload schema, state machine, or completion rule in
  the Skill or its references.
- Never read or edit Controller state files directly, reuse a stale binding, or
  treat a Hook as workflow authority.
- Do not add or invoke a generic shell MCP tool. Use normal repository tools only
  when they are needed to perform the Controller's current projected action.
- Preserve all repository-specific instructions and user authority boundaries
  while carrying out the projected action.
