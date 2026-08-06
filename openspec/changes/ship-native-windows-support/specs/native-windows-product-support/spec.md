## Purpose

Define the installed native Windows client experience layered over the existing Windows runtime while preserving one Dev Flow product, one Hook contract, and one bounded support statement.

## ADDED Requirements

### Requirement: The installed plugin launches its current Hook natively on supported Windows clients

Every packaged command Hook SHALL retain its existing POSIX `command` and SHALL provide a `commandWindows` override that invokes the installed Windows Python launcher and the same Hook bootstrap through `PLUGIN_ROOT`. The Windows launcher SHALL locate a supported 64-bit CPython interpreter, SHALL execute the handler with UTF-8 isolated standard-library settings, SHALL preserve the original argument boundaries, and SHALL require no WSL, Git Bash, or Cygwin executable.

SessionStart, UserPromptSubmit, and PreToolUse SHALL retain their current event names, matchers, timeouts, stdin payloads, stdout result shapes, and fail-open Hook behavior.

#### Scenario: Installed SessionStart launches from an ordinary Windows path

- **WHEN** Codex starts a session with the installed plugin under a local Windows path containing spaces or valid Unicode characters
- **THEN** `commandWindows` launches the current Hook through the `.cmd` launcher and the Hook returns its current JSON contract

#### Scenario: Windows Python is unavailable

- **WHEN** no supported 64-bit Python interpreter or valid `DEV_FLOW_PYTHON` override can execute the Hook
- **THEN** the launcher exits nonzero with a bounded diagnostic and no Controller task state is created or changed by the failed launch

#### Scenario: POSIX Hook launch is inspected

- **WHEN** the same candidate is installed on macOS
- **THEN** the existing `command` and POSIX launcher remain the active Hook path without routing through the Windows launcher

### Requirement: Windows Hook context uses the same task authority and a copyable PowerShell locator

On Windows, the Hook SHALL use the existing Controller and canonical task discovery to derive no-task guidance, one active task projection, multiple-task selection guidance, and inventory diagnostics. The injected Controller locator SHALL contain the exact installed Windows launcher, CLI bootstrap, and Controller data directory as PowerShell literal arguments and SHALL be executable unchanged in the supported shell.

A session started at or below any canonical member repository SHALL discover the same active task. The Hook SHALL NOT create a platform-specific task, projection, workflow, binding, or state path.

#### Scenario: Active task resumes from a secondary member

- **WHEN** SessionStart runs at or below a non-first repository member of one active task
- **THEN** the Hook injects that task's current projection and one PowerShell locator bound to the existing Controller data directory

#### Scenario: No active task covers the directory

- **WHEN** SessionStart runs outside every active task member
- **THEN** the Hook returns current start guidance and the same installed PowerShell locator without creating task state

#### Scenario: Locator path contains an apostrophe

- **WHEN** one installed launcher or data-root path contains an apostrophe
- **THEN** the PowerShell locator doubles it inside a single-quoted literal and executes without changing the intended argument boundaries

### Requirement: Windows Hook guards remain practical and explicitly bounded

PreToolUse SHALL continue to deny structured `Write`, `Edit`, and `apply_patch` operations whose resolved path equals or is contained by the protected plugin data root. It SHALL permit ordinary repository paths. Windows shell-command inspection SHALL recognize the exact generated Controller locator and MAY deny clear literal or environment-variable references to protected data, but SHALL NOT claim complete PowerShell interpretation or an unbypassable security boundary.

Guard evaluation SHALL run before task inventory loading so a corrupt task does not disable a clear structured-path denial. Unexpected Hook failures SHALL remain fail-open and SHALL NOT mutate Controller state.

#### Scenario: Structured write targets Controller data

- **WHEN** a Windows `Write`, `Edit`, or `apply_patch` input resolves inside the protected plugin data root
- **THEN** PreToolUse returns the current deny result before loading task inventory

#### Scenario: Exact Controller locator is used

- **WHEN** a shell call begins with the exact injected Windows Controller prefix and contains no additional PowerShell control operator
- **THEN** the Hook does not deny it as a protected-data reference

#### Scenario: Arbitrary PowerShell expression is ambiguous

- **WHEN** a shell command constructs a protected path through syntax outside the bounded checks
- **THEN** the Hook remains a fail-open guardrail and public guidance does not represent the command inspection as complete enforcement

### Requirement: Hook activation remains an explicit user trust decision

Installing, repairing, or upgrading the plugin SHALL NOT be represented as trusting its non-managed command Hooks. The installation receipt and public guidance SHALL direct the operator to start a new Codex session, open `/hooks`, review the installed source and exact current definition, and trust it before relying on automatic context restoration or guard behavior.

A changed Hook definition SHALL be treated as requiring review again according to Codex behavior. The product SHALL NOT use a trust bypass as its normal installation path.

#### Scenario: Plugin installation succeeds

- **WHEN** the plugin snapshot is installed successfully on Windows
- **THEN** the receipt reports plugin success separately and identifies Hook review as a remaining operator step

#### Scenario: Hook has not been trusted

- **WHEN** Codex skips the installed Hook pending review
- **THEN** documentation directs the operator to `/hooks` and does not diagnose the skipped Hook as a Controller-state failure

### Requirement: Native Windows support remains one bounded whole-product claim

The Windows installation SHALL expose the same plugin name, `PRODUCT_VERSION`, product identity, workflow catalog, Skills, Controller state model, assurance policy, Delivery Dossier, and Web UI as macOS. It SHALL NOT declare a Windows-specific version, package, marketplace entry, data namespace, workflow, compatibility line, or release gate.

The public supported Windows boundary SHALL be Windows 10 22H2 x64 and Windows 11 x64 client systems using supported 64-bit CPython, Git for Windows, Codex plugin and Hook support, PowerShell for lifecycle commands, and ordinary local repositories. Windows ARM64, 32-bit Python, Windows Server, WSL execution, UNC/SMB/NAS or mapped network repositories, `\\wsl$`, historical migration, and cross-operating-system task transfer SHALL remain outside the claim.

#### Scenario: Supported Windows client completes an installed task

- **WHEN** a documented Windows x64 client installs the plugin, trusts the Hook, and runs a representative task
- **THEN** all task records and outputs use the same current product authorities as macOS

#### Scenario: Unsupported Windows environment is used

- **WHEN** the product is run on an environment outside the documented boundary
- **THEN** the project makes no support claim and is not required to add a broad platform-detection or compatibility subsystem for this change
