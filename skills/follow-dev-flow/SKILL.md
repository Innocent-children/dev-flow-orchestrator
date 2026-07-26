---
name: follow-dev-flow
description: Start or resume the guarded, persistent development workflow for changes to code, configuration, tests, generated files, or OpenSpec artifacts across one or more Git repositories. Use as the sole workflow entry point to classify lite/full risk, ask the user whether to use the current branch, create and switch to a new branch, or create an isolated worktree; confirm risk-gated status transitions with the remaining Chinese-labelled workflow; preflight repositories; record evidence; implement and test; run review; and recover safely.
---

# Follow Dev Flow

Drive the request through the plugin's persistent state machine. Invoke `$analyze-change-impact` and `$review-dev-flow-change` as bounded substeps; retain orchestration, gates, and recovery here.

## Resolve the controller

Resolve this `SKILL.md` to an absolute path. Treat its directory as the skill directory and its grandparent as the plugin root. The plugin hook injects an absolute interpreter, absolute controller, and absolute data directory. Let `<ctl>` mean that exact ordered argument prefix: `<injected-interpreter> <injected-controller> --data-dir <injected-data-directory>`. Preserve the injected values and their argument boundaries on every host; do not replace the interpreter with `python3`, infer a launcher from `PATH`, search for a globally installed controller, or copy the controller into a target repository.

Read the Dev Flow bootstrap or active-task checkpoint injected by the plugin hook. Capture the interpreter, controller, and data-directory values and verify that the controller path matches the one resolved from this skill. The displayed bootstrap/resume command demonstrates the platform-appropriate quoting, but execution must preserve the three injected values as separate arguments rather than reparsing or rewriting that display string. The injected data directory is required even before the first task exists. If that bootstrap context is absent, stop before `start`. Report the two possible causes without guessing a fallback directory: the plugin hooks were not loaded or trusted, or this directory is outside the configured scope in `<PLUGIN_DATA>/config.json`. Resolving the second one is the user's decision, made with the controller's `scope` command; `start` also rejects an out-of-scope repository with `OUT_OF_SCOPE`.

Run the controller's `--help` and the selected subcommand's `--help` before the first state-changing call. The controller CLI grammar, help, stable IDs, error codes, and first-party `error.message` text stay in English; use the Chinese display names returned in `*_name`, workflow, and choice-label fields when speaking to the user. Use `<ctl>` for every controller call, including `list`, `show`, and `start`; never assume an execution surface inherits the hook-only `PLUGIN_DATA` value. For every operational call, parse the single JSON stdout object; branch on `error.code`, not localized display text, and treat a nonzero exit, invalid JSON, or `ok: false` as a failed command while preserving stderr for diagnosis.

Use these resources before advancing:

- [references/state-machine-common.md](references/state-machine-common.md) for controller protocol, flow selection, compact/sectioned state loading, per-edge confirmation, terminal-state rules, and canonical Chinese labels. Read it for every task.
- After the controller returns the immutable flow, read exactly one of [references/flow-lite.md](references/flow-lite.md) or [references/flow-full.md](references/flow-full.md). Never load both.
- For lite `INTAKE`/preflight work, additionally read [references/gates/preflight.md](references/gates/preflight.md). For full work, use the current-status routing table in `flow-full.md` and read exactly one gate bundle. Route again after a backward transition; do not preload every gate file.
- [references/index-routing.md](references/index-routing.md) before any full-flow codebase-memory indexing or query; it defines the dual-index roles and explicit project selection.
- [references/openspec-route.md](references/openspec-route.md) after the user selects OpenSpec.
- [references/recovery.md](references/recovery.md) whenever resuming, reconciling drift, or handling a failed side effect.
- [assets/direct-contract-template.md](assets/direct-contract-template.md) to create the approved direct-route contract.

## Select new or resume

