---
name: follow-dev-flow
description: Start or resume the guarded V4 Dev Flow workflow for code, configuration, test, generated-file, or OpenSpec work across one or more Git repositories. Use as the public orchestration entry point to resolve full@4 or lite@4, follow the controller-selected node, obtain action approval, dispatch bounded work, record evidence, recover interrupted effects, and finish with independent review.
---

# Follow Dev Flow

Treat the V4 controller as the only workflow writer and source of truth.

## Resolve the controller

Read the Hook-injected bootstrap or task checkpoint and preserve its exact
interpreter, controller path, data directory, and arguments as `<ctl>`. Prefer
the typed MCP tools when available; otherwise use only that exact CLI prefix.
Never read or edit controller state files directly.

## Start or resume

For an existing task, request `task-next` or run:

```text
<ctl> show --task <task-id> --profile agent-v1
```

For a new task, inspect repository identity and dirt read-only, declare the
repository set, target paths, and change categories, then select:

- `lite@4` for bounded single-repository internal, test, or documentation work;
- `full@4` for full single-repository or multi-repository work.

Every task uses task schema v4 and pins its exact V4 graph and bundle identity.

## Execute the current node

1. Request `task-next` and treat its revision, frontier digest, action
   contracts, confirmations, required sections, and locators as authoritative.
2. Request `node-description` and load only the bound playbook section.
3. Use the controller-selected executor. Give workers only their bounded
   assignment and repository worktree; workers never receive controller state
   or mutation authority.
4. Preview every action requiring confirmation. Apply only the same intent at
   the same revision after explicit user approval.
5. Submit multi-repository results one at a time in controller order. The
   controller owns lease, barrier, integration, and CAS decisions.
6. Record only real test and review evidence. Reload `task-next` after a lost
   response, revision conflict, changed frontier, or invalid result.

Use `$analyze-change-impact` for the bounded impact node and
`$review-dev-flow-change` in a fresh read-only context for independent review.

## Recover safely

Use `action-recovery-inspect` and `action-recovery-preview` before any recovery
apply. If the controller returns bounded `UNRESOLVED` with operator
intervention required, stop the affected action, show its exact effects and
resume conditions, and wait for user authority. Never fabricate settlement,
compensation, approval, receipt, or recovery proof.

Do not stash, reset, clean, force-push, rebase, merge, commit, push, archive an
OpenSpec change, delete a worktree, or cancel a task without explicit authority
for that exact action.
