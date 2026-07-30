# cross-platform-plugin-invocation Specification

## Purpose
TBD - created by archiving change complete-cross-platform-support. Update Purpose after archive.
## Requirements
### Requirement: Platform-specific bundled hook launch
The plugin SHALL register every bundled Codex hook handler with both the portable `command` entry and the Windows-specific `commandWindows` entry defined by the Codex hook contract. The two entries MUST invoke the same handler and preserve the same hook-event semantics. The POSIX command SHALL use a supported Python interpreter with shell-safe quoting, and the Windows command SHALL use a supported Windows Python launcher with Windows-safe quoting rather than depending on a `python3` executable.

#### Scenario: POSIX hook starts from a non-trivial plugin path
- **WHEN** Codex invokes a bundled hook on macOS or Linux with `PLUGIN_ROOT` containing spaces and Unicode characters
- **THEN** the configured `command` starts the intended Python handler, consumes the JSON event from standard input, and emits a valid hook JSON response

#### Scenario: Windows hook starts from a non-trivial plugin path
- **WHEN** Codex invokes a bundled hook on Windows with `PLUGIN_ROOT` containing spaces, Unicode characters, or shell metacharacters
- **THEN** the configured `commandWindows` starts the intended Python handler through the documented Windows Python launcher without interpreting any part of the plugin path as a command

#### Scenario: Hook registrations remain behaviorally paired
- **WHEN** the packaged hook configuration is inspected
- **THEN** every handler that has a `command` also has a `commandWindows` targeting the same script and hook lifecycle phase

### Requirement: Plugin environment and controller identity propagation
Bundled handlers SHALL load plugin code from `PLUGIN_ROOT` and SHALL use `PLUGIN_DATA` as the persistent workflow-data directory. A handler that exposes a controller command to the model MUST construct it from the running interpreter identity, the controller path below `PLUGIN_ROOT`, and an explicit `--data-dir` argument for `PLUGIN_DATA`. It MUST NOT silently substitute a default state location or rewrite the running interpreter to a generic launcher.

#### Scenario: Build context injects a resumable controller prefix
- **WHEN** the build-context handler runs with valid `PLUGIN_ROOT` and `PLUGIN_DATA` values
- **THEN** its context contains a controller prefix using the current Python executable, the packaged controller path, and the explicit injected data directory

#### Scenario: Required plugin environment is unavailable
- **WHEN** a bundled handler cannot resolve `PLUGIN_ROOT` or `PLUGIN_DATA`
- **THEN** it emits a non-mutating diagnostic response and does not construct a command that reads or writes an unrelated default location

### Requirement: Platform-specific MCP profiles use their native packaged launch commands
When the MCP companion schema cannot express an operating-system-specific
command override, the plugin SHALL expose explicit POSIX and Windows profiles
that default to disabled and are documented as mutually exclusive. Native
validation MUST select the current-host profile from the exact packaged
`.mcp.json` and complete MCP initialization and tool discovery through that
profile's configured command. Directly invoking the underlying Python server
MUST NOT substitute for this launcher proof.

#### Scenario: Validate the POSIX MCP profile
- **WHEN** a supported macOS or Linux validation job selects the packaged POSIX profile
- **THEN** its configured shell command starts from the plugin root and returns a valid initialize response and bounded tool list

#### Scenario: Validate the Windows MCP profile
- **WHEN** a native Windows validation job selects the packaged Windows profile
- **THEN** its configured `cmd.exe` command starts the shipped launcher from the plugin root and returns a valid initialize response and bounded tool list

#### Scenario: Reject simultaneous platform profiles
- **WHEN** package validation finds both platform profiles enabled
- **THEN** it rejects the ambiguous configuration before plugin handoff

### Requirement: Canonical Codex command matcher is preserved
The hook configuration SHALL retain the canonical Codex `Bash` matcher for command-tool events. Cross-platform support MUST be implemented by portable launch commands and command-payload recognition, not by replacing the canonical matcher with undocumented operating-system-specific tool aliases.

#### Scenario: Packaged matcher is validated
- **WHEN** the packaged hook configuration is checked on Windows, macOS, or Linux
- **THEN** command-related hook handlers remain registered under the canonical `Bash` matcher and expose equivalent decisions on every platform

### Requirement: Wrapped Git commands receive equivalent guardrails
The command guard SHALL recognize `git` and `git.exe` by executable basename after normalizing both slash styles, including absolute Windows drive, UNC, and space-containing paths. It MUST inspect command payloads launched directly, by supported POSIX shells, by `cmd.exe /c`, by Windows PowerShell, and by `pwsh -Command`, including chained commands and supported quoting forms. Equivalent protected Git mutations MUST produce the same guardrail decision regardless of executable spelling or wrapper. A recognized wrapper payload that cannot be parsed safely MUST be treated as blocked with a diagnostic rather than classified as safe.

