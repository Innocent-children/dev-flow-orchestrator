# Dev Flow Orchestrator

[English](README.md) | [简体中文](README.zh-CN.md)

A guarded development workflow for Codex across Git repositories, `codebase-memory-mcp`, and OpenSpec. It persists machine-readable task state, keeps human approvals explicit, and reviews committed, staged, unstaged, and untracked changes before handoff.

**New here?** Work through [Setup](#setup) top to bottom — six steps, a few minutes. [Configuration reference](#configuration-reference) is the one-screen summary of every setting. Everything after that explains how the workflow behaves and why.

---

## Setup

These placeholders appear throughout. Substitute your own values; nothing expands them for you.

| Placeholder | Meaning | Typical value |
| --- | --- | --- |
| `<python>` | Python 3.9+ interpreter, absolute path | `/usr/bin/python3`, `C:\Users\me\AppData\Local\Programs\Python\Python312\python.exe` |
| `<plugin-root>` | Where the installed plugin lives | `~/plugins/dev-flow-orchestrator`, `%USERPROFILE%\.codex\plugins\cache\personal\dev-flow-orchestrator\0.2.0` |
| `<PLUGIN_DATA>` | The plugin's private state directory | `~/.codex/plugin-data/dev-flow-orchestrator`, `%USERPROFILE%\.codex\plugin-data\dev-flow-orchestrator` |

Use absolute paths everywhere. Hooks run with an unpredictable working directory and a minimal environment, so a relative path or a bare `python3` is the most common cause of a silently dead setup.

### 1. Install the prerequisites

| Requirement | Needed for | Check |
| --- | --- | --- |
| Python 3.9 or newer | everything | `<python> --version` |
| Git | everything | `git --version` |
| `codebase-memory-mcp`, enabled | the full flow only (impact analysis, workspace discovery) | the MCP server appears in your Codex tool list |
| OpenSpec on `PATH` | the OpenSpec route only | `openspec --version` |

The lite flow needs only Python and Git. The plugin intentionally ships no machine-specific `.mcp.json`; keep using your existing user- or project-scoped MCP configuration.

### 2. Place the plugin

Copy the complete plugin directory to `<plugin-root>` — never individual files, and never into a business repository. Then register it in a local marketplace:

```text
~/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

If `~/.agents/plugins/marketplace.json` does not exist, copy `templates/personal-marketplace.example.json` to it. If it does exist, merge only the object from `templates/marketplace-entry.json` into its `plugins` array and leave the rest of the file alone. Restart the desktop app, install the plugin from that marketplace, and start a new task. [`INSTALL.md`](INSTALL.md) has the exact per-file placement map and the update/cachebuster procedure.

### 3. Register the hooks

The hooks are what make the workflow resumable: they re-inject the active task at session start, and they block writes and dangerous Git commands that would bypass the controller. Without them the controller still works, but nothing reminds Codex to use it.

**First try the bundled registration.** `hooks/hooks.json` is already written against `$PLUGIN_ROOT`, so if your Codex build discovers plugin hooks there is nothing to configure. Start a new task and look for a `Dev Flow controller bootstrap:` block in the session context. If it appears, skip to step 4.

**If it does not appear, register the hooks globally instead.** Create `~/.codex/hooks.json` (`%USERPROFILE%\.codex\hooks.json` on Windows). A global registration gets no `PLUGIN_ROOT` and no `PLUGIN_DATA`, so both paths must be spelled out and the data directory must be passed as `--data-dir` on the command line:

```json
{
  "description": "Global session recovery and bounded Dev Flow guardrails.",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "<python> <plugin-root>/hooks/dev_flow_hook.py --data-dir <PLUGIN_DATA>",
            "timeout": 10,
            "statusMessage": "Loading the active Dev Flow task"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "<python> <plugin-root>/hooks/dev_flow_hook.py --data-dir <PLUGIN_DATA>",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "^(Bash|bash|shell|exec_command|apply_patch|Edit|edit|Write|write)$",
        "hooks": [
          {
            "type": "command",
            "command": "<python> <plugin-root>/hooks/dev_flow_hook.py --data-dir <PLUGIN_DATA>",
            "timeout": 10,
            "statusMessage": "Checking Dev Flow guardrails"
          }
        ]
      }
    ]
  }
}
```

Field by field:

| Field | What it does | Guidance |
| --- | --- | --- |
| `SessionStart.matcher` | which session events re-inject task context | keep `startup\|resume\|clear\|compact`; dropping `compact` loses the task after a context compaction |
| `PreToolUse.matcher` | which tool names the guardrails intercept | a regex over your build's tool names. Codex builds spell these differently — if writes are not being blocked during an active task, widen it rather than assuming the hook is broken |
| `command` | the hook invocation | `<python>`, the hook path, and `--data-dir <PLUGIN_DATA>`, all absolute. On Windows use backslashes and escape them for JSON (`C:\\Users\\...`) |
| `timeout` | seconds before Codex abandons the hook | `10` is enough. The hook is fail-open by design — on timeout or error it emits nothing rather than blocking your session |
| `statusMessage` | text shown while the hook runs | cosmetic; omit freely |

`UserPromptSubmit` takes no `matcher` — it fires on every prompt. After editing this file, start a new task; Codex may also ask you to review and trust the hooks, and declining leaves you with no guardrails.

### 4. Point the controller at a data directory

`<PLUGIN_DATA>` is the plugin's private state directory. It holds your scope configuration, every task's state, and the managed worktrees — it is not inside your repository and not inside `<plugin-root>`. The controller resolves it in this order, first hit wins:

| Source | Scope | Notes |
| --- | --- | --- |
| `--data-dir <path>` | one call | What the skills always pass. May appear before or after the subcommand |
| `DEV_FLOW_DATA_DIR` | one process | Useful as a personal safety net so a forgotten `--data-dir` still lands in the right place |
| `PLUGIN_DATA` | one process | Injected by Codex for plugin-managed hooks. A global hook registration does **not** get this |
| platform state directory | fallback | Linux `$XDG_STATE_HOME/dev-flow-orchestrator` (default `~/.local/state/...`), macOS `~/Library/Application Support/dev-flow-orchestrator`, Windows `%LOCALAPPDATA%\dev-flow-orchestrator` |

The last row is a real hazard: forget `--data-dir` with no environment variable set and the controller silently creates a **second, empty** state store rather than failing. Your scope and tasks appear to vanish. Either pass `--data-dir` on every call, or set the fallback once:

```bash
export DEV_FLOW_DATA_DIR="$HOME/.codex/plugin-data/dev-flow-orchestrator"
```

```powershell
setx DEV_FLOW_DATA_DIR "$env:USERPROFILE\.codex\plugin-data\dev-flow-orchestrator"
```

The directory is created on first use; do not pre-populate or hand-edit anything in it except through the `scope` command.

### 5. Limit where the plugin is active

A personal installation is visible to every project on the machine. With no configuration the plugin is active everywhere. The scope narrows that: outside it the hooks emit nothing and `start` refuses the repository, so unrelated sessions behave as if the plugin were not installed.

The scope lives in `<PLUGIN_DATA>/config.json` and is the only file there you are meant to change — through the `scope` command, not an editor:

```bash
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --add ~/work
```

```powershell
<python> <plugin-root>\scripts\dev_flow.py scope --data-dir <PLUGIN_DATA> --add D:\projects\my-service
```

The resulting file:

```json
{
  "schema_version": 1,
  "scope": {
    "mode": "allowlist",
    "include": ["/home/me/work"],
    "exclude": []
  }
}
```

| Setting | Values | Default | Meaning |
| --- | --- | --- | --- |
| `scope.mode` | `all`, `allowlist` | `all` | `all` is active everywhere except the excludes; `allowlist` is active only inside the includes |
| `scope.include` | absolute directories | `[]` | Each entry covers the directory and its subdirectories |
| `scope.exclude` | absolute directories | `[]` | Same, but negative. Applies in **both** modes |

Every flag, with an example:

| Flag | Example | Effect |
| --- | --- | --- |
| `--add DIR` | `--add ~/work` | Include a directory tree. The **first** `--add` also flips `mode` to `allowlist`, because an include under `all` would do nothing |
| `--add-exclude DIR` | `--mode all --add-exclude ~/work/vendor` | Exclude a directory tree. Combined with `--mode all` this is a plain denylist |
| `--remove DIR` | `--remove ~/work` | Drop an include. Fails loudly if the directory was never configured, so a typo is not swallowed |
| `--remove-exclude DIR` | `--remove-exclude ~/work/vendor` | Drop an exclude |
| `--mode all\|allowlist` | `--mode allowlist` | Set the mode directly |
| `--clear` | `--clear` | Reset to active-everywhere. Also the only way to recover from a corrupted `config.json` |
| `--check [DIR]` | `--check .` | Read-only: report the decision for one directory, defaulting to the current one |

All four `DIR` flags are repeatable. Paths are expanded and made absolute when stored, so `~` and relative paths are fine on input.

**The deepest configured directory wins.** Include `~/work`, exclude `~/work/vendor`, include `~/work/vendor/mine`, and the plugin is active in the first and third only. An exactly equal include/exclude pair resolves to the exclusion.

Two environment variables override the file for a single process, without touching it — handy for a one-off session:

| Variable | Effect |
| --- | --- |
| `DEV_FLOW_SCOPE` | Replaces the includes **and** forces `allowlist` mode |
| `DEV_FLOW_SCOPE_EXCLUDE` | Replaces the excludes, in either mode |

Both take an `os.pathsep`-separated list (`:` on POSIX, `;` on Windows), and `scope` reports them back under `overrides`.

### 6. Verify the setup

```bash
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --check .
```

A correct install prints one JSON line, exit code `0`:

```json
{"changed": false, "check": {"in_scope": true, "matched": "/home/me/work", "mode": "allowlist", "path": "/home/me/work/my-service", "rule": "include"}, "command": "scope", "config_path": "/home/me/.codex/plugin-data/dev-flow-orchestrator/config.json", "effective": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "missing_paths": [], "ok": true, "overrides": {}, "scope": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "summary": "active only inside the included directories"}
```

`check.in_scope` is the answer; `check.rule` and `check.matched` say which configured directory decided it (`default` means no rule matched and the mode decided). `config_path` confirms which data directory you actually reached — if that is not the path you expect, revisit step 4 before anything else.

Then confirm the hooks fire: start a new Codex task inside a scoped repository and look for the injected `Dev Flow controller bootstrap:` block naming the controller path and data directory. If it is missing, revisit step 3. If it names a data directory you do not recognize, revisit step 4.

Finally, ask Codex to start a task. The lite flow is the cheapest end-to-end check:

```bash
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --flow lite --requirement "fix the typo in the login banner" --repo <repo-path>
```

## Configuration reference

Every setting the plugin has, in one place.

| Setting | Where | Default | Scope | Section |
| --- | --- | --- | --- | --- |
| Hook registration | `<plugin-root>/hooks/hooks.json` or `~/.codex/hooks.json` | bundled plugin registration | machine | [step 3](#3-register-the-hooks) |
| `PreToolUse` matcher | the same hooks file | `^(Bash\|apply_patch\|Edit\|Write)$` | machine | [step 3](#3-register-the-hooks) |
| Data directory | `--data-dir` | platform state directory | one call | [step 4](#4-point-the-controller-at-a-data-directory) |
| `DEV_FLOW_DATA_DIR` | environment | unset | one process | [step 4](#4-point-the-controller-at-a-data-directory) |
| `PLUGIN_DATA` | environment, injected by Codex | unset for global hooks | one process | [step 4](#4-point-the-controller-at-a-data-directory) |
| `scope.mode` | `<PLUGIN_DATA>/config.json` | `all` | machine | [step 5](#5-limit-where-the-plugin-is-active) |
| `scope.include` / `scope.exclude` | `<PLUGIN_DATA>/config.json` | `[]` | machine | [step 5](#5-limit-where-the-plugin-is-active) |
| `DEV_FLOW_SCOPE` / `DEV_FLOW_SCOPE_EXCLUDE` | environment | unset | one process | [step 5](#5-limit-where-the-plugin-is-active) |
| `--flow full\|lite` | `start` | `full` | one task, immutable | [Lite flow](#lite-flow) |
| `--protected-branch` | `start` | `main`, `master`, `trunk` | one task, immutable | [Controller commands](#controller-commands) |
| `--repo` | `start` | — (required) | one task, immutable | [Controller commands](#controller-commands) |
| `--task-id` | `start` | generated | one task | [Controller commands](#controller-commands) |

There is no global setting for the flow, the protected branches, or the repository set: they are decided per task at `start` and are immutable afterwards, so that recorded evidence always names the rules it was produced under.

---

## How it works

Every task selects one of two flows at `start`. The default full flow runs the complete pipeline. The lite flow (`start --flow lite`) covers ordinary bounded work — a small bug fix, a localized tweak — inside the configured scope without paying for the full pipeline: it runs `preflight -> lite approval -> implement -> verify -> done` directly in the user's checkout, with no baseline worktree, impact analysis, OpenSpec, managed implementation worktree, or independent-review machinery. It keeps the parts that make the workflow trustworthy: fail-closed preflight evidence, one explicit human gate bound to the exact branch/`HEAD`/working-tree snapshot (dirty trees need explicit `--allow-dirty`), drift detection at every transition, and test records that must pass and match the final worktree fingerprint before `DONE`. See [Lite flow](#lite-flow).

It uses a dual-index model per repository. A baseline project indexes the immutable detached analysis worktree for impact analysis and route decisions; a workspace project indexes the current-generation implementation worktree for planning, implementation, verification, and review discovery. Codebase-memory does not choose between them automatically: every query must pass the phase-selected project's exact returned ID. The controller exposes that choice in `show.index_selection`, archives every superseded index record for audit/ID isolation, and blocks downstream gates when a required workspace index is missing or stale.

It deliberately does not switch or pull the developer's current checkout. After preflight and explicit authorization, it resolves the configured remote's default branch, optionally fetches that remote, pins an immutable base commit, and creates a detached analysis worktree. Both direct and OpenSpec implementation then use separate task branches in isolated linked worktrees. Existing source-branch and dirty-state evidence remains visible and untouched; proceeding around an exact dirty snapshot requires structured approval.

The lifecycle hooks inject the plugin's absolute controller and private data-directory paths at session start and prompt submission. The main skill passes that data directory explicitly on every controller call, because `PLUGIN_DATA` belongs to the hook process and is not assumed to reach later shell tools.

### Boundaries and limitations

The hooks provide task-scoped guardrails, not a security boundary. They protect recognized file-write tools and common dangerous Git commands only while a matching task is active; shell scripts, nested tooling, hosted tools, or disabled/untrusted hooks can bypass them. The controller's state, artifact hashes, explicit approvals, and final independent review remain the source of truth. Installing this plugin does not globally restrict unrelated Codex tasks.

The evidence pipeline fails closed when Git cannot expose complete bytes reliably: tracked `assume-unchanged`/`skip-worktree` entries (including sparse checkouts), dirty initialized submodules, and clean/process content filters such as Git LFS are rejected. These are deliberate current limitations, not silently degraded coverage; normalize the checkout or use a separately governed repository/flow before continuing.

Avoid explicit workspace path or branch overrides that differ from another task only by letter case. On a case-insensitive filesystem, a not-yet-existing case-only alias can pass planning before Git rejects it during worktree creation; the controller then fails closed and requires collision recovery, but the current controller does not normalize those aliases at claim time.

## Controller commands

Everything the plugin does goes through one entry point, `scripts/dev_flow.py`. The skills and hooks never call anything else, so this list is the plugin's complete command surface.

```bash
<python> <plugin-root>/scripts/dev_flow.py [--data-dir <PLUGIN_DATA>] <command> [options]
```

- `--data-dir` may appear before or after the command; see [step 4](#4-point-the-controller-at-a-data-directory) for the full resolution order.
- Every command prints one JSON object on stdout and nothing else. Task commands return `ok`, `command`, `task_id`, `revision`, `status`, `flow`, and `index_selection` plus command-specific fields; `list` and `scope` return their own payloads. Failures return `{"ok": false, "error": {"code", "message", "details"}}`.
- Exit codes: `0` success, `2` a predictable `FlowError`, `1` an unexpected internal error, `130` interrupt.
- Task commands take the task id positionally or as `--task`. Every state-changing command additionally requires `--expected-revision N`; a stale value fails with `REVISION_CONFLICT` instead of overwriting a concurrent writer.
- The controller records and verifies; it never runs your build or test commands for you.

| Command | Flow | Valid states | Purpose |
| --- | --- | --- | --- |
| `start` | both | creates a task | Create an `INTAKE` task over one or more repositories |
| `show` | both | any | Print one full task snapshot |
| `list` | both | no task | List task summaries |
| `scope` | both | no task | Show or change the directories where the plugin is active |
| `preflight` | both | `INTAKE`, `PREFLIGHTED` | Record Git identity, remote/base and an exact worktree fingerprint |
| `baseline` | full | `PREFLIGHTED`, `BASELINED` | Pin each repository's remote base commit; optionally materialize the analysis worktree |
| `record-index` | full | `BASELINED`, `INDEXED` | Record codebase-memory indexing provenance for the baseline or workspace role |
| `record-artifact` | both | any active state | Hash and record an immutable file or deterministic directory artifact |
| `set-route` | full | `INDEXED`, `IMPACT_REVIEW` | Bind `direct` or `openspec` to the current impact/index evidence |
| `approve` | both | any active state | Approve a named gate with an auditable note |
| `transition` | both | any non-terminal | Make one guarded state-machine transition |
| `prepare-workspace` | full | `ROUTE_APPROVED`, `WORKSPACE_READY` | Record an approvable workspace plan or execute it into isolated worktrees |
| `record-test` | both | `IMPLEMENTING`, `VERIFYING` | Record a named command identity against exact repository fingerprints |
| `review-snapshot` | full | `VERIFYING`, `REVIEWING` | Capture `base...HEAD`, cached, unstaged and untracked review inputs |
| `cancel` | both | any non-terminal | Cancel a task with a reason |

"Any active state" means any state that is neither terminal (`DONE`, `CANCELLED`) nor `BLOCKED`; individual artifact kinds and gates narrow that further, as listed below. Full-only commands fail with `FLOW_MISMATCH` on a lite task, and `approve --gate lite` fails the same way on a full one. `preflight` is additionally accepted from `BLOCKED` when the task was blocked during preflight.

Of these fifteen, only `scope` changes the plugin's own behavior — it is the sole writer of `config.json`. The other fourteen operate on a single task's state and leave nothing behind once that task ends.

### Task setup and inspection

- `start --repo <path> [--repo <path> ...] "<requirement>"` — the requirement may also be given as `--requirement`. `--repo` is required and repeatable; the repository set, the requirement and the flow are immutable afterwards. `--flow full|lite` selects the pipeline (default `full`). `--task-id` supplies a stable id instead of a generated one, and `--protected-branch` is repeatable, extending the default `main`/`master`/`trunk` set. A repository outside the effective scope is rejected with `OUT_OF_SCOPE`.
- `show <task>` — the complete task state, including `index_selection`, which names the codebase-memory project every query in the current phase must use.
- `list [--active-only] [--status STATE ...]` — summaries sorted newest first. `--status` is repeatable and accepts any state name.
- `scope [...]` — see [step 5](#5-limit-where-the-plugin-is-active) for every flag, and [Directory scope](#directory-scope) for the resolution rules.

### Evidence

- `preflight [--repo ...] [--remote R] [--base B]` — `--repo` defaults to every repository and accepts an id or a path. `--remote`/`--base` override the parsed defaults when the repository's configuration cannot be resolved.
- `baseline [--fetch] [--materialize]` — `--fetch` performs the network fetch and requires the `baseline-fetch` approval to carry `--allow-fetch`; `--materialize` creates or reuses the detached analysis worktree at the pinned `base_sha`.
- `record-index [--role baseline|workspace] [--repo ...] [--commit SHA] [--index-id ID] [--receipt FILE] [--metadata-json JSON]` — `--role` defaults to `baseline`. `--commit` defaults to the pinned base for a baseline index and current `HEAD` for a workspace index. Omitting `--index-id` requires an `impact-degraded` approval and failure provenance in the metadata; a workspace index requires `persistence:false`.
- `record-artifact --path FILE_OR_DIR --kind KIND [--verdict PASS|CONDITIONAL|FAIL] [--metadata-json JSON]` — `--artifact` is an accepted alias for `--path`. Recognized kinds bind to a phase: `impact` (in `INDEXED`/`IMPACT_REVIEW`, and recording one clears any route approval), `direct-contract`/`openspec-plan` (in `PLANNING`), and `review-report` (in `REVIEWING`, where `--verdict` is required and must match the report's own `Verdict:` line). `workspace-plan` and `review-snapshot` are controller-generated and rejected here with `RESERVED_ARTIFACT_KIND`; other kinds are recorded as free-form evidence.
- `record-test --name NAME --command CMD --exit-code N [--repo ...] [--output FILE]` — the command string is recorded, never executed. The record binds the current plan (full) or lite approval and the repository fingerprints at recording time, so any later edit invalidates it.
- `review-snapshot [--repo ...]` — `--repo` must cover every repository in the task.

### Decisions and movement

- `set-route direct|openspec --reason "..."` — the route may also be given as `--route`.
- `approve --gate GATE --note "..." [--artifact-sha256 SHA] [--accept-conditional] [--allow-fetch] [--allow-dirty]` — gates are `baseline-fetch`, `impact-degraded`, `route`, `workspace`, `plan` and `review` on a full task, and `lite` on a lite task. Evidence-bound gates require `--artifact-sha256` naming an artifact already recorded on the task. `--accept-conditional` applies only to `review`, `--allow-fetch` only to `baseline-fetch`, and `--allow-dirty` only to `baseline-fetch` and `lite`; using one elsewhere is an `INVALID_ARGUMENT`. A `FAIL` review verdict cannot be approved at all.
- `transition STATE [--note "..."]` — the target may also be given as `--to`. Allowed edges are the flow's next state, its rework edges (back to `PLANNING`, `IMPLEMENTING`, or `INDEXED` for a full task; back to `IMPLEMENTING` or `PREFLIGHTED` for a lite one), and `BLOCKED`/`CANCELLED`. `--note` is required for `BLOCKED`, `CANCELLED`, replanning and impact reassessment. A blocked task may only resume to the state it was blocked from. Each transition re-verifies the guards for its target, so drifted worktrees, missing workspace indexes, stale reviews and non-current test records all fail closed here.
- `prepare-workspace [--repo ...] [--branch B] [--path P] [--workspace-path REPO=PATH ...] [--workspace-branch REPO=BRANCH ...] [--dry-run | --execute]` — `--dry-run` is the default and records a deterministic `workspace-plan` artifact; `--execute` performs exactly the latest plan that carries a `workspace` approval. `--path` is only valid with a single selected repository; use the repeatable `REPO=...` overrides otherwise. Branches default to `codex/<task-id>`.
- `cancel --reason "..."` — the preferred way to end a non-terminal task. A `DONE` task cannot be cancelled.

## Lite flow

The directory scope decides *where* the plugin is active; the flow decides *how much* pipeline a task inside that scope pays for. A lite task's state machine is `INTAKE -> PREFLIGHTED -> IMPLEMENTING -> VERIFYING -> DONE`:

```bash
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --flow lite --requirement "fix ..." --repo <path>
```

- The flow is chosen at `start` and immutable, like the requirement and repository set. When a lite change outgrows its scope, cancel/replace it as a full task; there is no in-place upgrade.
- The lite gate (`approve --gate lite`) replaces the baseline/route/workspace/plan/review gates with one explicit decision: work in place on the exact recorded checkouts. It binds each repository's branch, `HEAD`, and working-tree fingerprint; every new `preflight` clears it, and entering implementation re-verifies all three live.
- Full-only commands and gates (`baseline`, `record-index`, `set-route`, `prepare-workspace`, `review-snapshot`, plan/route/review approvals) fail with `FLOW_MISMATCH` on a lite task, and vice versa for the lite gate on a full task.
- Test records bind the current lite approval instead of a plan hash. Each repository still needs a current passing result whose fingerprint matches the final tree before `DONE`.
- The hooks allow file writes into the source checkouts only while a lite task is `IMPLEMENTING` or `VERIFYING`; the command guardrails (no `git reset --hard`, `clean`, `pull`, branch switching, or protected-branch commits) apply unchanged. Commit and push remain separate explicitly authorized actions.
- Lite tasks record no controller-bound codebase-memory indexes; `show.index_selection.selected_role` is `none`, and ad-hoc queries stay outside the evidence chain.

## Directory scope

[Step 5](#5-limit-where-the-plugin-is-active) covers the flags and the file format. This section covers how the decision is actually resolved.

With no configuration file the plugin is active everywhere, which is the pre-existing behavior. The scope is read by both the hooks and the controller on every event, so a change applies to the next Codex event without reinstalling the plugin.

Two deliberate carve-outs keep the scope from becoming a failure mode. An active task whose repositories or workspaces contain the current directory keeps the hooks enabled there even when the scope excludes it, so narrowing the scope mid-flight cannot silently drop that task's checkpoint or guardrails; the injected checkpoint says so. An unreadable configuration or an unimportable controller fails open to active-everywhere, because failing closed would hide the workflow instead of scoping it.

The scope is enforcement, not only quiet: `start` rejects a repository outside the effective scope with `OUT_OF_SCOPE` and names the configuration path. It is still a scoping mechanism rather than a security boundary — the same limits described under [Boundaries and limitations](#boundaries-and-limitations) apply.

Every `scope` call also returns `effective`, `summary`, and `missing_paths` for configured directories that no longer exist, which is the quickest way to spot a scope broken by a moved project.

## Source layout

Keep the files in these locations relative to the plugin root:

```text
dev-flow-orchestrator/
├── .codex-plugin/plugin.json        # Required plugin manifest
├── INSTALL.md                        # Exact personal/repository placement map
├── hooks/
│   ├── hooks.json                   # Codex lifecycle hook registration
│   └── dev_flow_hook.py             # State injection and best-effort guardrails
├── scripts/
│   └── dev_flow.py                  # Persistent state machine and Git control plane
├── skills/
│   ├── follow-dev-flow/             # Main workflow entry point
│   ├── analyze-change-impact/       # codebase-memory impact analysis
│   └── review-dev-flow-change/      # Independent full-change review
├── templates/project/AGENTS.md      # Optional policy to copy into a target repo
├── templates/marketplace-entry.json # Entry to merge into a local marketplace
├── templates/personal-marketplace.example.json # Complete first-marketplace example
└── tests/                            # Offline unit tests
```

Do not copy the hook or helper scripts into each business repository. Install the whole plugin directory as one unit. In each target repository, keep only project-specific guidance in `AGENTS.md` and let `openspec init`/`openspec update` generate the current Codex OpenSpec skills when that route is selected.

## Development validation

From this directory:

```bash
python3 -m unittest discover -s tests -v
```

Then validate the three skill directories with `skill-creator/scripts/quick_validate.py` and validate this plugin root with `plugin-creator/scripts/validate_plugin.py`.

## Installation placement

See [`INSTALL.md`](INSTALL.md) for the exact destination of every file, the runtime data layout under `<PLUGIN_DATA>`, and the update procedure for an already-installed copy. For personal use, place this complete directory at the plugin location referenced by your personal marketplace entry. For a repository marketplace, place it at `<marketplace-root>/plugins/dev-flow-orchestrator/` and point that marketplace entry to `./plugins/dev-flow-orchestrator`.

After installing or updating the plugin, start a new Codex task so the new skills and hooks are loaded. Review and trust the bundled hooks when Codex asks.
