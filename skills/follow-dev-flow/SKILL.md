---
name: follow-dev-flow
description: Start or resume the V5 Dev Flow workflow for code, configuration, test, generated-file, or OpenSpec work in one Git repository. Use the injected current controller locator, read the next projection, do exactly what it says, and apply the action. No approval ceremony, no recovery protocol.
---

# Follow Dev Flow

Treat the V5 controller as the only workflow writer and source of truth.

## Use the injected controller

Preserve the exact Hook-injected locator as:

```text
<ctl> = <exact injected locator>
```

The locator already contains the packaged Python launcher, CLI handler and
`--data-dir` for the V5 state directory. Do not reconstruct, shorten or append
another data directory.

Never read or edit controller state files directly. Record only real
implementation and test evidence.

## Start or resume

For a new task, make the workflow and repository explicit:

```text
<ctl> start --requirement <text> --workflow lite --repo <absolute-path>
```

`--workflow` accepts a built-in id (`lite`) or the absolute path to a custom
workflow file. For an existing task, run:

```text
<ctl> next <task-id>
```

## Execute the current node

1. Read the persisted `projection.requirement`, then the one current
   `action.action_id` and its required payload fields (`action.payload`).
2. Do the work the action describes, then apply it with the declared fields:

   ```text
   <ctl> apply <task-id> --action <action-id> --payload-json <json-object>
   ```

   The first action is always `task.preflight` with an empty payload; the
   controller records read-only Git evidence itself.
3. The apply response contains the fresh projection. Repeat until
   `projection.done` is `true`.
4. On `REVISION_CONFLICT`, read `error.details.projection` and re-run
   `next`; never guess a revision.

## Cancel

Only after explicit user instruction:

```text
<ctl> cancel <task-id> --reason <text>
```

## Read-only helpers

Use `$analyze-change-impact` when the workflow's action requires impact
analysis and `$review-dev-flow-change` for the implementation review.

A node may declare `driver: {tool: openspec}` (or another tool name) as an
opaque label. That only means: perform that node's work with the named tool
and record the structured result. The runtime never interprets the driver.

Do not stash, reset, clean, force-push, rebase, merge, commit, push, or cancel
a task without explicit user instruction for that exact action.
