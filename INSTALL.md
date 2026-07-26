# Installation and file placement

Dev Flow Orchestrator supports native Windows, macOS, and Linux with Python 3.9 through 3.14 and a real Git installation with `git worktree` support. Keep the plugin directory intact; paths below are relative to the plugin root unless an absolute destination is shown.

Use these placeholders:

| Placeholder | Meaning |
|---|---|
| `<python>` | Absolute path to a supported Python 3.9–3.14 interpreter |
| `<validator-python>` | Python interpreter that can import the official Codex validator dependencies |
| `<plugin-root>` | Complete installed `dev-flow-orchestrator` directory |
| `<PLUGIN_DATA>` | Host-local private state directory injected by Codex or selected explicitly |

## Plugin files

| Source | Destination | Purpose |
|---|---|---|
| `.gitattributes` | `<plugin-root>/.gitattributes` | Canonical LF checkout and handoff byte policy |
| `.codex-plugin/plugin.json` | `<plugin-root>/.codex-plugin/plugin.json` | Required plugin manifest; deliberately omits unsupported `hooks` |
| `.gitignore` | `<plugin-root>/.gitignore` | Excludes local Python/test by-products |
| `LICENSE` | `<plugin-root>/LICENSE` | License |
| `README.md` | `<plugin-root>/README.md` | English architecture, setup, and validation contract |
| `README.zh-CN.md` | `<plugin-root>/README.zh-CN.md` | Chinese architecture, setup, and validation contract |
| `INSTALL.md` | `<plugin-root>/INSTALL.md` | This installation and placement guide |
| `hooks/hooks.json` | `<plugin-root>/hooks/hooks.json` | Official default hook discovery with paired platform commands |
| `hooks/dev_flow_hook.cmd` | `<plugin-root>/hooks/dev_flow_hook.cmd` | Native Windows launcher shim |
| `hooks/dev_flow_hook.py` | `<plugin-root>/hooks/dev_flow_hook.py` | Shared resume context and fail-open guardrails |
| `scripts/dev_flow.py` | `<plugin-root>/scripts/dev_flow.py` | Stable controller CLI facade and ordered runtime loader |
| `scripts/dev_flow_parts/` | `<plugin-root>/scripts/dev_flow_parts/` | Complete, inseparable controller implementation bundle |
| `scripts/__init__.py` | `<plugin-root>/scripts/__init__.py` | Import boundary for controller helpers |
| `scripts/audit_runtime_imports.py` | `<plugin-root>/scripts/audit_runtime_imports.py` | Standard-library import and isolated-startup audit |
| `scripts/candidate_identity.py` | `<plugin-root>/scripts/candidate_identity.py` | Shared canonical-v1 identity and deterministic handoff implementation |
| `scripts/validate_package.py` | `<plugin-root>/scripts/validate_package.py` | Manifest/default-hook/inventory/reference validator |
| `scripts/run_bundled_validators.py` | `<plugin-root>/scripts/run_bundled_validators.py` | Exact-snapshot diagnostics and official validator runner |
| `scripts/windows_native_validation.py` | `<plugin-root>/scripts/windows_native_validation.py` | Canonical-bound native Windows self-test |
| `scripts/windows_native_validation.cmd` | `<plugin-root>/scripts/windows_native_validation.cmd` | Windows launcher for the native self-test |
| `skills/follow-dev-flow/` | `<plugin-root>/skills/follow-dev-flow/` | Main workflow skill, UI metadata, references, and direct-contract asset |
| `skills/analyze-change-impact/` | `<plugin-root>/skills/analyze-change-impact/` | Impact-analysis skill, UI metadata, reference, and report asset |
| `skills/review-dev-flow-change/` | `<plugin-root>/skills/review-dev-flow-change/` | Independent-review skill, UI metadata, and reference |
| `templates/marketplace-entry.json` | Keep in place; merge its object into a marketplace's `plugins[]` | Local plugin catalog entry |
| `templates/personal-marketplace.example.json` | Keep in place; copy only when the default personal marketplace does not exist | Complete first personal marketplace |
| `tests/` | `<plugin-root>/tests/` | Complete offline regression suite, including shared fixtures and split controller, hook, packaging, platform, mutation, and candidate-identity tests |
| `.github/workflows/cross-platform.yml` | `<plugin-root>/.github/workflows/cross-platform.yml` | Native OS/Python validation matrix |

Do not move individual skill references, assets, or `agents/openai.yaml` files out of their skill directories. Their relative links are intentional. The package does not ship a project `AGENTS.md` template; maintain project-specific guidance in each business repository.

## Recommended personal installation

Use this layout when the workflow should be available across projects:

```text
<user-home>/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
    ├── .codex-plugin/plugin.json
    ├── hooks/
    ├── scripts/
    ├── skills/
    ├── templates/
    └── tests/
```

Copy the complete plugin root to the shown plugin directory. If the default personal marketplace does not exist, use `templates/personal-marketplace.example.json` as its initial contents. If it already exists, merge only the object in `templates/marketplace-entry.json` into its `plugins` array and preserve its name, interface metadata, ordering, and existing entries. Do not copy a marketplace example over an existing catalog.

Restart the desktop app, install the plugin from that confirmed marketplace, and start a new Codex task so the current skills and hooks are loaded.

### Hook launch contract

Codex discovers `hooks/hooks.json` by convention; `.codex-plugin/plugin.json` must continue to omit a `hooks` field. Every bundled handler has:

- `command` for macOS/Linux, using quoted `$PLUGIN_ROOT` and the shared Python handler;
- `commandWindows` for native Windows, invoking `hooks/dev_flow_hook.cmd` through quoted `%PLUGIN_ROOT%`.

The Windows shim probes `py -3`, then explicit `py -3.14` through `py -3.9`, and finally `python`; it preserves stdin/stdout and exit status and invokes the same `hooks/dev_flow_hook.py`. If no launcher supplies Python 3.9–3.14, it emits a diagnostic and performs no mutation. A global hook gets neither `PLUGIN_ROOT` nor `PLUGIN_DATA`; configure both `command` and `commandWindows` there with a verified absolute interpreter, absolute hook path, and explicit `--data-dir`.

### Limit the plugin to specific directories

Take `<python>`, the controller path, and `<PLUGIN_DATA>` from the injected bootstrap context. Preserve those exact argument values.

macOS/Linux Bash:

```bash
"<python>" "<plugin-root>/scripts/dev_flow.py" scope --data-dir "<PLUGIN_DATA>" --add "$HOME/work"
```

Windows PowerShell:

```powershell
& "<python>" "<plugin-root>\scripts\dev_flow.py" scope --data-dir "<PLUGIN_DATA>" --add "D:\projects"
```

Windows Command Prompt:

```bat
"<python>" "<plugin-root>\scripts\dev_flow.py" scope --data-dir "<PLUGIN_DATA>" --add "D:\projects"
```

The first `--add` changes the scope from active everywhere to allowlist mode. Verify with `scope --check <directory>` and reverse with `scope --clear`. Outside the scope, hooks emit nothing and `start` rejects the repository.

### Update an installed local copy

Do not hand-edit a marketplace entry to defeat caching, and do not stack cachebuster suffixes. After replacing the complete source at the marketplace's confirmed local plugin location, use the bundled `plugin-creator` helpers from their own skill root. The helper preserves the manifest's current base version (`0.3.0` for this candidate) and replaces any old `+codex.<token>` with one UTC timestamp.

macOS/Linux Bash:

```bash
"<validator-python>" "<plugin-creator-skill-root>/scripts/update_plugin_cachebuster.py" "<plugin-root>"
"<validator-python>" "<plugin-creator-skill-root>/scripts/read_marketplace_name.py"
codex plugin add "dev-flow-orchestrator@<marketplace-name-printed-above>"
```

Windows PowerShell:

```powershell
& "<validator-python>" "<plugin-creator-skill-root>\scripts\update_plugin_cachebuster.py" "<plugin-root>"
& "<validator-python>" "<plugin-creator-skill-root>\scripts\read_marketplace_name.py"
codex plugin add "dev-flow-orchestrator@<marketplace-name-printed-above>"
```

Windows Command Prompt:

```bat
"<validator-python>" "<plugin-creator-skill-root>\scripts\update_plugin_cachebuster.py" "<plugin-root>"
"<validator-python>" "<plugin-creator-skill-root>\scripts\read_marketplace_name.py"
codex plugin add "dev-flow-orchestrator@<marketplace-name-printed-above>"
```

The no-argument marketplace-name helper reads the default personal marketplace. Do not run `codex plugin marketplace add` for that default location. For a different confirmed local marketplace, pass its path to `read_marketplace_name.py` as documented by `plugin-creator`, ensure it is configured, and reinstall using the exact printed name. Start a new Codex task after reinstall.

### Upgrade existing tasks

