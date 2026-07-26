# Dev Flow common state-machine rules

Read this file for every task. After the controller reveals the immutable
`flow` and current `status`, read exactly one flow file and only the gate bundle
selected by that flow file. Do not load every reference eagerly.

## Controller protocol

`<plugin-root>/scripts/dev_flow.py` is the sole writer of workflow state. Let
`<ctl>` mean the exact interpreter, absolute controller path, and explicit
`--data-dir <state-dir>` injected by the hook. Preserve those argument
boundaries on every call.

The controller exposes:

```text
start  show  recover-quarantine  recover-atomic-write  list  scope
preflight  baseline  record-index  record-artifact  set-route  approve
transition  prepare-workspace  record-test  review-snapshot  cancel
```

Read installed help before the first mutation. Parse the single JSON object on
stdout and branch on stable `error.code`. Never edit task JSON manually.
Mutations of an existing task require the latest returned task ID and
`--expected-revision`.

Use the smallest response that proves the next action:

```text
<ctl> list --active-only
<ctl> show --task <task-id> --compact
<ctl> show --task <task-id> --section <section>
<ctl> show --task <task-id>
```

`show --compact` returns workflow progress, including `workflow.remaining`,
plus counts without the complete task. `--section` is repeatable and returns
only the selected task sections. Use full `show` only when the complete state
is genuinely required.

A successful mutation receipt is authoritative for its returned revision,
status, workflow, and action result. Continue from that receipt when it
contains every field needed for the next decision; do not immediately issue a
duplicate `show`. Reload with compact or sectioned `show` when resuming, after
a lost/invalid response, on a revision conflict, or when the next gate needs
state not present in the receipt. Never infer a revision.

`record-test` and `review-snapshot` return compact receipts. Full repository
fingerprints are task-local content-addressed evidence under
`<state-dir>/tasks/<task-id>/artifacts/fingerprints/`, not inline response
payloads. Ask for the `tests` or `review-snapshots` section only when those
records are needed. Missing, changed, unsupported, or rollback-blocked
fingerprint blobs fail closed; never reconstruct or relabel them.
The locator deliberately has no `evidence_contract_version`: only the resolved
blob payload is v2 evidence. A controller that does not understand this storage
format therefore rejects it as stale instead of accepting an unvalidated hash.

`recover-atomic-write` takes neither task ID nor expected revision. It is the
only supported response to `ATOMIC_RECOVERY_REQUIRED`; see
[recovery.md](recovery.md). `scope` governs plugin scope and the protected-path
risk policy rather than a task and also takes no task ID.

## Flow and work-mode selection

Before `start`, ask in Chinese and wait for exactly one explicit choice:

1. **使用当前分支（精简流程）** — `--workspace-strategy in-place`.
2. **新建并切换分支（精简流程）** — show repository, branch, `HEAD`,
   status, proposed safe branch, and exact `git switch -c <branch>`; execute
   only after approval, then start with `--workspace-strategy branch`.
3. **创建独立工作树（完整流程）** — `--workspace-strategy worktree`;
   later workspace planning and approval still govern creation.

`in-place` and `branch` derive immutable `lite`; `worktree` derives immutable
`full`. The requirement, repository set, flow, and strategy are immutable.
The optional `--flow` is only a compatibility assertion. `start` rejects a
missing `--workspace-strategy`. Never treat branch-mode selection as
authorization to fetch, pull, stash, reset, clean, or switch anything beyond
the displayed local branch creation.

Before `start`, declare one or more repeatable `--change-category` values and
exact repository-relative `--target-path` values. Lite is allowed only for one
repository, categories drawn exclusively from `internal`, `tests`, and `docs`,
and targets outside the configured protected-path globs. The full-only
categories are `public-api`, `schema`, `auth`, `migration`, `infrastructure`,
and `cross-repo`. Missing/unknown categories or target paths, multiple
repositories, and protected paths fail closed with `LITE_REQUIRES_FULL`.

Configure protected globs only through `scope --add-protected-path <glob>`,
`--remove-protected-path <glob>`, or `--reset-protected-paths`. They use
normalized POSIX repository-relative syntax with literal characters, `*`, `?`,
and whole-segment `**`; absolute/drive-qualified paths, empty/`.`/`..`
segments, NUL bytes, and bracket classes are invalid. Each new task stores the
declaration plus the exact risk-policy snapshot and digest.

Use `full` for cross-repository, public-contract, migration, auth/security,
infrastructure, architecture-sensitive, materially ambiguous, or
isolation-sensitive work. Use `lite` only for bounded, low-risk,
well-understood work. Before a schema-v2 lite task enters `VERIFYING` or
`DONE`, the controller checks the live diff from the approved preflight
`HEAD`, including committed, staged, unstaged, and untracked paths. A
protected, undeclared, unreadable, or otherwise unclassifiable change makes a
read-only `--preview` report `required_flow: full` without changing status; any
actual attempt to apply that advance instead commits the task as `BLOCKED`
with `blocked.phase: lite-risk` and `required_flow: full`. Leave the checkout
untouched and explicitly cancel/replace the task with a full one; flow and
strategy are never converted in place.

