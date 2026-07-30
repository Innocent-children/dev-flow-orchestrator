---
name: follow-dev-flow
description: Start or resume the guarded Dev Flow controller for code, configuration, test, generated-file, or OpenSpec work across one or more Git repositories. Use as the public orchestration entry point when Codex must select a safe work mode, follow the current catalog-pinned node, dispatch scoped subagents or executors, obtain per-action approval, record evidence, recover interrupted work, and finish with independent review.
---

# Follow Dev Flow

Treat the deterministic controller as the only workflow writer and source of
truth. Use Codex, subagents, Skills, MCP, and optional runtimes only as
execution adapters.

## Resolve the controller

Read the hook-injected bootstrap or task checkpoint. Preserve its absolute
interpreter, controller, data directory, and argument boundaries; call this
exact prefix `<ctl>`. Verify that the controller belongs to this plugin. If the
checkpoint is absent, stop before `start`: do not infer `PLUGIN_DATA`, search
`PATH`, or copy the controller into a repository.

Prefer the bundled typed MCP tools when available. If MCP is unavailable or
incompatible, use only the exact CLI locator returned by the checkpoint or
controller. Do not read global/subcommand help during the normal typed path.
Parse one JSON response and branch on stable English codes.

Never edit controller state, events, claims, approvals, or evidence directly.
Never give workers the controller data directory, a manager capability, or
mutating CLI/MCP tools.

## Select new or resume

For an existing task, request `task-next`; with CLI use:

```text
<ctl> show --task <task-id> --profile agent-v1
```

Resolve any returned task-scoped artifact before acting. Do not create a
second task to escape ambiguous state.

For a new task, inspect repository identity/status read-only, classify exact
categories and target paths, then ask in Chinese for one explicit work mode:

- **使用当前分支（精简流程）** — `in-place`.
- **新建并切换分支（精简流程）** — show the exact safe
  `git switch -c <branch>` action and run it only after approval.
- **创建独立工作树（完整流程）** — `worktree`; later controller planning
  still governs creation.

The package activates `lite@4` for single-repository lite work and `full@4`
for both single- and multi-repository full work. New tasks therefore use
schema v3 and pin the selected V4 bundle. Existing schema-v1/schema-v2 tasks
continue through their frozen legacy adapters; never migrate them in place.

Lite is limited to one repository, `internal`/`tests`/`docs`, and declared
paths outside protected globs. Use full for multiple repositories, public
contracts, schema, auth/security, migration, infrastructure, or material
ambiguity. Pass the declaration to `start`; never omit it to force lite.

## Dispatch one current node

Repeat this bounded loop:

1. Use the latest compact receipt, otherwise call `task-next`. Treat its pinned
   bundle, revision, frontier digest, legal actions, confirmations, required
   sections, and locators as authoritative.
2. Call `node-description` for the selected frontier item and load only its
   returned, integrity-bound playbook section. Do not preload unrelated flow
   or gate references.
3. Read only the declared task sections and evidence. Use
   [references/index-routing.md](references/index-routing.md) only for a node
   that requests codebase-memory. Use
   [references/openspec-route.md](references/openspec-route.md) only after the
   selected route is OpenSpec.
4. Choose the registered executor declared by the node. Use deterministic
   controller actions for state/Git gates, native Codex subagents for
   interactive parallel repository work, structured `codex exec` for bounded
   headless work, and optional Codex SDK/Agents Runtime only through their
   registered adapters.
5. For a fixed multi-repository frontier, dispatch only controller-issued
   assignments to distinct claimed worktrees. Workers return bounded candidate
   `NodeResult` values; the manager submits them one at a time in the
   controller's canonical order. A worker never advances state.
6. Preview every action whose contract requires confirmation. Present the
   stable and Chinese source/target labels, exact effects, and remaining
   workflow; apply only the same intent at the same revision after explicit
   approval. `DONE` and `CANCELLED` are always explicit. 一次确认不得授权后续状态边。
7. Continue from a successful compact receipt when it contains the next
   locator. Reload `task-next` after a lost/invalid response, revision conflict,
   missing field, or changed frontier. Never fabricate a revision or blindly
   replay a mutation.

Use `$analyze-change-impact` only for the bounded impact node and
`$review-dev-flow-change` in a fresh, read-only reviewer context for the
independent review node.

## Recover safely

On drift, timeout, cancellation, quarantine, missing artifacts, uncertain
runtime state, or lost responses, read
[references/recovery.md](references/recovery.md) and re-query controller
state before any retry. Runtime completion, MCP approval, Hook output, an
Agents trace, or model prose is only a candidate; it never satisfies evidence
or a guard.

If recovery returns `UNRESOLVED` with
`operator_intervention.required: true`, stop the affected work immediately.
Show the user the exact target execution, effects, scopes, reason, and listed
resume conditions, then ask the user to inspect or operate. Never redispatch,
compensate, unblock, edit controller state, or turn the user's statement alone
into recovery proof. After the user acts, reload controller state and continue
only when the controller verifies one of the returned resume conditions.
The complete intervention projection is limited to 4,096 semantic-JSON bytes.
If recovery instead returns
`ACTION_RECOVERY_OPERATOR_INTERVENTION_TOO_LARGE` or
`ACTION_RECOVERY_RESULT_INVALID`, keep the same stop-and-ask boundary, show
the reported target and byte counts, and use only the returned
`action-recovery-inspect` locator for further read-only inspection. Never
truncate or reconstruct the missing safety fields.

For every frozen schema-v1/v2 task, regardless of typed MCP availability, use
[references/state-machine-common.md](references/state-machine-common.md) and
load exactly one of [references/flow-lite.md](references/flow-lite.md) or
[references/flow-full.md](references/flow-full.md). This compatibility route
must not migrate or reinterpret the task.

Do not stash, reset, clean, force-push, rebase, merge, commit, push, archive an
OpenSpec change, delete a worktree, or cancel a task without explicit authority
for that exact action.
