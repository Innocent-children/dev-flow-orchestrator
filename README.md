# Dev Flow Orchestrator

[English](README.md) | [简体中文](README.zh-CN.md)

A guarded development workflow for Codex across Git repositories, `codebase-memory-mcp`, and OpenSpec. It keeps the same state-machine, approval, and evidence semantics on native Windows, macOS, and Linux; persists machine-readable task state; keeps human approvals explicit; and reviews committed, staged, unstaged, and untracked changes before handoff.

The supported runtime contract is native Windows, macOS, and Linux with Python 3.9 through 3.14 and a real Git installation with `git worktree` support. The controller and hook runtime use only the Python standard library; no POSIX compatibility layer is required on Windows.

**New here?** Work through [Setup](#setup) top to bottom — six steps, a few minutes. [Configuration reference](#configuration-reference) is the one-screen summary of every setting. Everything after that explains how the workflow behaves and why.

---

## Setup

These placeholders appear throughout. Substitute your own values; nothing expands them for you.

| Placeholder | Meaning | Typical value |
| --- | --- | --- |
| `<python>` | Supported Python 3.9–3.14 interpreter, absolute path | `/usr/bin/python3`, `C:\Users\me\AppData\Local\Programs\Python\Python314\python.exe` |
| `<plugin-root>` | Where the installed plugin lives | `~/plugins/dev-flow-orchestrator`, `%USERPROFILE%\.codex\plugins\cache\personal\dev-flow-orchestrator\0.3.0` |
| `<PLUGIN_DATA>` | The plugin's private state directory | `~/.codex/plugin-data/dev-flow-orchestrator`, `%USERPROFILE%\.codex\plugin-data\dev-flow-orchestrator` |

Use absolute interpreter, handler, and data-directory paths for manual controller calls and global hooks. A hook's working directory is unpredictable and its environment is intentionally sparse, so relative paths and bare interpreter names that depend on `PATH` are common causes of a silent-looking setup failure. Bundled hooks are the exception: they use the `PLUGIN_ROOT`/`PLUGIN_DATA` injected by Codex and the packaged cross-platform launch commands; workflow skills then preserve the injected interpreter, controller, and data-directory arguments instead of reconstructing a launcher.

### 1. Install the prerequisites

| Requirement | Needed for | Check |
| --- | --- | --- |
| Python 3.9 through 3.14 | controller, hooks, and validation | `<python> --version` |
| Native Git with `git worktree` support | repository evidence and managed worktrees | `git --version` |
| `codebase-memory-mcp`, enabled | the full flow only (impact analysis, workspace discovery) | the MCP server appears in your Codex tool list |
| OpenSpec on `PATH` | the OpenSpec route only | `openspec --version` |

The lite flow needs only a supported Python and Git. The full flow additionally needs codebase-memory, and only the OpenSpec route needs OpenSpec. The plugin intentionally bundles no Python, Git, OpenSpec, POSIX compatibility layer, or machine-specific `.mcp.json`; install the first two yourself and keep using your existing user- or project-scoped MCP configuration. Python 3.9 and 3.14 run the complete validation suite on Windows, macOS, and Linux, while 3.10–3.13 run it at least on Linux; a new Python minor version is not declared supported until it enters that native matrix.

### 2. Place the plugin

Copy the complete plugin directory to `<plugin-root>` — never individual files, and never into a business repository. Then register it in a local marketplace:

```text
~/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

If `~/.agents/plugins/marketplace.json` does not exist, copy `templates/personal-marketplace.example.json` to it. If it does exist, merge only the object from `templates/marketplace-entry.json` into its `plugins` array and leave the rest of the file alone. Restart the desktop app, install the plugin from that marketplace, and start a new task. [`INSTALL.md`](INSTALL.md) has the complete package placement map and the update/cachebuster procedure.

### 3. Register the hooks

The hooks are what make the workflow resumable: they re-inject the active task at session start, and they block writes and dangerous Git commands that would bypass the controller. Without them the controller still works, but nothing reminds Codex to use it.

**First try the bundled registration.** Codex discovers `hooks/hooks.json` at its default plugin location; the plugin manifest intentionally has no unsupported `hooks` field. Every handler has a POSIX `command` and a Windows `commandWindows`, and both invoke `hooks/dev_flow_hook.py`:

- On macOS/Linux, `command` runs `python3 "$PLUGIN_ROOT/hooks/dev_flow_hook.py"`.
- On Windows, `commandWindows` invokes the bundled `hooks/dev_flow_hook.cmd`. The shim probes a supported `py -3`, then explicit `py -3.14` through `py -3.9`, and finally `python`, while preserving stdin, stdout, and the exit code.
- Both paths ultimately run the same `hooks/dev_flow_hook.py` with the real `PLUGIN_ROOT` and `PLUGIN_DATA` injected by Codex, so their handler semantics are identical.

If no Windows launcher supplies Python 3.9–3.14, the shim reports a non-mutating diagnostic. Start a new task and look for a `Dev Flow controller bootstrap:` block in the session context. Its controller prefix consists of the current `sys.executable`, the absolute controller path under `PLUGIN_ROOT`, and an explicit `--data-dir <PLUGIN_DATA>`; the workflow skills preserve that prefix exactly instead of reconstructing it as `python3`. If the block appears, skip to step 4.

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

`UserPromptSubmit` takes no `matcher` — it fires on every prompt. `SessionStart` always injects the complete resumable checkpoint. A prompt receives the single-line compact checkpoint containing task/revision/flow/status/remaining-workflow/index/next-action data and a compact resume command only when that content changed within the current Codex session. The best-effort marker is keyed by `sha256(session_id)` and stores only the compact-content digest; a missing session ID or any marker read/write/corruption failure emits instead of suppressing, preserving fail-open behavior. The command guard recognizes direct `git`/`git.exe`, absolute Git paths, supported POSIX shells, `cmd.exe /c`, Windows PowerShell, and `pwsh -Command` wrappers equivalently; a recognized wrapper payload that cannot be parsed safely is rejected with a diagnostic. The bundled Windows shim is for plugin-managed discovery; global registrations should use a verified absolute interpreter as shown above because they receive neither `PLUGIN_ROOT` nor `PLUGIN_DATA`. After editing this file, start a new task; Codex may also ask you to review and trust the hooks, and declining leaves you with no guardrails.

### 4. Point the controller at a data directory

`<PLUGIN_DATA>` is the plugin's private state directory. It holds your scope configuration, every task's state, and the managed worktrees — it is not inside your repository and not inside `<plugin-root>`. The controller resolves it in this order, first hit wins:

| Source | Scope | Notes |
| --- | --- | --- |
| `--data-dir <path>` | one call | What the skills always pass. May appear before or after the subcommand |
| `DEV_FLOW_DATA_DIR` | one process | Useful as a personal safety net so a forgotten `--data-dir` still lands in the right place |
| `PLUGIN_DATA` | one process | Injected by Codex for plugin-managed hooks. A global hook registration does **not** get this |
| native per-user state directory | fallback | Windows `%LOCALAPPDATA%\dev-flow-orchestrator` (home-based local-app-data fallback), macOS `~/Library/Application Support/dev-flow-orchestrator`, Linux `$XDG_STATE_HOME/dev-flow-orchestrator` (default `~/.local/state/dev-flow-orchestrator`) |

Whitespace-only explicit/environment values are treated as unset; they never resolve relative to the working directory. The last row is a real hazard: forget `--data-dir` with no environment variable set and the controller creates a **second, empty** native state store. Your scope and tasks appear to vanish. Either pass `--data-dir` on every call, or set `DEV_FLOW_DATA_DIR` in each controller process. The examples below affect the current shell only; if you need persistence, add the equivalent assignment to your normal shell profile or environment-management policy.

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

Windows Command Prompt:

```bat
"<python>" "<plugin-root>\scripts\dev_flow.py" scope --data-dir "<PLUGIN_DATA>" --add "D:\projects\my-service"
```

The resulting file:

```json
{
  "schema_version": 2,
  "scope": {
    "mode": "allowlist",
    "include": ["/home/me/work"],
    "exclude": []
  },
  "risk_policy": {
    "schema": "dev-flow-risk-policy/v1",
    "protected_paths": [
      ".github/workflows/**",
      "**/alembic/**",
      "**/api/**",
      "**/auth/**",
      "**/migrations/**",
      "**/schema/**",
      "**/schemas/**",
      "**/security/**",
      "**/*.graphql",
      "**/*.proto",
      "**/*.sql",
      "**/*.tf",
      "deploy/**",
      "docker-compose*.yml",
      "docker-compose*.yaml",
      "Dockerfile*",
      "infra/**",
      "infrastructure/**",
      "k8s/**",
      "terraform/**"
    ]
  }
}
```

| Setting | Values | Default | Meaning |
| --- | --- | --- | --- |
| `scope.mode` | `all`, `allowlist` | `all` | `all` is active everywhere except the excludes; `allowlist` is active only inside the includes |
| `scope.include` | absolute directories | `[]` | Each entry covers the directory and its subdirectories |
| `scope.exclude` | absolute directories | `[]` | Same, but negative. Applies in **both** modes |
| `risk_policy.protected_paths` | repository-relative POSIX globs | built-in public-contract/auth/schema/migration/infrastructure set shown above | Any declared or live changed path matching one of these globs requires full flow |

Every flag, with an example:

| Flag | Example | Effect |
| --- | --- | --- |
| `--add DIR` | `--add ~/work` | Include a directory tree. The **first** `--add` also flips `mode` to `allowlist`, because an include under `all` would do nothing |
| `--add-exclude DIR` | `--mode all --add-exclude ~/work/vendor` | Exclude a directory tree. Combined with `--mode all` this is a plain denylist |
| `--remove DIR` | `--remove ~/work` | Drop an include. Fails loudly if the directory was never configured, so a typo is not swallowed |
| `--remove-exclude DIR` | `--remove-exclude ~/work/vendor` | Drop an exclude |
| `--mode all\|allowlist` | `--mode allowlist` | Set the mode directly |
| `--clear` | `--clear` | Reset scope to active-everywhere and protected paths to the built-in defaults. Also the only way to recover from a corrupted `config.json` |
| `--add-protected-path GLOB` | `--add-protected-path "config/security/**"` | Add a protected repository-relative pattern; repeatable |
| `--remove-protected-path GLOB` | `--remove-protected-path "Dockerfile*"` | Remove one exact configured pattern; repeatable and typo-safe |
| `--reset-protected-paths` | `--reset-protected-paths` | Restore only the built-in protected-path set without changing directory scope |
| `--check [DIR]` | `--check .` | Read-only: report the decision for one directory, defaulting to the current one |

All four `DIR` flags are repeatable. Paths are expanded and made absolute when stored, so `~` and relative paths are fine on input.

Protected patterns are normalized POSIX repository-relative globs. They support literal characters, `*`, `?`, and whole-segment `**`. Absolute or drive-qualified paths, NUL bytes, empty/`.`/`..` segments, bracket classes, and `**` embedded inside another segment are rejected.

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

Platform-neutral argv form; in actual workflow execution, use the absolute interpreter, controller, and `--data-dir` prefix injected by the hook:

```text
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --workspace-strategy in-place --change-category docs --target-path docs/login-banner.md --requirement "fix the typo in the login banner" --repo <repo-path>
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
| `risk_policy.protected_paths` | `<PLUGIN_DATA>/config.json` | built-in full-flow path set | machine; snapshotted per task | [step 5](#5-limit-where-the-plugin-is-active) |
| `DEV_FLOW_SCOPE` / `DEV_FLOW_SCOPE_EXCLUDE` | environment | unset | one process | [step 5](#5-limit-where-the-plugin-is-active) |
| `--flow full\|lite` | `start` | inferred from `--workspace-strategy`; optional compatibility assertion | one `start` call | [Lite flow](#lite-flow) |
| `--workspace-strategy in-place\|branch\|worktree` | `start` | — (required) | one task, immutable | [How it works](#how-it-works) |
| `--change-category` | `start` | required for lite | one task, immutable declaration | [Lite flow](#lite-flow) |
| `--target-path` | `start` | required for lite | one task, immutable declaration | [Lite flow](#lite-flow) |
| `--protected-branch` | `start` | always includes `main`, `master`, `trunk`; repeated values extend it | one task, immutable | [Controller commands](#controller-commands) |
| `--repo` | `start` | — (required) | one task, immutable | [Controller commands](#controller-commands) |
| `--task-id` | `start` | generated | one task | [Controller commands](#controller-commands) |

There is no global setting for the workspace strategy, protected branches, or repository set: they are decided per task at `start` and are immutable afterwards. The flow is derived from the strategy and stored immutably, so recorded evidence always names the rules it was produced under.

---

## How it works

Before `start` or any branch/worktree operation, the workflow asks in Chinese for one explicit work mode:

- **使用当前分支（精简流程）**: pass `--workspace-strategy in-place`, from which the controller derives `lite`.
- **新建并切换分支（精简流程）**: first show the current branch, `HEAD`, status, proposed branch, and exact local `git switch -c <branch>` operation. After a separate approval and completed switch, pass `--workspace-strategy branch`, from which the controller derives `lite`. This choice never authorizes `fetch` or `pull`.
- **创建独立工作树（完整流程）**: pass `--workspace-strategy worktree`, from which the controller derives `full`; the deterministic workspace plan still requires a later approval.

New calls pass only `--workspace-strategy`. `--flow` remains an optional compatibility consistency assertion for old callers: a matching value is accepted, while a mismatch fails and cannot override the derived flow. The stable internal IDs remain `full`/`lite`, displayed to the user as **完整流程** and **精简流程**.

The lite flow covers ordinary bounded work without paying for the full pipeline. It runs `preflight -> lite approval -> implement -> verify -> done` directly in the selected source-checkout branch, with no baseline worktree, impact analysis, OpenSpec, managed implementation worktree, or independent-review machinery. A schema-v2 lite task requires exactly one repository, at least one low-risk `--change-category` (`internal`, `tests`, or `docs`), and one or more exact repository-relative `--target-path` values outside the protected policy. `public-api`, `schema`, `auth`, `migration`, `infrastructure`, `cross-repo`, multiple repositories, or missing/unknown declarations fail closed with `LITE_REQUIRES_FULL`.

Schema-v2 status confirmation is default-explicit with one exact automatic whitelist: the final required full baseline `record-index` (`BASELINED -> INDEXED`), full `WORKSPACE_READY -> PLANNING`, full and lite `IMPLEMENTING -> VERIFYING`, and full `review-snapshot` (`VERIFYING -> REVIEWING`). No other edge is inferred from its command or perceived safety. `DONE` and `CANCELLED` are always explicit.

For every other `transition` or `cancel`, first call `--preview`, show the Chinese `current state -> target state`, action, side effects, and all remaining main-flow states, then pass the exact returned `intent_id` to `--confirm-intent` after approval. The intent binds task/revision/flow/edge/action/live evidence; drift returns `INTENT_STALE` and requires a new preview. Preflight keeps its separate two-phase protocol: `--preview` performs no complete fingerprint and binds the exact status decision plus a lightweight observation; `--confirm-preview` captures complete evidence. Decision drift makes that token stale. Observation-only drift returns `PREFLIGHT_EVIDENCE_REFRESH_REQUIRED`; after inspecting and explicitly accepting the refreshed evidence, the same token can be retried with `--accept-evidence-refresh`.

Successful `baseline`, `set-route`, route approval, and `prepare-workspace --execute` remain explicit domain actions when they advance status. A route approval that also advances the task records independent `gate_approved` and `state_transitioned` audit facts with separate event IDs and a shared transaction/revision/intent; one fact never substitutes for the other.

It uses a dual-index model per repository. A baseline project indexes the immutable detached analysis worktree for impact analysis and route decisions; a workspace project indexes the current-generation implementation worktree for planning, implementation, verification, and review discovery. Codebase-memory does not choose between them automatically: every query must pass the phase-selected project's exact returned ID. The controller exposes that choice in `show.index_selection`, archives every superseded index record for audit/ID isolation, and blocks downstream gates when a required workspace index is missing or stale.

The controller itself does not switch or pull the developer's current checkout. The main skill may create/switch a local branch only when the user explicitly chooses that mode before `start`, after seeing the exact operation; the lite task then binds that branch as non-drifting preflight evidence. Full-flow implementation continues to use approved isolated linked worktrees without touching the source branch. A controlled fetch uses only the approved effective URL and exact refspec while disabling repository hooks, custom upload-pack/transport commands, credential and askpass helpers, pruning, and automatic maintenance.

When the OpenSpec route is selected, an explicit user choice determines the language of human-readable artifacts. Otherwise the workflow follows the dominant language of the target repository's existing OpenSpec artifacts, then its other human-readable artifacts. Conflicting or unclear signals require a question before writing; machine-required identifiers and fixed syntax remain unchanged.

The lifecycle hooks inject the exact interpreter, absolute controller, and private data-directory arguments at session start and in each changed compact prompt checkpoint; identical content is suppressed only within the same session. The main skill preserves that ordered prefix on every controller call; it does not replace the interpreter with a platform-specific guess, and it does not assume `PLUGIN_DATA` reaches later execution tools.

### Boundaries and limitations

The hooks provide task-scoped guardrails, not a security boundary. They protect recognized file-write tools and common dangerous Git commands only while a matching task is active; shell scripts, nested tooling, hosted tools, or disabled/untrusted hooks can bypass them. The controller's state, artifact hashes, explicit approvals, and final independent review remain the source of truth. Installing this plugin does not globally restrict unrelated Codex tasks.

The evidence pipeline fails closed when Git cannot expose complete bytes reliably: tracked `assume-unchanged`/`skip-worktree` entries (including sparse checkouts), dirty initialized submodules, and clean/process content filters such as Git LFS are rejected. Restore the checkout to a canonical state, or use a separately governed repository or process, before continuing; the workflow never silently degrades incomplete coverage.

The current evidence contract version is `2` (`evidence_contract_version: 2`). Repository fingerprints never force synthetic `core.fileMode`, `core.symlinks`, or `core.ignoreCase` values. Host capability probes instead record the truthful Git/filesystem profile and, for every tracked entry, the raw path, index mode/object/stage, working-tree type, and on-disk byte digest. Platforms may express different capabilities, but every profile still carries a tracked-byte manifest; an incomplete or ambiguous observation blocks the gate instead of being called complete coverage.

Repeated test and review fingerprints keep the same v2 semantic payload and hash but are stored once per task as `task-local-json-v1` blobs. Their state entries are storage locators, not evidence records, and deliberately omit `evidence_contract_version`; the current controller validates the blob before accepting its v2 payload, while an older controller fails closed instead of trusting an unvalidated locator. Legacy inline v2 fingerprints remain readable.

New tasks use task-state schema v2, which makes the confirmation contract and risk assessment mandatory. The current controller can still read and finish schema-v1 tasks with their legacy direct `transition`/`cancel` behavior and per-edge human prompts; v2 `--preview`/`--confirm-intent` is unavailable for them. Do not rewrite a v1 state into v2 or invent an intent/risk snapshot. Conversely, an older controller that understands only schema v1 rejects a schema-v2 task instead of silently dropping its safety fields.

Legacy v1 evidence does not satisfy the current v2 evidence contract/profile digest; it is deliberately stale for downstream gates. Regenerate the required preflight, baseline/workspace indexes, plan binding, tests, and review snapshot with a compatible current version on the same host before the task can advance. A task already beyond a state where the controller permits the required evidence refresh cannot be migrated in place; cancel and replace it instead of editing evidence. A legacy `branch`-strategy task without a start-time `branch_binding` remains inspectable but fails closed at preflight and lite gates; cancel and replace it instead of inventing approval evidence. Do not relabel legacy evidence or reuse a baseline codebase-memory project as a workspace project. Pointing an older plugin that does not understand the current capability profile at a data directory already handled by this version is also unsafe: reinstall a version that supports the same evidence contract and regenerate stale evidence. Readable old state does not imply semantic compatibility, and a platform change is not an evidence migration path.

Before task state, event records, mutation/quarantine evidence, predictable errors, or CLI JSON are written or emitted, the controller applies structured redaction to recognized credential-bearing URLs, sensitive-named fields and command-line options, authorization values, and credential-like diagnostic text. Operational paths, branch names, requirements, and controller-issued preview tokens retain their required exact values. Loading a legacy state that still contains recognized sensitive material performs a locked, one-time cleanup rewrite, even when the first reader is `show` or `list`; this cleanup adds no workflow event and is not permission to hand-edit state.

Workspace and repository ownership checks normalize `/` and `\`, drive and UNC spellings, case behavior, Unicode normalization, and symlink/junction aliases. An uncreated destination binds to its nearest existing ancestor so the filesystem behavior can be probed. A capability that cannot be measured safely, or an ambiguous/colliding identity, fails closed before ownership is assigned; avoid paths and branch overrides that differ only by case or rely on platform-specific aliases.

During a protected mutation, the controller owns the child process it starts. On interruption it first requests platform-appropriate termination, escalates if necessary, waits for reaping, and releases the lock only after proving quiescence. If a Git-changing child times out or cannot be proven quiescent, the controller persists `mutation-quarantine.json` while still holding the lock and blocks every later state mutation. Do not delete or edit the file, and do not retry blindly. After read-only inspection of the reported repository and process evidence, run `recover-quarantine --task <task-id> --expected-revision <revision>`; that command proves the child is gone, validates the recorded Git/filesystem postconditions and current evidence contract, and archives the quarantine. A live or unverifiable child, revision drift, or postcondition drift remains blocked.

Every controller state file is written through a rollback-protected atomic replacement. If that write is interrupted before its cleanup — `SIGKILL`, power loss, or a hook killed at its timeout — a `.<name>.rollback-<suffix>` file survives next to the destination, and every later write to that exact file fails closed with `ATOMIC_RECOVERY_REQUIRED`, naming `details.rollback_candidates`. This is deliberate: the controller will not write over a destination whose last replacement it cannot account for. It is also not a dead end, and clearing it by hand is still not the way out. Run `recover-atomic-write` to report every candidate, then `--apply` to remove only the evidence that provably matches the committed destination, or the empty placeholder of a write that never committed a new file. Content that differs from the destination is a decision about committed state, so it stays blocked with both digests and schema summaries until you choose `--resolve keep-current` or `--resolve restore-rollback` for one `--path`, proving inspection with `--rollback-sha256`. The command never picks a side for you.

## Controller commands

Everything the plugin does goes through one entry point, `scripts/dev_flow.py`. The skills and hooks never call anything else, so this list is the plugin's complete command surface.

Platform-neutral argv form:

```text
<python> <plugin-root>/scripts/dev_flow.py [--data-dir <PLUGIN_DATA>] <command> [options]
```

- `--data-dir` may appear before or after the command; see [step 4](#4-point-the-controller-at-a-data-directory) for the full resolution order.
- Every command prints one JSON object on stdout and nothing else. Task commands keep stable `status`/`flow` IDs and additionally return `status_name`, `flow_name`, `workspace_strategy_name`, and a `workflow` object with Chinese current/remaining stages, plus `index_selection` and command-specific fields; `list` and `scope` return their own structures. Failures use `{"ok": false, "error": {"code", "message", "details"}}`.
- Controller commands, options, help, stable IDs, JSON keys, error codes, and first-party `error.message` text remain English. Hook/skill prompts and display fields such as `*_name`, workflow names, and choice labels use Chinese; automation should branch on `error.code`, not message text.
- Exit codes: `0` success, `2` a predictable `FlowError`, `1` an unexpected internal error, `130` interrupt.
- Task commands take the task id positionally or as `--task`. Every state-changing command additionally requires `--expected-revision N`; a stale value fails with `REVISION_CONFLICT` instead of overwriting a concurrent writer.
- The controller records and verifies; it never runs your build or test commands for you.

| Command | Flow | Valid states | Purpose |
| --- | --- | --- | --- |
| `start` | both | creates a task | Create an `INTAKE` task over one or more repositories |
| `show` | both | any | Print a compact, sectioned, or full task snapshot |
| `recover-quarantine` | both | quarantined task | Prove an interrupted child is gone, verify postconditions, and archive its durable quarantine |
| `recover-atomic-write` | both | no task | Report and clear rollback evidence left by an interrupted atomic state write |
| `list` | both | no task | List task summaries |
| `scope` | both | no task | Show or change the directories where the plugin is active |
| `preflight` | both | `INTAKE`, `PREFLIGHTED` | Preview one exact status edge, then record Git identity, remote/base and a fingerprint with the confirmed token |
| `baseline` | full | `PREFLIGHTED`, `BASELINED` | Pin each repository's remote base commit; optionally materialize the analysis worktree |
| `record-index` | full | `BASELINED`, `INDEXED` (baseline); `WORKSPACE_READY`, `PLANNING`, `IMPLEMENTING`, `VERIFYING` (workspace) | Record codebase-memory indexing provenance for the baseline or workspace role |
| `record-artifact` | both | any active state | Hash and record an immutable file or deterministic directory artifact |
| `set-route` | full | `INDEXED`, `IMPACT_REVIEW` | Bind `direct` or `openspec` to the current impact/index evidence |
| `approve` | both | any active state | Approve a named gate with an auditable note |
| `transition` | both | any non-terminal | Make one guarded state-machine transition |
| `prepare-workspace` | full | `ROUTE_APPROVED`, `WORKSPACE_READY` | Record an approvable workspace plan or execute it into isolated worktrees |
| `record-test` | both | `IMPLEMENTING`, `VERIFYING` | Record a named command identity against exact repository fingerprints |
| `review-snapshot` | full | `VERIFYING`, `REVIEWING` | Capture `base...HEAD`, cached, unstaged and untracked review inputs |
| `cancel` | both | any non-terminal | Cancel a task with a reason |

"Any active state" means any state that is neither terminal (`DONE`, `CANCELLED`) nor `BLOCKED`; individual artifact kinds and gates narrow that further, as listed below. Full-only commands fail with `FLOW_MISMATCH` on a lite task, and `approve --gate lite` fails the same way on a full one. `preflight` is additionally accepted from `BLOCKED` when the task was blocked during preflight.

Three of these seventeen do not target one task: `scope` is the sole writer of `config.json`; `recover-atomic-write` resolves interrupted writes to controller-owned files; and `list` enumerates summaries across tasks. The other fourteen target one task's state. While loading a legacy state, `show` or `list` may also perform the one-time sensitive-data cleanup described above.

### Task setup and inspection

- `start --repo <path> [--repo <path> ...] --workspace-strategy MODE [--change-category CATEGORY ...] [--target-path PATH ...] "<requirement>"` — `--repo` is required and repeatable; the requirement may also be given as `--requirement`. `--workspace-strategy` is required, proving a work mode was selected before creation: `in-place` and `branch` derive `lite`, while `worktree` derives `full`. Schema-v2 lite creation additionally requires exactly one repository, repeatable categories drawn only from `internal`/`tests`/`docs`, and repeatable exact repository-relative target paths that do not match the configured protected globs. Full-only categories are `public-api`, `schema`, `auth`, `migration`, `infrastructure`, and `cross-repo`; missing or unknown declarations fail closed to full. Full tasks may record the same declaration without being rejected. The task stores the normalized values plus its exact risk-policy snapshot and digest. The optional `--flow` is only a compatibility consistency assertion; a matching value is accepted and a mismatch fails instead of overriding the strategy. The repository set, requirement, derived flow, workspace strategy, and risk declaration are immutable afterwards. `branch` records the exact branch and `HEAD` reached by a user-approved switch already completed before `start`, and rejects symbolic local branches plus protected or resolvable remote-default/base branches. Both branch and `HEAD` must remain exact until the first confirmed all-repository preflight; afterwards the branch stays immutable, while a new `HEAD` requires another all-repository preflight pair and lite approval. `start` never performs the Git switch. `--task-id` may supply a stable task ID. Repeatable `--protected-branch` values always extend and never replace the default `main`/`master`/`trunk` set. Protected names prevent branch-mode binding and direct commits, but do not prohibit local edits under an explicitly selected `in-place` task. A repository outside the effective directory scope is rejected with `OUT_OF_SCOPE`.
- `show <task> [--compact | --section SECTION ...]` — full state remains the compatibility default. `--compact` returns workflow progress (including `workflow.remaining`) and task counts without the complete state; repeatable `--section` returns only selected task sections. Use the mutation receipt when it already contains the next revision/status/workflow, compact show for resume/conflict recovery, and sectioned show for gate-specific detail.
- `recover-quarantine <task> --expected-revision N` — after a child-quiescence failure, prove the recorded process/process group is gone, verify the mutation's platform and repository postconditions, and archive its durable quarantine. It never kills a process or treats a timeout as recovery.
- `recover-atomic-write [--path FILE] [--apply] [--resolve keep-current|restore-rollback] [--rollback-sha256 SHA]` — the only supported answer to `ATOMIC_RECOVERY_REQUIRED`. With no flags it reports every rollback candidate under the data directory read-only, with both sides' size, SHA-256, and schema summary. `--apply` removes only provably safe evidence. `--path` accepts the blocked destination or one of its rollback files, and is required with `--resolve`. It takes no task and no `--expected-revision`, because a stranded rollback file can block the very state write a revision check would need; it takes the interrupted writer's own lock instead. It is deliberately separate from `recover-quarantine`, which cannot help here — that command commits task state through the same atomic write, so residue would block it too, and residue can equally sit on `config.json` or `workspace-registry.json`, which belong to no task.
- `list [--active-only] [--status STATE ...]` — summaries sorted newest first. `--status` is repeatable and accepts any state name.
- `scope [...]` — see [step 5](#5-limit-where-the-plugin-is-active) for directory-scope and protected-path flags, and [Directory scope](#directory-scope) for the activation rules. It is the sole writer of configuration schema v2.

### Evidence

- `preflight [--repo ...] [--remote R] [--base B] --preview`, then the same call with `--confirm-preview TOKEN [--accept-evidence-refresh]` — preview commits no task state, computes no complete worktree fingerprint, and returns the exact source/target decision, Chinese remaining workflow, lightweight observation, and token. Confirm the reported edge when `changes_status` is true; confirm captures the complete fingerprint and records the evidence. Decision drift returns `PREFLIGHT_PREVIEW_STALE`, requiring a new preview and state-edge confirmation. Observation-only drift returns `PREFLIGHT_EVIDENCE_REFRESH_REQUIRED` with current evidence and a reusable token; inspect it, obtain explicit acceptance, and retry that same token with `--accept-evidence-refresh`. `--repo` defaults to every repository and accepts an id or a path. A selected-repository pair may record evidence but never changes status; a final all-repository preview/confirm pair captures every repository and is required for any preflight status transition. Once a task is `PREFLIGHTED`, preflight refreshes must also cover all repositories.
- `baseline [--fetch] [--materialize]` — every call, including bare `baseline` and `--materialize` without a fetch, requires a current `baseline-fetch` approval. `--fetch` performs the constrained helper-free network fetch and additionally requires that approval to carry `--allow-fetch`; an approved dirty preflight likewise requires `--allow-dirty`. `--materialize` creates or reuses the detached analysis worktree at the pinned `base_sha`.
- `record-index [--role baseline|workspace] [--repo ...] [--commit SHA] [--index-id ID] [--receipt FILE] [--metadata-json JSON]` — `--role` defaults to `baseline`. Baseline indexes are recorded in `BASELINED`/`INDEXED`; workspace indexes are recorded in `WORKSPACE_READY`/`PLANNING`/`IMPLEMENTING`/`VERIFYING`. `--commit` defaults to the pinned base for a baseline index and current `HEAD` for a workspace index. For the baseline role only, omitting `--index-id` requires an `impact-degraded` approval and failure provenance in the metadata. A workspace index requires a successful non-empty `--index-id` and explicit `persistence:false`.
- `record-artifact --path FILE_OR_DIR --kind KIND [--verdict PASS|CONDITIONAL|FAIL] [--metadata-json JSON]` — `--artifact` is an accepted alias for `--path`. Recognized kinds bind to a phase: `impact` (in `INDEXED`/`IMPACT_REVIEW`, and recording one clears any route approval), `direct-contract`/`openspec-plan` (in `PLANNING`), and `review-report` (in `REVIEWING`, where `--verdict` is required and must match the report's own `Verdict:` line). `workspace-plan` and `review-snapshot` are controller-generated and rejected here with `RESERVED_ARTIFACT_KIND`; other kinds are recorded as free-form evidence.
- `record-test --name NAME --command CMD --exit-code N [--repo ...] [--output FILE]` — the command string is recorded, never executed. The record binds the current plan (full) or lite approval and the repository fingerprints at recording time, so any later edit invalidates it. Complete fingerprints are stored once per task under `artifacts/fingerprints/<fingerprint-sha256>.json`; state keeps validated compact references and the response is a compact receipt.
- `review-snapshot [--repo ...]` — `--repo` must cover every repository in the task. It reuses the same task-local fingerprint blobs and returns a compact receipt naming the manifest rather than inlining the complete snapshot.

### Decisions and movement

- `set-route direct|openspec --reason "..."` — the route may also be given as `--route`.
- `approve --gate GATE --note "..." [--artifact-sha256 SHA] [--accept-conditional] [--allow-fetch] [--allow-dirty]` — gates are `baseline-fetch`, `impact-degraded`, `route`, `workspace`, `plan` and `review` on a full task, and `lite` on a lite task. Evidence-bound gates require `--artifact-sha256` naming an artifact already recorded on the task. `--accept-conditional` applies only to `review`, `--allow-fetch` only to `baseline-fetch`, and `--allow-dirty` only to `baseline-fetch` and `lite`; using one elsewhere is an `INVALID_ARGUMENT`. A `FAIL` review verdict cannot be approved at all.
- `transition STATE [--note "..."] [--preview | --confirm-intent INTENT]` — the target may also be given as `--to`. Allowed edges are the flow's next state, its rework edges (back to `PLANNING`, `IMPLEMENTING`, or `INDEXED` for a full task; back to `IMPLEMENTING` or `PREFLIGHTED` for a lite one), and `BLOCKED`/`CANCELLED`. `--note` is required for `BLOCKED`, `CANCELLED`, replanning and impact reassessment. On schema-v2 tasks, every edge outside the exact automatic whitelist first uses `--preview`, then applies the unchanged returned intent with `--confirm-intent`; `DONE` and `CANCELLED` are always explicit. A blocked task may only resume to the state it was blocked from, except that a `lite-risk` block must be cancelled/replaced rather than resumed. Each transition re-verifies the guards and live evidence for its target, so drifted worktrees, missing workspace indexes, stale reviews and non-current test records all fail closed here.
- `prepare-workspace [--repo ...] [--branch B] [--path P] [--workspace-path REPO=PATH ...] [--workspace-branch REPO=BRANCH ...] [--dry-run | --execute]` — `--dry-run` is the default and records a deterministic `workspace-plan` artifact; `--execute` performs exactly the latest plan that carries a `workspace` approval. `--path` is only valid with a single selected repository; use the repeatable `REPO=...` overrides otherwise. Branches default to `codex/<task-id>`.
- `cancel --reason "..." [--preview | --confirm-intent INTENT]` — the preferred way to end a non-terminal task. Schema-v2 cancellation always uses preview followed by the exact confirmed intent; schema-v1 tasks retain the legacy direct command after a human prompt. A `DONE` task cannot be cancelled.

## Lite flow

The directory scope decides *where* the plugin is active; the flow decides *how much* pipeline a task inside that scope pays for. A lite task's state machine is `INTAKE -> PREFLIGHTED -> IMPLEMENTING -> VERIFYING -> DONE`:

Platform-neutral argv form:

```text
<python> <plugin-root>/scripts/dev_flow.py start --data-dir <PLUGIN_DATA> --workspace-strategy in-place --change-category internal --target-path src/component.py --requirement "fix ..." --repo <path>
```

- The workspace strategy is chosen at `start`, uniquely derives the immutable flow, and is itself immutable like the requirement and repository set. Lite records either the current branch (`in-place`) or a branch explicitly created/switched before start (`branch`); neither may switch branches after the task begins. It also stores the normalized low-risk category/target declaration and the exact protected-policy snapshot.
- The lite gate (`approve --gate lite`) replaces all six full-flow gates (`baseline-fetch`, `impact-degraded`, `route`, `workspace`, `plan`, and `review`) with one explicit decision: work in place on the exact recorded checkouts. It binds each repository's branch, `HEAD`, and working-tree fingerprint; every new `preflight` clears it, and entering implementation re-verifies all three live.
- Full-only commands (`baseline`, `record-index`, `set-route`, `prepare-workspace`, and `review-snapshot`) and all six full-flow gates fail with `FLOW_MISMATCH` on a lite task, and the lite gate fails the same way on a full task.
- Test records bind the current lite approval instead of a plan hash. Each repository still needs a current passing result whose fingerprint matches the final tree before `DONE`.
- Before entering `VERIFYING` or `DONE`, schema-v2 reclassifies every live path changed since the approved preflight `HEAD`, including committed, staged, unstaged, and untracked paths. A protected path, a change outside the declared targets, or unreadable/ambiguous evidence makes read-only `--preview` report `required_flow: full`; any actual attempt to apply that advance persists `BLOCKED` with `blocked.phase: lite-risk` and `required_flow: full`. The checkout is left untouched. Explicitly preview/confirm cancellation and create a replacement worktree/full task; the flow is never changed in place.
- Lite `IMPLEMENTING -> VERIFYING` is the only automatic lite transition. `PREFLIGHTED -> IMPLEMENTING`, rework, `DONE`, and `CANCELLED` require the schema-v2 intent protocol.
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
├── .github/workflows/
│   └── cross-platform.yml            # Native Windows/macOS/Linux validation matrix
├── .codex-plugin/plugin.json        # Required plugin manifest
├── INSTALL.md                        # Exact personal/repository placement map
├── hooks/
│   ├── hooks.json                   # Paired POSIX/Windows hook registration
│   ├── dev_flow_hook.cmd            # Native Windows launcher shim
│   └── dev_flow_hook.py             # Shared state injection and guardrails
├── scripts/
│   ├── dev_flow.py                  # Stable CLI facade and ordered runtime loader
│   ├── dev_flow_parts/              # Ten inseparable controller implementation parts
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
└── tests/                            # Portable offline unit tests
```

Do not copy the hook or helper scripts into each business repository. Install the whole plugin directory as one unit. In each target repository, maintain project-specific `AGENTS.md` guidance yourself and let `openspec init`/`openspec update` generate the current Codex OpenSpec skills when that route is selected.

## Development validation

Run these from the plugin source root. Each is a single argv sequence suitable for Bash, PowerShell, or Command Prompt; replace `<python>` with the actual command or absolute path of a supported interpreter:

```text
<python> -m unittest discover -s tests -v
<python> scripts/audit_runtime_imports.py
<python> scripts/validate_package.py
<python> scripts/run_bundled_validators.py --require-available
openspec validate complete-cross-platform-support --strict
```

These checks cover, in order, the complete unit suite; standard-library-only runtime and isolated startup; the plugin manifest, official default `hooks/hooks.json` discovery, and package references; the official validators for all three bundled skills and the plugin manifest; and strict OpenSpec change validation. `scripts/audit_runtime_imports.py` parses every shipped runtime import and starts the controller, hook, and Windows native runner with isolated `-I -S`. `scripts/validate_package.py` independently validates the default hooks because `.codex-plugin/plugin.json` must omit the unsupported `hooks` field.

`scripts/run_bundled_validators.py` records candidate digests before and after the validation and tries to discover the official skill/plugin validators from Codex home. Required CI materializes both official scripts from a pinned `openai/codex` commit, verifies their Git blob IDs and SHA-256 digests, and fails closed with `--require-available`. If the scripts or their dependencies are unavailable locally, a diagnostic run without the strict flag emits JSON `status: "unavailable"` so the other checks can continue, but that is **not** an official-validator pass. Final handoff must run where the validators are actually available:

```text
<python> scripts/run_bundled_validators.py --require-available
```

Use `DEV_FLOW_SKILL_VALIDATOR`, `DEV_FLOW_PLUGIN_VALIDATOR`, and, when needed, `DEV_FLOW_VALIDATOR_PYTHON` to locate them explicitly. `--require-available` turns every `unavailable` result into a failure, so a handoff cannot substitute the default soft diagnostic for a real pass.

Every required CI job runs the same complete suite with real Git on its exact checked-out `github.sha`: Python 3.9 and 3.14 on native Windows, macOS, and Linux, plus 3.10–3.13 on Linux. Simulating Windows branches or merely launching `commandWindows` is not enough to claim complete Windows plugin support. Before release, install the candidate from a confirmed local marketplace on an actual Windows Codex host and start a new task. The source/install path must cover spaces, Unicode, `&`, and parentheses; record default `hooks/hooks.json` discovery, `commandWindows` selection, real `PLUGIN_ROOT`/`PLUGIN_DATA` injection, bootstrap/checkpoint pickup, a benign command allowed, and a protected Git mutation rejected. Without that smoke evidence, Windows support is not fully validated.

### Cross-host Windows native self-test

The cross-host subject is `dev-flow-canonical-v1`, not the host-local snapshot digest. Canonical v1 hashes the explicit package allowlist by exact UTF-8 POSIX path and raw file bytes, ignores timestamps/ownership/executable modes, excludes OpenSpec progress only, rejects unexpected paths and links/reparse points, and asserts the published two-file golden vector. `scripts/run_bundled_validators.py` reports both `canonical_candidate_sha256` and the separate mode-sensitive `host_local_snapshot_sha256`; only the canonical value is compared across hosts.

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

Return the new `windows-native-report.json` unchanged for review. A valid report must bind the expected and observed canonical digest, show legacy-code-page and UNC/long-path/worktree checks as `passed`, and show cleanup `passed`. macOS/Linux can test preparation and fail-closed logic but can never emit native `passed`.

This project-local self-test is distinct from the real Windows Codex-host pickup smoke below. Running it authorizes neither publication/native CI dispatch nor marketplace installation. Those remain separate explicit approvals. For an authorized release dispatch, `.github/workflows/cross-platform.yml` requires the reviewed canonical digest and every Windows/macOS/Linux matrix job validates its lowercase format, asserts the golden vector, and fails on a local digest mismatch; ordinary push/pull-request checks are not release authorization.

Command execution in CI is not enough to claim Codex integration on Windows. Before publishing Windows support, install the cache-busted candidate from the confirmed local marketplace on an actual Windows Codex host, start a new task, prove default `hooks/hooks.json` discovery and `commandWindows` selection, observe real `PLUGIN_ROOT`/`PLUGIN_DATA`, and round-trip an installed path containing spaces, Unicode, `&`, and parentheses. Record bootstrap/checkpoint pickup, a benign command allowed, and a protected Git mutation rejected against the same candidate digest. Without this real-host smoke evidence, do not claim that Windows support has completed validation.

## Installation placement

See [`INSTALL.md`](INSTALL.md) for the complete package placement map, the runtime data layout under `<PLUGIN_DATA>`, and the update procedure for an already-installed copy. For personal use, place this complete directory at the plugin location referenced by your personal marketplace entry. For a repository marketplace, place it at `<marketplace-root>/plugins/dev-flow-orchestrator/` and point that marketplace entry to `./plugins/dev-flow-orchestrator`.

After installing or updating the plugin, start a new Codex task so the new skills and hooks are loaded. Review and trust the bundled hooks when Codex asks. Active task state remains local to the host on which it was created; reinstalling the plugin does not authorize copying an in-flight state directory to another operating system.
