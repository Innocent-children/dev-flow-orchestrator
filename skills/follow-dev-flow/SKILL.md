---
name: follow-dev-flow
description: Start or resume the guarded, persistent development workflow for changes to code, configuration, tests, generated files, or OpenSpec artifacts across one or more Git repositories. Use as the sole workflow entry point to preflight repositories, record baselines, analyze impact with codebase-memory, obtain the user's direct-versus-OpenSpec route choice, create isolated branches/worktrees, implement and test, run an independent full-snapshot review, and recover safely after interruption or failure.
---

# Follow Dev Flow

Drive the request through the plugin's persistent state machine. Invoke `$analyze-change-impact` and `$review-dev-flow-change` as bounded substeps; retain orchestration, gates, and recovery here.

## Resolve the controller

Resolve this `SKILL.md` to an absolute path. Treat its directory as the skill directory and its grandparent as the plugin root. The plugin hook injects an absolute interpreter, absolute controller, and absolute data directory. Let `<ctl>` mean that exact ordered argument prefix: `<injected-interpreter> <injected-controller> --data-dir <injected-data-directory>`. Preserve the injected values and their argument boundaries on every host; do not replace the interpreter with `python3`, infer a launcher from `PATH`, search for a globally installed controller, or copy the controller into a target repository.

Read the Dev Flow bootstrap or active-task checkpoint injected by the plugin hook. Capture the interpreter, controller, and data-directory values and verify that the controller path matches the one resolved from this skill. The displayed bootstrap/resume command demonstrates the platform-appropriate quoting, but execution must preserve the three injected values as separate arguments rather than reparsing or rewriting that display string. The injected data directory is required even before the first task exists. If that bootstrap context is absent, stop before `start`. Report the two possible causes without guessing a fallback directory: the plugin hooks were not loaded or trusted, or this directory is outside the configured scope in `<PLUGIN_DATA>/config.json`. Resolving the second one is the user's decision, made with the controller's `scope` command; `start` also rejects an out-of-scope repository with `OUT_OF_SCOPE`.

Run the controller's `--help` and the selected subcommand's `--help` before the first state-changing call. Treat help text as human-readable usage. Use `<ctl>` for every controller call, including `list`, `show`, and `start`; never assume an execution surface inherits the hook-only `PLUGIN_DATA` value. For every operational call, parse the single JSON stdout object; treat a nonzero exit, invalid JSON, or `ok: false` as a failed command and preserve stderr for diagnosis.

Use these resources before advancing:

- [references/state-machine.md](references/state-machine.md) for states, gates, controller usage, and route-neutral execution.
- [references/index-routing.md](references/index-routing.md) before any codebase-memory indexing or query; it defines the dual-index roles and explicit project selection.
- [references/openspec-route.md](references/openspec-route.md) after the user selects OpenSpec.
- [references/recovery.md](references/recovery.md) whenever resuming, reconciling drift, or handling a failed side effect.
- [assets/direct-contract-template.md](assets/direct-contract-template.md) to create the approved direct-route contract.

## Select new or resume

1. Query existing tasks before creating state.
2. Resume when the user supplies a task ID or deliberately selects a matching active task. Load it with `show` and continue from its recorded state and revision.
3. Start only when the request is new. Normalize the requirement and repository set, recommend a flow — `--flow lite` for a bounded, low-risk, well-understood in-place change such as a small bug fix; the default full flow for everything larger, riskier, or ambiguous — and call `start` only with the user's explicit flow choice. Retain the returned task ID and revision.
4. Never merge a new request into a merely convenient active task. Never replace, rewind, or cancel existing state without the user's explicit direction.

A lite task runs `preflight -> approve --gate lite -> IMPLEMENTING -> VERIFYING -> DONE` directly inside the source checkouts, with no baseline, impact analysis, route, managed worktree, plan artifact, or controller-bound index; the state-machine reference's [Lite flow](references/state-machine.md#lite-flow) section governs it. The rest of this skill's baseline/index/route/workspace requirements apply to full tasks.

## Run one guarded loop

1. Load the latest task JSON and reconcile it with read-only repository evidence.
2. Determine the single next legal action from the recorded state.
3. Perform that action, then record its evidence through the controller using the latest `--expected-revision`.
4. Reload the task after every successful mutation. Do not infer the next revision or replay a transition blindly.
5. Stop at each human gate and present the decision, evidence, risks, and recovery implications. Continue only after an explicit choice.
6. Continue until `DONE`, `CANCELLED`, or a genuine blocker requires user input.

Always preflight and baseline every repository before impact analysis. Always run impact analysis before route selection. Require an isolated task branch/worktree for both direct and OpenSpec routes. Require approved planning before implementation and independent full-snapshot review before final handoff.

Maintain one current baseline index over the immutable pinned analysis worktree and one refreshable current-generation workspace index for every repository; retain superseded records in controller history. `codebase-memory-mcp` never chooses between them: pass the controller-selected project's exact ID on every query. Never substitute the baseline index when the workspace index is missing or stale.

Do not stash, reset, clean, force-push, rebase, merge, delete a worktree, commit, push, archive an OpenSpec change, or cancel a task unless the user explicitly authorizes that specific action. Never write the controller's state files directly.
