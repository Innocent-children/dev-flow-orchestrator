## Context

The prerequisite runtime change leaves a deliberately small release gap.

| Product surface | Current implementation | Remaining Windows gap |
| --- | --- | --- |
| Hook configuration | `hooks/hooks.json` defines only `command` values using `$PLUGIN_ROOT` and the POSIX launcher | Installed command Hooks have no Windows override |
| Public Hook bootstrap | `hooks/dev_flow_hook.py` passes `scripts/dev_flow_python_launcher` as the Controller launcher | Windows needs the `.cmd` launcher |
| Hook locator | `src/dev_flow_orchestrator/hook.py` uses POSIX `shlex.join` and POSIX token inspection | Injected commands are not copyable PowerShell commands |
| Installer | `scripts/install.sh` implements authoritative clone/update, candidate validation, marketplace registration, plugin activation, and receipts, then rejects non-macOS hosts | Windows has no native entry point |
| Uninstaller | `scripts/uninstall.sh` conservatively removes plugin, marketplace entry, and a validated clean source checkout, then rejects non-macOS hosts | Windows has no native entry point |
| Web UI | The standard-library server already uses Controller storage, sockets, and the runtime Git cancellation path | It needs Windows installed smoke evidence, not a second implementation |
| Package validator | Required assets and host smoke are centered on POSIX launch and macOS installer behavior | Windows assets and host-specific execution gates are absent |
| Public guidance | README and INSTALL advertise macOS only | Windows support and commands are not documented |

The OpenAI Hook contract has also been checked against the current official documentation:

- `commandWindows` is the supported Windows-only command override;
- plugin commands receive `PLUGIN_ROOT` and `PLUGIN_DATA`;
- installing a plugin does not automatically trust its command Hooks;
- changed Hook definitions are skipped until reviewed and trusted through `/hooks`;
- Windows shell calls still use the `Bash` Hook tool path; and
- tool Hooks are useful guardrails rather than complete enforcement boundaries.

Reference: <https://developers.openai.com/codex/hooks>

GitHub-hosted `windows-latest` is a Windows Server automation image, so it is suitable for implementation tests but is not evidence for the public consumer-client support claim. Client release evidence remains separate.

Reference: <https://github.com/actions/runner-images>

## Goals

1. Make the installed plugin usable in native Codex sessions on documented Windows x64 clients.
2. Preserve the current macOS commands and behavior.
3. Keep Hook differences limited to launch, command rendering, and practical path inspection.
4. Apply the existing installation authority rules to a PowerShell entry point.
5. Validate the existing Web UI rather than reimplementing it.
6. Add enough automated and client evidence to make an honest public Windows support claim.
7. Keep the change understandable: one new launcher, two lifecycle scripts, small Hook branches, and proportional tests.

## Non-goals

- replacing or redesigning `add-native-windows-runtime`;
- implementing Windows ARM64, 32-bit, Server, WSL, network-path, or uncommon-filesystem support;
- creating a generic command-dialect framework;
- parsing arbitrary PowerShell expressions or proving the Hook cannot be bypassed;
- changing controller data permissions or Codex sandbox ACLs;
- building MSI, MSIX, winget, Chocolatey, Scoop, or background update delivery;
- opening a browser automatically;
- migrating historical tasks or transferring live tasks between macOS and Windows;
- duplicating the complete workflow and assurance validation matrix on Windows.

## Decision 1: Treat this as release integration over one existing runtime

The change depends on the private path, storage, and process seams delivered by `add-native-windows-runtime`. Hook, installer, Web UI, and package tests call the same public Controller and CLI used on macOS.

No second Windows platform package is introduced. If an installed journey exposes a path, lock, process, or snapshot defect, the fix goes into the existing runtime seam and receives one focused regression test.

This keeps the product graph simple:

```text
same product core
├── POSIX runtime primitives
└── Windows runtime primitives
        ↓
same CLI / Hook / workflows / Web UI / Dossier
```

## Decision 2: Add one native Hook command and one `.cmd` launcher

### Hook configuration

Every existing command Hook retains its current `command` and gains `commandWindows`. The Windows override invokes the installed launcher and Hook bootstrap through `%PLUGIN_ROOT%`:

```text
"%PLUGIN_ROOT%\scripts\dev_flow_python_launcher.cmd" "%PLUGIN_ROOT%\hooks\dev_flow_hook.py"
```