1. Query existing tasks before creating state.
2. Resume when the user supplies a task ID or deliberately selects a matching active task. Load it with `show --compact`, select the flow/status references, and request only the task sections required by the next gate. Use full `show` only when a complete snapshot is genuinely necessary.
3. Start only when the request is new. Before `start` or any branch/worktree mutation, ask in Chinese and wait for the user to choose exactly one user-facing work mode:
   - **使用当前分支（精简流程）**: pass `--workspace-strategy in-place`; the controller derives `lite`.
   - **新建并切换分支（精简流程）**: present the repository, current branch/`HEAD`/status, proposed direct local branch name that is neither protected nor the resolvable remote default/base, and the exact `git switch -c <branch>` operation; create/switch only after explicit approval, then pass `--workspace-strategy branch`, from which the controller derives `lite`. Before the first confirmed all-repository preflight, both that branch and `HEAD` stay exact; afterwards the branch remains immutable, while a new `HEAD` requires a fresh all-repository preflight pair and lite approval. Do not interpret “拉分支” as permission to fetch or pull.
   - **创建独立工作树（完整流程）**: pass `--workspace-strategy worktree`; the controller derives `full`, and the later workspace plan and approval still govern actual creation.
   Before offering either lite mode, classify the request with one or more
   `--change-category` values and exact repository-relative `--target-path`
   values. Lite accepts only `internal`, `tests`, and `docs`, exactly one
   repository, and paths outside the configured protected globs. The
   full-only categories are `public-api`, `schema`, `auth`, `migration`,
   `infrastructure`, and `cross-repo`; an absent/unknown classification also
   requires full. Pass the declaration on `start`; never omit it to force a
   lite task through. Recommend one mode from the request's size and risk, but
   never infer the choice from a generic request to start or continue. Keep
   the Chinese name primary and show the stable internal ID in parentheses
   when useful. Retain the returned task ID and revision.
4. Never merge a new request into a merely convenient active task. Never replace, rewind, or cancel existing state without the user's explicit direction.

A lite task runs `preflight -> approve --gate lite -> IMPLEMENTING -> VERIFYING -> DONE` directly inside the selected source checkout branch, with no baseline, impact analysis, route, managed worktree, plan artifact, or controller-bound index; [references/flow-lite.md](references/flow-lite.md) governs it. The rest of this skill's baseline/index/route/workspace requirements apply to full tasks.

## Run one guarded loop

1. Start from the latest successful mutation receipt or load `show --compact`; request only the sections needed for the next decision and reconcile them with read-only repository evidence.
2. Determine the single next legal action from the recorded state.
3. Apply the schema-v2 risk-gated confirmation contract in the common rules.
   For an explicit `transition` or `cancel`, first call `--preview`, present the
   returned Chinese source/target and complete remaining workflow, ask for
   confirmation, then apply only that exact `intent_id` with
   `--confirm-intent`. Any changed revision or live evidence requires a new
   preview. Execute only the five exact automatic edges listed in the common
   rules without a separate state-edge prompt. `DONE` and `CANCELLED` are
   always explicit. Schema-v1 tasks retain their legacy direct-command and
   per-edge-prompt behavior; never invent a v2 intent for them. 一次确认不得授权后续状态边。 Never treat “continue”, “finish the task”, or an earlier gate approval as blanket authorization for later explicit edges.
4. Preflight is two-phase under [references/gates/preflight.md](references/gates/preflight.md): first run `preflight --preview`, which commits no state and reports the exact decision/edge; confirmed apply captures complete evidence. Handle decision drift and observation-only refresh exactly as that gate specifies.
5. After confirmation, perform only that action, then record its evidence through the controller using the latest `--expected-revision`.
6. Replace the in-memory revision, status, workflow, and action result with the successful mutation receipt. Do not issue an immediate duplicate `show` when that receipt contains every field needed next. Reload with `show --compact` or `show --section` on resume, lost/invalid response, revision conflict, or missing gate fields. Never infer the next revision or replay a transition blindly.
7. Stop at each human gate and present the decision, evidence, risks, and recovery implications. Continue only after an explicit choice. When one approved action also advances status, its durable audit record must still contain separate `gate_approved` and `state_transitioned` facts; never collapse approval and movement into one fact.
8. Continue until `DONE`, `CANCELLED`, or a genuine blocker requires user input.

Always preflight and baseline every repository before impact analysis. Always run impact analysis before route selection. Require an isolated task branch/worktree for both direct and OpenSpec routes. Require approved planning before implementation and independent full-snapshot review before final handoff. When OpenSpec is selected, honor an explicit artifact-language choice from the user; otherwise follow the dominant language of the target repository's existing OpenSpec artifacts, then its other human-readable artifacts. Stop and ask when repository signals conflict or remain unclear. Preserve machine-required identifiers and fixed syntax under the exact rules in [references/openspec-route.md](references/openspec-route.md).

Maintain one current baseline index over the immutable pinned analysis worktree and one refreshable current-generation workspace index for every repository; retain superseded records in controller history. `codebase-memory-mcp` never chooses between them: pass the controller-selected project's exact ID on every query. Never substitute the baseline index when the workspace index is missing or stale.

Do not stash, reset, clean, force-push, rebase, merge, delete a worktree, commit, push, archive an OpenSpec change, or cancel a task unless the user explicitly authorizes that specific action. Never write the controller's state files directly.