#### Scenario: Absolute Windows Git executable is guarded
- **WHEN** a command invokes a protected Git mutation through a path such as `C:\Program Files\Git\cmd\git.exe` or the same path with forward slashes
- **THEN** the hook identifies the Git invocation and returns the same denial as it does for the equivalent direct `git` command

#### Scenario: Command Prompt wrapper is guarded
- **WHEN** `cmd.exe /d /s /c` carries a protected `git.exe` mutation in a quoted or chained payload
- **THEN** the hook extracts the payload, identifies every relevant Git invocation, and applies the protected-mutation denial

#### Scenario: PowerShell wrappers are guarded
- **WHEN** Windows PowerShell or `pwsh -Command` carries a protected Git mutation using a supported quoting or chaining form
- **THEN** the hook identifies the Git invocation without applying POSIX-only tokenization and returns the protected-mutation denial

#### Scenario: POSIX wrapper behavior remains intact
- **WHEN** `sh`, `bash`, or another supported POSIX shell carries the equivalent protected Git mutation
- **THEN** the hook continues to identify and deny that mutation with the same reason

#### Scenario: Ambiguous wrapped payload fails safely
- **WHEN** a supported shell wrapper is recognized but its command payload cannot be decomposed without ambiguity
- **THEN** the hook blocks the payload with an actionable parse diagnostic instead of allowing it as a non-Git command

### Requirement: Skill commands preserve the injected executable prefix
All bundled workflow skills SHALL reuse the controller prefix injected by the hook or returned by controller inspection. Skills MUST NOT reconstruct that prefix with a hard-coded `python3`, omit the explicit data directory, or present POSIX line continuation as a platform-neutral command. Platform-neutral examples SHALL use a single command/argument sequence, while shell-specific multiline examples MUST be clearly labelled and paired with equivalent guidance for the other supported shells.

#### Scenario: A skill resumes on Windows
- **WHEN** an agent follows a bundled skill in a Windows session
- **THEN** every controller operation preserves the injected Windows interpreter and data-directory arguments and requires no POSIX continuation syntax

#### Scenario: A skill resumes on macOS or Linux
- **WHEN** an agent follows the same bundled skill on macOS or Linux
- **THEN** it invokes the same controller subcommands and gates through the injected prefix without changing their state-machine semantics

#### Scenario: Generated command guidance is audited
- **WHEN** packaged skill Markdown and references are scanned for controller reconstruction examples
- **THEN** no platform-neutral example hard-codes `python3` or relies on an unlabelled backslash line continuation

### Requirement: Installable package and manifest are internally complete
The plugin manifest and package layout SHALL validate against the supported Codex plugin schema and SHALL expose the bundled `hooks/hooks.json` through the official hook-discovery convention. The packaged inventory MUST include every runtime script, hook, skill asset, template, and project-guidance file referenced by the manifest or published documentation. A release MUST fail validation when a referenced local file is absent or differs only by a case spelling that is not portable across supported filesystems.

#### Scenario: Plugin manifest validates without an unsupported hook field
- **WHEN** the release candidate is processed by the plugin-creator manifest validator from the packaged root
- **THEN** the manifest is valid, contains no unsupported `hooks` field, and every path it actually declares resolves inside the package

#### Scenario: Independent default hook discovery check passes
- **WHEN** the package/default-discovery validator inspects the same release-candidate root
- **THEN** `hooks/hooks.json` exists at Codex's official default discovery location, is valid hook JSON, and contains paired platform commands for every bundled handler

#### Scenario: Package references resolve on every supported filesystem
- **WHEN** package inventory validation resolves all manifest, skill, template, and documentation references using Windows and POSIX path rules
- **THEN** every reference points to exactly one shipped file and references to absent `AGENTS.md` or template guidance fail the release

### Requirement: English and Chinese documentation describe one platform contract
`README.md`, `README.zh-CN.md`, and `INSTALL.md` SHALL consistently document Windows, macOS, and Linux support, the declared Python and Git prerequisites, platform-appropriate installation and update commands, hook launcher behavior, validation steps, and recovery guidance. Examples MUST reference only shipped files and verified workflows. Platform-specific syntax SHALL be labelled so that readers are not instructed to run POSIX commands in Command Prompt or PowerShell.

#### Scenario: Bilingual platform claims agree
- **WHEN** the English and Chinese documentation sets are reviewed for a release
- **THEN** they describe the same supported operating systems, prerequisites, safety guarantees, limitations, and lifecycle operations

#### Scenario: Documented commands match their shell
- **WHEN** a user follows the documented install, update, validation, or recovery workflow in Bash, Command Prompt, or PowerShell
- **THEN** the selected example uses valid syntax for that shell and addresses the same plugin files and controller operation

#### Scenario: Documentation does not advertise missing assets
- **WHEN** documentation links and local path references are checked against the packaged inventory
- **THEN** each referenced file is shipped and readable, or the stale reference has been removed before release