## Per-transition confirmation

New tasks use task schema v2 and a default-explicit confirmation policy. Only
these exact edges are automatic and need no separate state-edge prompt:

| Flow | Command/action | Edge |
|---|---|---|
| `full` | final required baseline `record-index` | `BASELINED -> INDEXED` |
| `full` | `transition` | `WORKSPACE_READY -> PLANNING` |
| `full` | `transition` | `IMPLEMENTING -> VERIFYING` |
| `full` | `review-snapshot` | `VERIFYING -> REVIEWING` |
| `lite` | `transition` | `IMPLEMENTING -> VERIFYING` |

The whitelist is exact: do not generalize it by command name, source, target,
or perceived reversibility. Every other status edge is explicit, and
`DONE`/`CANCELLED` can never be automatic.

For an explicit `transition`, first validate and preview without mutation:

```text
<ctl> transition --task <task-id> --expected-revision <revision> --to <state> [--note <note>] --preview
```

Use its `preview.intent_id`, source/target, side effects, and the latest
receipt/workflow to ask:

```text
即将切换：<当前中文状态>（<ID>） → <目标中文状态>（<ID>）
本次动作：<command/action>
后续流程：<目标之后的全部中文主流程；终态写“无”>
是否执行这一次状态切换？
```

After approval, apply that same live intent:

```text
<ctl> transition --task <task-id> --expected-revision <revision> --to <state> [--note <note>] --confirm-intent <intent-id>
```

The canonical intent binds task ID, revision, flow, source/target, action
parameters, live evidence, side effects, and confirmation mode. Any change
returns `INTENT_STALE`; preview again instead of retrying or fabricating an
intent. 一次确认不得授权后续状态边。“继续”“完成任务”、a gate approval, or an
earlier implementation request is not blanket authorization for later edges.

Cancellation uses the same two-step protocol:

```text
<ctl> cancel --task <task-id> --expected-revision <revision> --reason <reason> --preview
<ctl> cancel --task <task-id> --expected-revision <revision> --reason <reason> --confirm-intent <intent-id>
```

Other state-changing domain commands keep their own confirmation/gate
protocols:

- `preflight --confirm-preview <token>` when its preview reports a status
  change; follow [gates/preflight.md](gates/preflight.md);
- `baseline`, `set-route`, route approval, and
  `prepare-workspace --execute` require their documented explicit action/gate
  decisions when they advance status;
- the final baseline `record-index` and `review-snapshot` are automatic only
  at the exact whitelisted edges above.

Do not use `transition` to imitate a domain command. When a gate approval also
advances status, the durable outbox records distinct `gate_approved` and
`state_transitioned` facts with different event IDs but the same transaction,
revision, and intent.

Schema-v1 tasks remain readable and retain their legacy confirmation behavior:
show the Chinese edge and obtain one explicit human confirmation, then call
`transition` or `cancel` directly. They reject v2 `--preview` and
`--confirm-intent`; never migrate them by hand or invent an intent.

`BLOCKED` retains the last good evidence and may resume only to the recorded
origin through supported recovery. `DONE` and `CANCELLED` are terminal.
`DONE` is irreversible and cannot be cancelled. Both terminal states always
require a schema-v2 preview/intent confirmation (or the schema-v1 legacy
prompt); never advance either automatically.

## Canonical display names

Use stable IDs in commands/evidence and these Chinese names with users:

| Stable ID | Chinese name |
|---|---|
| `full` | 完整流程 |
| `lite` | 精简流程 |
| `INTAKE` | 需求接收 |
| `PREFLIGHTED` | 预检完成 |
| `BASELINED` | 基线就绪 |
| `INDEXED` | 索引完成 |
| `IMPACT_REVIEW` | 影响评审 |
| `ROUTE_APPROVED` | 路线已批准 |
| `WORKSPACE_READY` | 工作区就绪 |
| `PLANNING` | 方案规划 |
| `IMPLEMENTING` | 实现中 |
| `VERIFYING` | 验证中 |
| `REVIEWING` | 独立审查 |
| `FINALIZING` | 交付确认 |
| `DONE` | 已完成 |
| `BLOCKED` | 已阻塞 |
| `CANCELLED` | 已取消 |

## Universal human gates

Never infer approval from silence. Always require explicit approval for work
mode/flow selection, cancellation, and each commit, push, merge, archive,
cleanup, branch switch, or other external Git action. Flow-specific gate files
define the remaining decisions.