State schema version 1 remains readable when its task ID is portable. The current evidence contract version is `2`: legacy v1 preflight, fingerprint, baseline/workspace index, test, or review evidence does not satisfy the current contract/profile digest and must be regenerated by the current controller before its next downstream gate. A task already beyond a state where the controller permits the required evidence refresh cannot be migrated in place; cancel and replace it instead of editing evidence. Loading a legacy state that contains recognized sensitive values may perform a locked, one-time redaction rewrite, including when first loaded by `show` or `list`; this cleanup adds no workflow event. A legacy `branch`-strategy task without its start-time `branch_binding` is inspectable but deliberately fails closed at preflight and lite gates; cancel and replace it rather than synthesizing that approval evidence. Do not relabel old evidence or reuse a baseline codebase-memory project as a workspace project.

An existing task already bound to an immutable review chain may finish only where the controller explicitly accepts that chain. If planning or implementation resumes, use the supported reassessment/replanning transitions, refresh the current-generation workspace indexes, tests, and review snapshot, and repeat the relevant approvals.

Active tasks and `<PLUGIN_DATA>` are host-local. Do not move or synchronize live state, locks, quarantine records, analysis worktrees, or linked implementation worktrees between Windows, macOS, and Linux. Finish or cancel on the originating host and start a new task on the destination host.

## Repository-scoped alternative

For a shared marketplace rooted at `<marketplace-root>`:

```text
<marketplace-root>/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

The same marketplace entry works because its source path is relative to `<marketplace-root>`. Use this placement only when the repository or team owns the plugin catalog.

## Files in each business repository

- Keep project-specific guidance in the repository's existing `AGENTS.md`; no such template is shipped by this plugin.
- Do not copy plugin hooks, controller, package validators, or state files into the business repository.
- Do not copy a fixed OpenSpec workflow. Run the installed OpenSpec initialization/update command and use its current `.codex/skills/openspec-*` guidance. For human-readable OpenSpec artifacts, honor an explicit user language choice; otherwise follow the dominant language of the repository's existing OpenSpec artifacts, then its other human-readable artifacts. Stop and ask when those signals conflict or remain unclear, and preserve machine-required identifiers and fixed syntax tokens in every language.
- Keep the existing user- or project-scoped codebase-memory configuration. The plugin intentionally has no machine-specific `.mcp.json`.

## Runtime data and permissions

The controller resolves its data root in this order: non-empty `--data-dir`, `DEV_FLOW_DATA_DIR`, `PLUGIN_DATA`, then the native per-user default:

- Windows: `%LOCALAPPDATA%\dev-flow-orchestrator`, with a home-based local-app-data fallback;
- macOS: `~/Library/Application Support/dev-flow-orchestrator`;
- Linux: `$XDG_STATE_HOME/dev-flow-orchestrator`, or `~/.local/state/dev-flow-orchestrator`.

Whitespace-only values are unset; they never select the current directory. The controller creates runtime-only paths such as:

```text
<PLUGIN_DATA>/
├── config.json
├── config.lock
├── workspace-registry.json
├── workspace-registry.lock
├── tasks/<task-id>/state.json
├── tasks/<task-id>/state.lock
├── tasks/<task-id>/events.jsonl
├── tasks/<task-id>/mutation-quarantine.json
├── tasks/<task-id>/artifacts/
├── tasks/<task-id>/workspace-plans/
├── tasks/<task-id>/reviews/
├── analysis/<task-id>/<repository-id>/
└── workspaces/<task-id>/<repository-id>/
```

On POSIX, controller-owned directories are mode `0700` and state/configuration/event/lock/receipt/temporary files are `0600`. On Windows, standard-library Win32 bindings verify the actual owner and inherited DACL and block a mutation if the descriptor is null, unreadable, unexpectedly owned, or broadly writable. POSIX modes are never presented as Windows ACL proof.

Do not hand-edit runtime data. If a Git-changing child cannot be proven quiescent, the controller writes durable quarantine evidence and blocks further mutations. Inspect the task/process/repository state and use `recover-quarantine --expected-revision <revision>`; recovery proves the child is gone, validates postconditions, and archives the quarantine. Never delete the file or retry the mutation as a shortcut.

An atomic state write that is killed before its cleanup leaves a `.<name>.rollback-<suffix>` file next to the destination, and later writes to that file fail with `ATOMIC_RECOVERY_REQUIRED`. Use `recover-atomic-write` to report the candidates and `--apply` to clear the provably safe ones; differing content requires an explicit `--resolve` decision. Deleting the file yourself is not the supported recovery.

## Release validation

Run from the exact candidate root. Each native CI job records `github.sha`, Git `HEAD`, worktree cleanliness, OS, Python, and a before/after package SHA-256.

macOS/Linux Bash:

```bash
"<python>" -m unittest discover -s tests -v
"<python>" scripts/audit_runtime_imports.py
"<python>" scripts/validate_package.py
"<validator-python>" scripts/run_bundled_validators.py --require-available
openspec validate complete-cross-platform-support --strict
```

Windows PowerShell:

```powershell
& "<python>" -m unittest discover -s tests -v
& "<python>" "scripts\audit_runtime_imports.py"
& "<python>" "scripts\validate_package.py"
& "<validator-python>" "scripts\run_bundled_validators.py" --require-available
openspec validate complete-cross-platform-support --strict
```

Windows Command Prompt:

```bat
"<python>" -m unittest discover -s tests -v
"<python>" "scripts\audit_runtime_imports.py"
"<python>" "scripts\validate_package.py"
"<validator-python>" "scripts\run_bundled_validators.py" --require-available
openspec validate complete-cross-platform-support --strict
```

`run_bundled_validators.py` auto-discovers official validators under `CODEX_HOME` or accepts `DEV_FLOW_SKILL_VALIDATOR`, `DEV_FLOW_PLUGIN_VALIDATOR`, and `DEV_FLOW_VALIDATOR_PYTHON`. Without `--require-available`, a missing bundle/dependency is reported as `unavailable` so ordinary local development remains diagnosable. Required CI materializes the two official scripts from a pinned `openai/codex` commit, verifies their Git blob IDs and SHA-256 digests, and uses the strict flag; release handoff must likewise provide the real bundled validators and use the strict flag.

### Project-local Windows self-test handoff

`scripts/run_bundled_validators.py` reports two identities: cross-host `canonical_candidate_sha256` and mode-sensitive, host-only `host_local_snapshot_sha256`. Freeze every canonical input first, including `.gitattributes`, implementation, tests, workflow, documentation, manifest/cachebuster, then create new outputs outside the candidate:

macOS/Linux Bash:

```bash
mkdir -p "$HOME/dev-flow-windows-handoff"
"<python>" scripts/windows_native_validation.py prepare --candidate-root . --archive "$HOME/dev-flow-windows-handoff/dev-flow-candidate.zip" --manifest "$HOME/dev-flow-windows-handoff/dev-flow-candidate.json"
```

Transfer both files byte-for-byte and retain the printed `candidate_sha256`. On Windows, provide an existing writable child directory through a local path and an existing UNC alias to the same backing directory; do not pass a drive or share root. The runner does not manage the share.

Windows PowerShell:

```powershell
& ".\scripts\windows_native_validation.cmd" run --archive "C:\dev-flow-windows-handoff\dev-flow-candidate.zip" --manifest "C:\dev-flow-windows-handoff\dev-flow-candidate.json" --expected-canonical "<canonical-sha256-from-prepare>" --local-root "C:\dev-flow-share-parent\test-root" --unc-root "\\localhost\DevFlowNative\test-root" --code-page 936 --report "C:\dev-flow-windows-handoff\windows-native-report.json"
```

Windows Command Prompt:

```bat
scripts\windows_native_validation.cmd run --archive "C:\dev-flow-windows-handoff\dev-flow-candidate.zip" --manifest "C:\dev-flow-windows-handoff\dev-flow-candidate.json" --expected-canonical "<canonical-sha256-from-prepare>" --local-root "C:\dev-flow-share-parent\test-root" --unc-root "\\localhost\DevFlowNative\test-root" --code-page 936 --report "C:\dev-flow-windows-handoff\windows-native-report.json"
```

The report parent must already exist, the report must be new and outside the candidate/test roots, and code page `936` may be replaced only with another installed non-UTF-8 page. Return `windows-native-report.json` unchanged. The runner verifies/extracts the handoff without `extractall`, uses one sentinel-owned child, isolated controller data and repository-local Git config, and refuses unsafe cleanup. It never installs/publishes/pushes, manages a share, changes persistent code-page or machine/global Git state, reuses live plugin data, or overwrites a report. A non-Windows run is always `incomplete`.

This self-test proves native code-page and UNC/long-path/worktree behavior for the canonical candidate. It is not the Windows Codex-host pickup smoke and grants no publication, workflow-dispatch, marketplace, or installation authorization. An authorized release dispatch separately supplies this reviewed lowercase canonical digest to the already-frozen `.github/workflows/cross-platform.yml`, where every matrix job asserts the golden vector and exact digest.

Before a release claims Windows support, an actual Windows Codex host must install the cache-busted candidate from the confirmed local marketplace, start a new task, prove default `hooks/hooks.json` discovery and `commandWindows` selection, observe real `PLUGIN_ROOT`/`PLUGIN_DATA`, and round-trip a plugin location containing spaces, Unicode, and command-shell metacharacters. Record the result against the same candidate digest; CI command tests alone are not this integration evidence.