The exact outer quoting is validated by launching it through the same Windows command path used by Codex. The Hook event names, matchers, timeouts, status messages, stdin JSON, and stdout JSON remain unchanged.

### Launcher responsibilities

`scripts/dev_flow_python_launcher.cmd` remains a small bootstrap, not an installer or environment manager. It:

1. starts with `@echo off` and disabled delayed expansion;
2. requires a first argument naming an existing Python handler;
3. accepts `DEV_FLOW_PYTHON` only as a verified executable path override;
4. otherwise tries the Windows Python launcher (`py -3`) and ordinary `python.exe`/`python3.exe` commands;
5. verifies a supported 64-bit CPython version before use;
6. executes the selected interpreter with `-X utf8 -I -S` and the original quoted argument sequence;
7. returns the Python process exit code; and
8. emits a short ASCII diagnostic and nonzero status when no interpreter is usable.

The launcher is tested with an ordinary path, a path containing spaces, and one Unicode path. It does not promise every `cmd.exe` metacharacter combination.

### Public Hook bootstrap

`hooks/dev_flow_hook.py` chooses:

```text
scripts/dev_flow_python_launcher        on POSIX
scripts/dev_flow_python_launcher.cmd    on Windows
```

and continues to pass `scripts/dev_flow.py` as the Controller program. The fallback inside `src/dev_flow_orchestrator/hook.py` follows the same rule so direct tests and packaged execution agree.

## Decision 3: Render one PowerShell locator without building a command framework

The locator is a user-visible, copyable command. POSIX retains `shlex.join`. Windows uses a small local renderer:

```text
& '<launcher>' '<dev_flow.py>' --data-dir '<state-root>'
```

Each PowerShell literal is single-quoted and any embedded apostrophe is doubled. The `&` call operator is emitted exactly once. No environment variable or relative path is left for the user to reconstruct.

The renderer is a pair of private functions in `hook.py`, not a public command-dialect service. It has two real implementations and one call site.

### Exact Controller recognition

The PreToolUse guard recognizes only the product-rendered Controller prefix for the active host. On Windows it:

- compares against the exact rendered launcher, CLI, `--data-dir`, and state root;
- rejects carriage returns, newlines, backticks, command substitutions, statement separators, pipelines, and additional call operators in the suffix;
- permits ordinary Controller action names and arguments after the fixed prefix; and
- does not try to accept every semantically equivalent PowerShell spelling.

This is intentionally narrower than a PowerShell parser. The injected command is the supported spelling.

## Decision 4: Keep structured path protection strong and shell inspection modest

Structured tool arguments remain the reliable path boundary:

- `Write` and `Edit` inspect `file_path` or `path` directly;
- `apply_patch` extracts declared patch paths and compares them through the runtime host-path helper;
- relative paths are resolved against the Hook `cwd`;
- controller data equality or containment is denied before task inventory is loaded.

For Windows shell commands reported through the `Bash` Hook path, inspection is best effort. It checks:

- a literal normalized protected data-root spelling;
- `%PLUGIN_DATA%`;
- `$env:PLUGIN_DATA` and `${env:PLUGIN_DATA}`; and
- the exact Controller locator exception.

It does not interpret variables, aliases, functions, nested scripts, encoded commands, or general PowerShell syntax. Ambiguous shell commands remain fail-open, matching the existing Hook's role as a guardrail. Installation and documentation must not describe the Hook as an operating-system security boundary.

## Decision 5: Make Hook trust an explicit handoff

Codex stores trust against the exact current Hook definition. Adding `commandWindows` changes that definition, and plugin installation does not grant trust.

The Windows installer therefore reports two separate facts:

```text
plugin installed/repaired/upgraded
Hook review required: open /hooks in a new Codex session
```

It must not print `Hook active`, `Hook trusted`, or equivalent language unless a future supported Codex interface can actually prove that state. Automated tests validate the receipt text and Hook assets; one client smoke performs the real `/hooks` review and subsequent SessionStart execution.

## Decision 6: Implement a native PowerShell lifecycle without rewriting the macOS bootstrap

### Baseline

