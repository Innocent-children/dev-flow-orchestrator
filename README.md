# Dev Flow Orchestrator

[English](README.md) | [简体中文](README.zh-CN.md)

A guarded development workflow for Codex across Git repositories, `codebase-memory-mcp`, and OpenSpec. It persists machine-readable task state, keeps human approvals explicit, and reviews committed, staged, unstaged, and untracked changes before handoff.

The supported runtime contract is native Windows, macOS, and Linux with Python 3.9 through 3.14 and a real Git installation with `git worktree` support. The controller and hook runtime use only the Python standard library; no POSIX compatibility layer is required on Windows.

**New here?** Work through [Setup](#setup) top to bottom — six steps, a few minutes. [Configuration reference](#configuration-reference) is the one-screen summary of every setting. Everything after that explains how the workflow behaves and why.

---

## Setup

These placeholders appear throughout. Substitute your own values; nothing expands them for you.

| Placeholder | Meaning | Typical value |
| --- | --- | --- |
| `<python>` | Supported Python 3.9–3.14 interpreter, absolute path | `/usr/bin/python3`, `C:\Users\me\AppData\Local\Programs\Python\Python314\python.exe` |
| `<plugin-root>` | Where the installed plugin lives | `~/plugins/dev-flow-orchestrator`, `%USERPROFILE%\.codex\plugins\cache\personal\dev-flow-orchestrator\0.2.0` |
| `<PLUGIN_DATA>` | The plugin's private state directory | `~/.codex/plugin-data/dev-flow-orchestrator`, `%USERPROFILE%\.codex\plugin-data\dev-flow-orchestrator` |

Use absolute paths for manual controller calls and global hooks. Bundled hooks resolve the installed plugin through `PLUGIN_ROOT`; workflow skills then preserve the interpreter, controller, and data-directory arguments injected by that hook instead of reconstructing a launcher.

### 1. Install the prerequisites

| Requirement | Needed for | Check |
| --- | --- | --- |
| Python 3.9 through 3.14 | controller, hooks, and validation | `<python> --version` |
| Native Git with `git worktree` support | repository evidence and managed worktrees | `git --version` |
| `codebase-memory-mcp`, enabled | the full flow only (impact analysis, workspace discovery) | the MCP server appears in your Codex tool list |
| OpenSpec on `PATH` | the OpenSpec route only | `openspec --version` |

The lite flow needs only a supported Python and Git. The full flow additionally needs codebase-memory, and only the OpenSpec route needs OpenSpec. The plugin intentionally ships no machine-specific `.mcp.json`; keep using your existing user- or project-scoped MCP configuration.

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

**First try the bundled registration.** Codex discovers `hooks/hooks.json` at its default plugin location; the plugin manifest intentionally has no unsupported `hooks` field. Every handler has a POSIX `command` and a Windows `commandWindows`, and both invoke `hooks/dev_flow_hook.py`. On macOS/Linux the command uses quoted `$PLUGIN_ROOT`; on Windows `hooks/dev_flow_hook.cmd` safely uses `%PLUGIN_ROOT%`, probes `py -3`, then explicit `py -3.14` through `py -3.9`, and finally `python`. It preserves stdin/stdout and the exit code, and reports a non-mutating diagnostic if no launcher supplies Python 3.9–3.14. Start a new task and look for a `Dev Flow controller bootstrap:` block in the session context. If it appears, skip to step 4.

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
            "command": "\"<absolute-posix-python>\" \"<absolute-plugin-root>/hooks/dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "commandWindows": "\"<absolute-windows-python>\" \"<absolute-plugin-root>\\hooks\\dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
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
            "command": "\"<absolute-posix-python>\" \"<absolute-plugin-root>/hooks/dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "commandWindows": "\"<absolute-windows-python>\" \"<absolute-plugin-root>\\hooks\\dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "^(Bash|apply_patch|Edit|Write)$",
        "hooks": [
          {
            "type": "command",
            "command": "\"<absolute-posix-python>\" \"<absolute-plugin-root>/hooks/dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
            "commandWindows": "\"<absolute-windows-python>\" \"<absolute-plugin-root>\\hooks\\dev_flow_hook.py\" --data-dir \"<absolute-PLUGIN_DATA>\"",
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
| `PreToolUse.matcher` | which canonical tool names the guardrails intercept | retain `^(Bash\|apply_patch\|Edit\|Write)$`; the package validator checks this contract |
| `command` | macOS/Linux hook invocation | use an absolute supported interpreter, hook path, and data directory; quote every path |
| `commandWindows` | native Windows hook invocation | target the same Python handler with an absolute Windows interpreter/path; backslashes inside JSON strings are doubled (`C:\\Users\\...`) |
| `timeout` | seconds before Codex abandons the hook | `10` is enough. The hook is fail-open by design — on timeout or error it emits nothing rather than blocking your session |
| `statusMessage` | text shown while the hook runs | cosmetic; omit freely |

`UserPromptSubmit` takes no `matcher` — it fires on every prompt. The bundled Windows shim is for plugin-managed discovery; global registrations should use a verified absolute interpreter as shown above because they receive neither `PLUGIN_ROOT` nor `PLUGIN_DATA`. After editing this file, start a new task; Codex may also ask you to review and trust the hooks, and declining leaves you with no guardrails.

### 4. Point the controller at a data directory

`<PLUGIN_DATA>` is the plugin's private state directory. It holds your scope configuration, every task's state, and the managed worktrees — it is not inside your repository and not inside `<plugin-root>`. The controller resolves it in this order, first hit wins:

| Source | Scope | Notes |
| --- | --- | --- |
| `--data-dir <path>` | one call | What the skills always pass. May appear before or after the subcommand |
| `DEV_FLOW_DATA_DIR` | one process | Useful as a personal safety net so a forgotten `--data-dir` still lands in the right place |
| `PLUGIN_DATA` | one process | Injected by Codex for plugin-managed hooks. A global hook registration does **not** get this |
| native per-user state directory | fallback | Windows `%LOCALAPPDATA%\dev-flow-orchestrator` (home-based local-app-data fallback), macOS `~/Library/Application Support/dev-flow-orchestrator`, Linux `$XDG_STATE_HOME/dev-flow-orchestrator` (default `~/.local/state/dev-flow-orchestrator`) |

Whitespace-only explicit/environment values are treated as unset; they never resolve relative to the working directory. The last row is a real hazard: forget `--data-dir` with no environment variable set and the controller creates a **second, empty** native state store. Your scope and tasks appear to vanish. Either pass `--data-dir` on every call, or set the fallback once.

macOS/Linux Bash:

```bash
export DEV_FLOW_DATA_DIR="$HOME/.codex/plugin-data/dev-flow-orchestrator"
```

Windows PowerShell:

```powershell
$env:DEV_FLOW_DATA_DIR = "$env:USERPROFILE\.codex\plugin-data\dev-flow-orchestrator"
```

Windows Command Prompt:

```bat
set "DEV_FLOW_DATA_DIR=%USERPROFILE%\.codex\plugin-data\dev-flow-orchestrator"
```

The directory is created on first use; do not pre-populate or hand-edit anything in it except through the `scope` command. On POSIX, controller-owned directories are kept at mode `0700` and state/configuration/event/lock/receipt/temporary files at `0600`. On Windows, the controller verifies the actual owner and inherited DACL through standard-library Win32 bindings and blocks mutations when the descriptor is null, unreadable, owned unexpectedly, or broadly writable; POSIX mode bits are not treated as Windows ACL enforcement.

An active task and its state directory are platform-local. Do not copy or synchronize `<PLUGIN_DATA>`, linked worktrees, lock/quarantine files, or an in-flight task between operating systems. Finish or cancel it on the originating host and start a new task on the destination host; ordinary source commits may of course move through Git.

### 5. Limit where the plugin is active

A personal installation is visible to every project on the machine. With no configuration the plugin is active everywhere. The scope narrows that: outside it the hooks emit nothing and `start` refuses the repository, so unrelated sessions behave as if the plugin were not installed.

The scope lives in `<PLUGIN_DATA>/config.json` and is the only file there you are meant to change — through the `scope` command, not an editor:

macOS/Linux Bash:

```bash
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --add ~/work
```

Windows PowerShell:

```powershell
& "<python>" "<plugin-root>\scripts\dev_flow.py" scope --data-dir "<PLUGIN_DATA>" --add "D:\projects\my-service"
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

Platform-neutral argv form (render it with the quoting rules of your shell):

```text
<python> <plugin-root>/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --check .
```

A correct install prints one JSON line, exit code `0`:

```json
{"changed": false, "check": {"in_scope": true, "matched": "/home/me/work", "mode": "allowlist", "path": "/home/me/work/my-service", "rule": "include"}, "command": "scope", "config_path": "/home/me/.codex/plugin-data/dev-flow-orchestrator/config.json", "effective": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "missing_paths": [], "ok": true, "overrides": {}, "scope": {"exclude": [], "include": ["/home/me/work"], "mode": "allowlist"}, "summary": "active only inside the included directories"}
```

`check.in_scope` is the answer; `check.rule` and `check.matched` say which configured directory decided it (`default` means no rule matched and the mode decided). `config_path` confirms which data directory you actually reached — if that is not the path you expect, revisit step 4 before anything else.

Then confirm the hooks fire: start a new Codex task inside a scoped repository and look for the injected `Dev Flow controller bootstrap:` block naming the controller path and data directory. If it is missing, revisit step 3. If it names a data directory you do not recognize, revisit step 4.

Finally, ask Codex to start a task. The lite flow is the cheapest end-to-end check:

Platform-neutral argv form:

```text
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

It deliberately does not switch or pull the developer's current checkout. After preflight and explicit authorization, it resolves the configured remote's default branch, optionally fetches that remote, pins an immutable base commit, and creates a detached analysis worktree. The controlled fetch uses the approved effective URL and exact refspec while disabling repository hooks, custom upload-pack/transport commands, credential or askpass helpers, pruning, and automatic maintenance. If a remote requires an external authentication or SSH helper, fetch it separately under the user's normal Git policy, rerun `preflight`, and approve the resulting no-fetch baseline. Both direct and OpenSpec implementation then use separate task branches in isolated linked worktrees. Existing source-branch and dirty-state evidence remains visible and untouched; proceeding around an exact dirty snapshot requires structured approval.

The lifecycle hooks inject the exact interpreter, absolute controller, and private data-directory arguments at session start and prompt submission. The main skill preserves that ordered prefix on every controller call; it does not replace the interpreter with a platform-specific guess, and it does not assume `PLUGIN_DATA` reaches later execution tools.

### Boundaries and limitations

The hooks provide task-scoped guardrails, not a security boundary. They protect recognized file-write tools and common dangerous Git commands only while a matching task is active; shell scripts, nested tooling, hosted tools, or disabled/untrusted hooks can bypass them. The controller's state, artifact hashes, explicit approvals, and final independent review remain the source of truth. Installing this plugin does not globally restrict unrelated Codex tasks.

The evidence pipeline fails closed when Git cannot expose complete bytes reliably: tracked `assume-unchanged`/`skip-worktree` entries (including sparse checkouts), dirty initialized submodules, and clean/process content filters such as Git LFS are rejected. Host capability probes choose a truthful profile for file mode, symlink, case sensitivity, filesystem identity, and Git representation; every profile still carries a tracked-byte manifest, and an ambiguity blocks the gate instead of being called complete coverage.

Capability-aware preflight, fingerprints, baseline/workspace index records, tests, and review snapshots use evidence contract version `1`. Schema-v1 task state remains readable, but legacy evidence without the current contract/profile digest is deliberately stale for downstream gates and must be regenerated on the same host before the task can advance. A platform change is not an evidence migration path.

Workspace and repository identities use native filesystem evidence and portable comparison keys, including case-insensitive aliases, Windows drive/UNC spellings, and uncreated destination parents. Ambiguous or colliding identities fail closed before ownership is assigned.

If a Git-changing child times out or cannot be proven quiescent, the controller persists `mutation-quarantine.json` and blocks later mutations. Do not delete it or retry blindly. After inspecting the repository and process evidence, run `recover-quarantine` with the current revision; that command proves the child is gone, validates recorded postconditions, and archives the quarantine. An active or unverifiable child remains blocked.

## Controller commands

Everything the plugin does goes through one entry point, `scripts/dev_flow.py`. The skills and hooks never call anything else, so this list is the plugin's complete command surface.

Platform-neutral argv form:

```text
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
| `recover-quarantine` | both | quarantined task | Prove an interrupted child is gone, verify postconditions, and archive its durable quarantine |
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

Of these sixteen, only `scope` changes the plugin's own behavior — it is the sole writer of `config.json`. The other fifteen operate on a single task's state.

### Task setup and inspection

- `start --repo <path> [--repo <path> ...] "<requirement>"` — the requirement may also be given as `--requirement`. `--repo` is required and repeatable; the repository set, the requirement and the flow are immutable afterwards. `--flow full|lite` selects the pipeline (default `full`). `--task-id` supplies a stable id instead of a generated one, and `--protected-branch` is repeatable, extending the default `main`/`master`/`trunk` set. A repository outside the effective scope is rejected with `OUT_OF_SCOPE`.
- `show <task>` — the complete task state, including `index_selection`, which names the codebase-memory project every query in the current phase must use.
- `recover-quarantine <task> --expected-revision N` — after a child-quiescence failure, prove the recorded process/process group is gone, verify the mutation's platform and repository postconditions, and archive its durable quarantine. It never kills a process or treats a timeout as recovery.
- `list [--active-only] [--status STATE ...]` — summaries sorted newest first. `--status` is repeatable and accepts any state name.
- `scope [...]` — see [step 5](#5-limit-where-the-plugin-is-active) for every flag, and [Directory scope](#directory-scope) for the resolution rules.

### Evidence

- `preflight [--repo ...] [--remote R] [--base B]` — `--repo` defaults to every repository and accepts an id or a path. `--remote`/`--base` override the parsed defaults when the repository's configuration cannot be resolved.
- `baseline [--fetch] [--materialize]` — `--fetch` performs the constrained helper-free network fetch and requires the `baseline-fetch` approval to carry `--allow-fetch`; `--materialize` creates or reuses the detached analysis worktree at the pinned `base_sha`.
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

Platform-neutral argv form:

```text
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
├── .gitattributes                    # Canonical LF checkout policy
├── .codex-plugin/plugin.json        # Required plugin manifest
├── INSTALL.md                        # Exact personal/repository placement map
├── hooks/
│   ├── hooks.json                   # Paired POSIX/Windows hook registration
│   ├── dev_flow_hook.cmd            # Native Windows launcher shim
│   └── dev_flow_hook.py             # Shared state injection and guardrails
├── scripts/
│   ├── dev_flow.py                  # Persistent state machine and Git control plane
│   ├── audit_runtime_imports.py      # Standard-library/isolated-startup audit
│   ├── candidate_identity.py         # canonical-v1 identity + deterministic handoff
│   ├── validate_package.py           # Manifest/default-hook/inventory checks
│   ├── run_bundled_validators.py     # Official validators + dual candidate digests
│   ├── windows_native_validation.py  # Native Windows evidence runner
│   └── windows_native_validation.cmd # Windows Python launcher for the runner
├── skills/
│   ├── follow-dev-flow/             # Main workflow entry point
│   ├── analyze-change-impact/       # codebase-memory impact analysis
│   └── review-dev-flow-change/      # Independent full-change review
├── templates/marketplace-entry.json # Entry to merge into a local marketplace
├── templates/personal-marketplace.example.json # Complete first-marketplace example
├── tests/                            # Portable offline unit tests
└── .github/workflows/cross-platform.yml # Native OS/Python matrix
```

Do not copy the hook or helper scripts into each business repository. Install the whole plugin directory as one unit. In each target repository, maintain project-specific `AGENTS.md` guidance yourself and let `openspec init`/`openspec update` generate the current Codex OpenSpec skills when that route is selected.

## Development validation

Every required CI job runs the full suite on its exact checked-out `github.sha`: Python 3.9–3.14 on Linux and Python 3.9/3.14 on native macOS and Windows. Run the same release checks from this directory with a supported `<python>`.

Platform-neutral commands (one command per line):

```text
<python> -m unittest discover -s tests -v
<python> scripts/audit_runtime_imports.py
<python> scripts/validate_package.py
<python> scripts/run_bundled_validators.py --require-available
openspec validate complete-cross-platform-support --strict
```

`audit_runtime_imports.py` parses every shipped controller/hook import and starts both entry points with isolated `-I -S`. `validate_package.py` independently checks the supported manifest shape, official default discovery at `hooks/hooks.json`, paired launch commands, all three skills, references, templates, and portable case/Unicode path identity. `run_bundled_validators.py` records the candidate tree SHA-256 and Git revision before and after invoking every official Codex skill validator and the plugin-creator manifest validator. Required CI materializes those scripts from a pinned `openai/codex` commit, verifies their Git blob IDs and SHA-256 digests, and fails closed with `--require-available`. A local development run may omit that flag to emit an explicit `unavailable` diagnostic when the Codex bundles or validator runtime are absent, but release handoff must provide `DEV_FLOW_SKILL_VALIDATOR`, `DEV_FLOW_PLUGIN_VALIDATOR`, and when needed `DEV_FLOW_VALIDATOR_PYTHON`, then use the strict flag.

### Cross-host Windows native self-test

The cross-host subject is `dev-flow-canonical-v1`, not the host-local snapshot digest. Canonical v1 hashes the explicit package allowlist by exact UTF-8 POSIX path and raw file bytes, ignores timestamps/ownership/executable modes, excludes OpenSpec progress only, rejects unexpected paths and links/reparse points, and asserts the published two-file golden vector. `run_bundled_validators.py` reports both `canonical_candidate_sha256` and the separate mode-sensitive `host_local_snapshot_sha256`; only the canonical value is compared across hosts.

After implementation, documentation, workflow, and cachebuster inputs are frozen, create the byte-preserving handoff from the exact candidate. Both output paths must be new, their parent must already exist, and they must be outside the candidate root.

macOS/Linux Bash:

```bash
mkdir -p "$HOME/dev-flow-windows-handoff"
"<python>" scripts/windows_native_validation.py prepare --candidate-root . --archive "$HOME/dev-flow-windows-handoff/dev-flow-candidate.zip" --manifest "$HOME/dev-flow-windows-handoff/dev-flow-candidate.json"
```

The command prints `candidate_sha256`; preserve that exact lowercase 64-hex value as `<canonical-sha256-from-prepare>`. Transfer the ZIP and JSON without extraction or text conversion. The ZIP is deterministic `ZIP_STORED`; the external manifest binds the archive, exact member set, member hashes, and canonical digest.

On Windows, make one ordinary writable test directory available through both a local path and an already-existing UNC share. The two arguments must identify the same directory, but neither may be a drive root or share root. For example, an administrator may already have shared `C:\dev-flow-share-parent` as `DevFlowNative`; then create/use `C:\dev-flow-share-parent\test-root` and `\\localhost\DevFlowNative\test-root`. The runner never creates or removes the share.

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force "C:\dev-flow-share-parent\test-root" | Out-Null
New-Item -ItemType Directory -Force "C:\dev-flow-windows-handoff" | Out-Null
& ".\scripts\windows_native_validation.cmd" run --archive "C:\dev-flow-windows-handoff\dev-flow-candidate.zip" --manifest "C:\dev-flow-windows-handoff\dev-flow-candidate.json" --expected-canonical "<canonical-sha256-from-prepare>" --local-root "C:\dev-flow-share-parent\test-root" --unc-root "\\localhost\DevFlowNative\test-root" --code-page 936 --report "C:\dev-flow-windows-handoff\windows-native-report.json"
```

Windows Command Prompt:

```bat
scripts\windows_native_validation.cmd run --archive "C:\dev-flow-windows-handoff\dev-flow-candidate.zip" --manifest "C:\dev-flow-windows-handoff\dev-flow-candidate.json" --expected-canonical "<canonical-sha256-from-prepare>" --local-root "C:\dev-flow-share-parent\test-root" --unc-root "\\localhost\DevFlowNative\test-root" --code-page 936 --report "C:\dev-flow-windows-handoff\windows-native-report.json"
```

Code page `936` is the documented legacy default; choose another installed non-UTF-8 page when appropriate. The report path must be new, its parent must already exist, and it must be outside the handoff candidate and both test roots. Before native mutation, the runner verifies the manifest/archive/member paths and bytes, extracts without `extractall`, proves local/UNC identity, and creates only one unpredictable sentinel-owned child. It uses isolated controller state and repository-local Git configuration, scopes `chcp` to child `cmd.exe`, and safely removes only the matching child. It does not install the plugin, reuse live `<PLUGIN_DATA>`, change machine/global Git configuration, publish, push, create/remove a share, or overwrite a report. `--keep-owned-fixture-on-failure` deliberately retains only that sentinel-owned child and forces an `incomplete` report.

Return the new `windows-native-report.json` unchanged for review. A valid report must bind the expected and observed canonical digest, show passed legacy-code-page and UNC/long-path/worktree checks, and show cleanup `passed`. macOS/Linux can test preparation and fail-closed logic but can never emit native `passed`.

This project-local self-test is distinct from the real Windows Codex-host pickup smoke below. Running it authorizes neither publication/native CI dispatch nor marketplace installation. Those remain separate explicit approvals. For an authorized release dispatch, `.github/workflows/cross-platform.yml` requires the reviewed canonical digest and every Windows/macOS/Linux matrix job validates its lowercase format, asserts the golden vector, and fails on a local digest mismatch; ordinary push/pull-request checks are not release authorization.

Command execution in CI is not enough to claim Codex integration on Windows. Before publishing Windows support, install the cache-busted candidate from the confirmed local marketplace on an actual Windows Codex host, start a new task, prove default `hooks/hooks.json` discovery and `commandWindows` selection, observe real `PLUGIN_ROOT`/`PLUGIN_DATA`, and round-trip an installed path containing spaces, Unicode, and command-shell metacharacters. Record that smoke result against the same candidate digest.

## Installation placement

See [`INSTALL.md`](INSTALL.md) for the exact destination of every file, the runtime data layout under `<PLUGIN_DATA>`, and the update procedure for an already-installed copy. For personal use, place this complete directory at the plugin location referenced by your personal marketplace entry. For a repository marketplace, place it at `<marketplace-root>/plugins/dev-flow-orchestrator/` and point that marketplace entry to `./plugins/dev-flow-orchestrator`.

After installing or updating the plugin, start a new Codex task so the new skills and hooks are loaded. Review and trust the bundled hooks when Codex asks. Active task state remains local to the host on which it was created; reinstalling the plugin does not authorize copying an in-flight state directory to another operating system.