`scripts/install.ps1` and `scripts/uninstall.ps1` target Windows PowerShell 5.1 syntax and also run under PowerShell 7. They use:

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
```

External commands are invoked with the call operator and argument arrays. The scripts do not build an eval string, invoke WSL, or require Git Bash.

The current `.sh` scripts remain authoritative for macOS and are not rewritten merely to share code. Small pure helpers may be extracted only when they reduce existing duplicated JSON logic without moving clone/update authority into an unverified candidate.

### Host and prerequisite checks

The Windows installer verifies:

- it is running on Windows;
- the process and selected Python interpreter are 64-bit x64, not ARM64 or 32-bit;
- Git for Windows is available through `git`;
- Codex exposes `codex plugin`;
- Python is within the product's supported range; and
- the source and marketplace defaults resolve beneath the current user profile.

It does not attempt a broad Windows edition detector. Windows Server remains outside the documented support boundary even if the script happens to execute there.

### Defaults and overrides

The Windows lifecycle mirrors the existing environment controls:

```text
DEV_FLOW_REPOSITORY_URL
DEV_FLOW_SOURCE_ROOT
DEV_FLOW_MARKETPLACE_FILE
DEV_FLOW_PYTHON
CODEX_HOME
NO_COLOR
```

Default paths are:

```text
%USERPROFILE%\plugins\dev-flow-orchestrator
%USERPROFILE%\.agents\plugins\marketplace.json
%CODEX_HOME% or %USERPROFILE%\.codex
```

Path operations use PowerShell `-LiteralPath` or .NET APIs. External command paths and arguments are passed separately.

### Authoritative source lifecycle

The PowerShell installer implements the existing generic installation Requirements rather than a weaker Windows variant:

1. a fresh install clones attached branch `main` explicitly from the expected origin;
2. an existing path must be a Git checkout with the exact origin and attached `main`;
3. tracked and untracked status must be clean;
4. the installer fetches `refs/heads/main` explicitly;
5. equal commits proceed idempotently;
6. an installed ancestor may fast-forward with `--ff-only --no-overwrite-ignore`;
7. local-ahead and diverged histories fail without reset or merge;
8. final `HEAD` must equal the fetched commit and status must remain clean; and
9. package validation runs only after that verification.

The script never stashes, cleans, resets, switches branches, or silently replaces an existing non-checkout directory.

### Marketplace and plugin activation

After source verification and candidate validation:

- the marketplace path must still be `<marketplace-root>/.agents/plugins/marketplace.json`;
- the source must be inside the marketplace root;
- malformed JSON or a non-array `plugins` value fails without replacement;
- unrelated entries are preserved;
- all Dev Flow entries are replaced by exactly one local entry;
- the write uses a same-directory temporary file and atomic replacement through the selected Python interpreter or an equivalent .NET same-volume replacement;
- `codex plugin list --marketplace personal --json` determines absent/current/older state;
- an installed snapshot is removed before add, preserving the existing repair/upgrade semantics; and
- `codex plugin add dev-flow-orchestrator@personal` failure returns nonzero with manual recovery commands.

The receipt uses plain text by default and optional ANSI color only when the host supports it. Visual parity with the macOS receipt is desirable but not a release requirement.

## Decision 7: Keep uninstallation conservative

`scripts/uninstall.ps1` accepts:

```text
-KeepSource
-Help
```

It:

1. validates the marketplace before changing it;
2. inspects installed plugin state;
3. removes the plugin if installed;
4. removes only the Dev Flow marketplace entry;
5. preserves unrelated entries;
6. removes the source by default only after verifying it is a real Dev Flow checkout, has an allowed official origin, is attached to `main`, has no tracked, untracked, or ignored content, and has no local-only commits;
7. preserves source when `-KeepSource` is supplied; and
8. always preserves external controller task data.

A refusal to remove source does not authorize deleting an uncertain directory. The user receives the exact path and reason for manual handling.

The Windows parameter name follows PowerShell conventions. Documentation may also show `--keep-source` only if the implementation intentionally aliases it; the spec does not require two spellings.

## Decision 8: Reuse the existing Web UI unchanged unless smoke reveals a concrete bug

The Web UI already binds numeric loopback, emits a tokenized startup receipt, serves fixed read-only routes, separates stored inspection from live Git observation, and cancels Git capture during shutdown.

Windows release work verifies:

1. `dev-flow --data-dir <root> web --port 0` starts in the foreground;
2. the startup receipt is strict JSON and identifies the current whole product;
3. `/`, assets, `/api/meta`, inventory, stored detail, and one authenticated live detail respond through the existing contract;
4. live observation uses the Windows runtime process cancellation path;
5. Ctrl+C closes the listener and returns control; and
6. task and repository state remain unchanged by observation.

No Windows browser shell command, registry integration, tray process, daemon, or auto-launch feature is added.

## Decision 9: Validate assets and behavior proportionally

### Candidate validation

The package validator adds the following current-product assets:

```text
scripts/dev_flow_python_launcher.cmd
scripts/install.ps1
scripts/uninstall.ps1
Windows-focused tests
```

It also verifies that every packaged command Hook retains `command` and adds a non-empty `commandWindows`. Static validation remains host-neutral. Host execution is conditional:

- macOS runs the existing launcher and installer suite;
- Windows runs `.cmd`, PowerShell lifecycle, Hook, Web UI, and installed-smoke tests;
- neither host is required to execute the other host's shell language.

The validator's public result uses a neutral platform description rather than claiming the complete candidate is macOS-only.

### CI

The existing macOS focused job remains the broad product regression gate. The Windows job extends the prerequisite runtime checks with:

- `.cmd` launcher smoke;
- Hook rendering and guard tests;
- PowerShell installer/uninstaller behavior tests against isolated local Git remotes, marketplaces, and stub Codex executables;
- Web UI startup/live/shutdown smoke; and
- one installed product journey.

The GitHub-hosted runner is automation infrastructure, not public Windows Server support evidence.

### Installed evidence

One installed Windows journey is enough to prove the vertical product path:

```text
verified source
→ marketplace registration
→ plugin installation
→ Hook launch
→ one representative task lifecycle
→ assurance/Dossier completion
→ Web UI inspection
→ uninstall
```

A second, shorter smoke creates a two-member task and resumes/discovers it from the non-first member. Windows does not rerun all six workflow/profile journeys because those business rules are shared and remain covered by the main product suite.

### Consumer-client evidence

Before the public support claim:

- Windows 11 x64 records the complete installed journey;
- Windows 10 22H2 x64 records install, Hook launch, core task resume, Web UI startup, and uninstall;
- each record includes OS build, PowerShell, Python, Git, and Codex versions plus pass/fail outcome; and
- every reproducible defect found receives one targeted regression test.

## Decision 10: Publish a bounded support matrix without a platform fork

Public documents describe one product available on:

```text
macOS
Windows 10 22H2 x64 client
Windows 11 x64 client
```

Windows prerequisites are:

```text
64-bit supported CPython
Git for Windows
Codex plugin and Hook support
Windows PowerShell 5.1 or PowerShell 7 for lifecycle commands
ordinary local repositories
```

Public non-support statements include:

```text
Windows ARM64
32-bit Python
Windows Server
WSL execution
UNC/SMB/NAS and mapped network repositories
\\wsl$
cross-operating-system task transfer
historical task migration
```

The product keeps one `PRODUCT_VERSION`, plugin manifest, package, namespace, workflow catalog, and Web UI identity. No `Windows version` or compatibility line is introduced.

If the normal release process selects a new whole-product version before merge, all existing current-product assets move together and old namespaces remain inert under the project's no-migration policy. That release maintenance is not used to justify Windows-specific compatibility code in this change.

## Alternatives considered

### Split Hook, installer, and Web UI into separate changes

Rejected. They are independently testable, but none produces a complete user-installable Windows product alone. One release-integration change makes the final boundary easier to review and avoids more OpenSpec overhead.

### Rewrite both installers around one new lifecycle framework

Rejected for this change. The remote bootstrap must establish source authority before trusting candidate code, and rewriting the working macOS path would create avoidable regression risk. Shared helpers remain optional and small.

### Build a general shell command parser

Rejected. It would be large, incomplete, and inconsistent with the official description of tool Hooks as guardrails. Structured path inputs and one exact generated locator provide the useful protection.

### Automate Hook trust

Rejected. Current Codex requires review and trust of the exact non-managed Hook definition. The installer provides an honest handoff rather than bypassing or fabricating trust.

### Use Windows client self-hosted CI for every pull request

Rejected as a default requirement. GitHub-hosted Windows automation plus pre-release Windows client evidence gives a practical maintenance burden. A self-hosted client runner may be added later if release frequency justifies it.

## Complexity check

Expected new production surfaces are limited to:

```text
1 .cmd launcher
2 PowerShell lifecycle scripts
small host branches in Hook rendering/bootstrap
small validator and documentation updates
```

The change does not duplicate Controller, workflow, assurance, Web UI, or persisted-model code. It does not rewrite Python subprocess or storage primitives. Most new lines correspond directly to user-visible installation and Hook support; release checks remain representative rather than exhaustive.
