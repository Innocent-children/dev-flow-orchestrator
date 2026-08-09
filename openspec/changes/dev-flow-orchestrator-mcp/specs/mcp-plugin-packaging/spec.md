## Purpose

Define how Dev Flow is distributed as an MCP-first Codex plugin and as an optional
standalone local MCP server while preserving authoritative source verification,
managed runtime ownership, user approval, duplicate-registration safety, and task
data.

## ADDED Requirements

### Requirement: The Codex plugin bundles the local MCP server as its interaction surface

The plugin manifest SHALL retain product name `dev-flow-orchestrator`, the single
`RELEASE_VERSION`, marketplace identity, author, license, and documentation metadata.
It SHALL declare an MCP server through the supported `mcpServers` reference to a root
`.mcp.json` file or the current equivalent plugin packaging contract. The MCP
configuration SHALL launch the installed Dev Flow MCP launcher in STDIO mode and
SHALL NOT embed machine-specific absolute paths, secrets, user tokens, network URLs,
or a second data namespace.

After MCP parity and installed-journey gates pass, the package SHALL no longer expose
Dev Flow Skills or command Hooks as current model-facing workflow authority. The
package validator SHALL reject a candidate that simultaneously advertises the new
MCP-first interface and installs the legacy `follow-dev-flow`,
`analyze-change-impact`, `review-dev-flow-change`, SessionStart, UserPromptSubmit, or
PreToolUse interaction path.

#### Scenario: The installed plugin is discovered

- **WHEN** Codex loads the verified plugin snapshot
- **THEN** it discovers one bundled `dev-flow` local STDIO MCP server and the stable tool catalog without requiring a Skill invocation or Hook trust step

#### Scenario: The MCP manifest is missing or unsafe

- **WHEN** `.mcp.json` is absent, malformed, references a network transport, contains a secret, or resolves outside validated installed assets
- **THEN** package validation or plugin activation fails before reporting a healthy MCP installation

#### Scenario: Legacy authority remains packaged

- **WHEN** the candidate retains installed workflow Skills or command Hooks after the MCP removal gate
- **THEN** package validation fails because two conflicting model-facing authorities would exist

### Requirement: The installed launcher resolves owned runtime and data paths natively

The package SHALL provide one POSIX launcher and one Windows launcher that preserve
argument boundaries, locate the installer-owned MCP runtime, start the same MCP
bootstrap with UTF-8 behavior, and require no shell-language emulation on the other
host. The launcher SHALL resolve the current Controller data root through the shared
resolver and SHALL pass no data-root path through model-visible configuration or
output.

A launcher SHALL fail before protocol initialization when the managed runtime is
missing, its receipt does not match the active source candidate, its locked
dependencies are inconsistent, or no supported 64-bit CPython 3.10–3.14 interpreter
can execute it. A failed launch SHALL not create or mutate task state merely to
diagnose installation.

#### Scenario: POSIX plugin path contains spaces or Unicode

- **WHEN** Codex starts the installed server from a supported macOS path containing spaces or valid Unicode
- **THEN** the POSIX launcher preserves the exact bootstrap and argument boundaries and initializes STDIO successfully

#### Scenario: Windows plugin path contains spaces or Unicode

- **WHEN** Codex starts the installed server from a supported Windows path containing spaces or valid Unicode
- **THEN** the native Windows launcher starts the same server without WSL, Git Bash, or Cygwin

#### Scenario: The managed runtime is inconsistent

- **WHEN** the runtime receipt, source commit, release version, Python identity, or locked dependency metadata does not match the active installation
- **THEN** launch fails with a bounded stderr diagnostic and emits no invalid MCP stdout

### Requirement: The MCP runtime is an isolated installer-owned asset

Installers SHALL create or update a managed runtime in an installer-owned location
outside the verified source checkout, outside every Controller data root, and outside
user repositories. They SHALL install the candidate's exact locked runtime set and
write a bounded ownership receipt containing product identity, source commit,
release version, Python identity, lock digest, runtime location identity, and creation
or update action.

Runtime replacement SHALL be staged and validated before activation. An existing
healthy runtime MAY be reused only when its receipt and installed metadata exactly
match the candidate. Failed staging SHALL leave the prior active runtime and task
data intact. The source checkout SHALL remain clean and SHALL not acquire a local
virtual environment or generated dependency files as a side effect of installation.

#### Scenario: A fresh runtime is provisioned

- **WHEN** source verification and package validation succeed and no matching runtime exists
- **THEN** the installer creates a staged isolated runtime, installs the lock, validates the MCP bootstrap, atomically activates it, and records ownership

#### Scenario: An installation is repaired idempotently

- **WHEN** the verified source and runtime receipt already match the candidate
- **THEN** the installer validates and reuses or deterministically repairs the owned runtime without changing task data

#### Scenario: Runtime staging fails

- **WHEN** dependency installation, import smoke, protocol smoke, or receipt validation fails
- **THEN** plugin activation is not reported as successful and the previous validated runtime and Controller data remain unchanged

### Requirement: Bundled and standalone registration are mutually exclusive

The supported default SHALL be bundled plugin registration. An operator MAY instead
register the same installed launcher as one standalone local STDIO MCP server through
the documented Codex MCP configuration path. The installer SHALL NOT create both
registrations automatically and SHALL NOT modify an unrelated user MCP server.

Installation, repair, validation, and public diagnostics SHALL detect an active
standalone Dev Flow registration when bundled mode is being enabled, and SHALL detect
an active bundled registration when standalone setup is requested. The operation
SHALL fail or require the documented explicit operator resolution before claiming a
healthy state. Detection SHALL compare the Dev Flow identity and launcher target,
not merely a generic server name.

#### Scenario: Only bundled mode is configured

- **WHEN** the plugin owns the active Dev Flow MCP registration and no standalone duplicate exists
- **THEN** health checks report one server identity and normal activation proceeds

#### Scenario: Both modes are active

- **WHEN** the same product would be started from bundled and standalone registrations
- **THEN** installation or health validation reports a duplicate, identifies the two configuration surfaces, and does not claim deterministic task authority

#### Scenario: An unrelated MCP server has a similar name

- **WHEN** another user server name contains `dev-flow` but does not resolve to the owned product identity or launcher
- **THEN** the installer preserves it and does not delete or rewrite it automatically

### Requirement: MCP approval remains user and host authority

Plugin installation SHALL register the server but SHALL NOT silently grant blanket
approval for its mutation tools, rewrite unrelated global MCP approval settings, or
represent tool annotations as authorization. The candidate SHALL provide a bounded
plugin-scoped recommended policy that allows practical use while leaving final
approval behavior to Codex and the operator.

Installation receipts and public documentation SHALL state which tools are read-only,
which mutate or terminate Controller state, that a user should review the installed
MCP identity and tool catalog, and that the former Hook trust step and PreToolUse
guard no longer apply. A successful install SHALL distinguish source verification,
runtime health, plugin activation, MCP visibility, and remaining user approval.

#### Scenario: Installation succeeds but a mutation needs approval

- **WHEN** Codex exposes the server but host policy requires approval for `dev_flow_start_task` or another mutation
- **THEN** documentation treats the prompt as expected host authority rather than an MCP runtime failure

#### Scenario: Installer attempts to grant blanket approval

- **WHEN** an implementation would edit unrelated user policy or approve all Dev Flow tools without explicit operator control
- **THEN** package or lifecycle validation fails

### Requirement: Activation proves the installed MCP artifact rather than source-only code

After source, package, and managed-runtime validation, each supported installer SHALL
activate the plugin and run an installed-artifact MCP smoke. The smoke SHALL invoke
the actual installed launcher and runtime, complete initialize, inspect bounded
instructions, list the exact tool catalog, call `dev_flow_server_info`, and shut down
cleanly. A source-tree import or mocked protocol exchange SHALL NOT substitute for
this activation proof.

Activation failure SHALL be explicit and recoverable. The installer SHALL return
nonzero, preserve the verified source and task data, preserve a previously working
runtime where possible, and print exact bounded recovery commands for plugin and MCP
inspection. It SHALL never report success merely because plugin registration
completed before the server failed.

#### Scenario: The installed smoke succeeds

- **WHEN** the real installed launcher initializes, lists the expected catalog, and returns matching server identity
- **THEN** the receipt may report MCP activation healthy

#### Scenario: Plugin registration succeeds but MCP startup fails

- **WHEN** Codex accepts the plugin yet the installed launcher or runtime cannot initialize
- **THEN** installation exits unsuccessfully and reports plugin activation and MCP health as separate states

### Requirement: Uninstallation removes only validated MCP installation assets

Uninstallers SHALL remove the installed plugin when present, atomically remove only
the Dev Flow marketplace entry from a valid marketplace, and remove only the
validated installer-owned MCP runtime and launch assets. They SHALL preserve all
Controller task data and unrelated MCP registrations by default.

Source-checkout deletion SHALL retain the current fail-closed validation over product
identity, allowed origin, attached authoritative branch, tracked/untracked/ignored
content, and local-only commits. A keep-source option SHALL preserve the source. A
keep-runtime option MAY be offered only when it is explicit and does not leave a
registration that claims a removed product. Any uncertainty about runtime or source
ownership SHALL leave that asset for manual handling rather than deleting it.
If an independently managed standalone Dev Flow registration still resolves to the
installer-owned launcher or runtime selected for removal, uninstallation SHALL fail
closed before removing those shared assets and SHALL require the operator to disable
or remove the standalone registration explicitly. It SHALL not leave a dangling
registration and SHALL not edit unrelated registration policy automatically.

#### Scenario: Ordinary uninstall succeeds

- **WHEN** plugin, marketplace entry, managed runtime, launch assets, and source are all validated as installer-owned and safe to remove
- **THEN** those installation assets are removed and the receipt states that task data was preserved

#### Scenario: Runtime ownership is uncertain

- **WHEN** the runtime receipt is missing, inconsistent, or points outside the expected owned location
- **THEN** uninstallation refuses to delete that runtime, continues only with independently safe removals, and reports manual cleanup without touching task data

#### Scenario: A standalone registration exists

- **WHEN** a standalone Dev Flow MCP registration is not owned by the plugin installer
- **THEN** plugin uninstall preserves it and, when it references an otherwise removable Dev Flow launcher or runtime, preserves those shared assets and requires explicit operator cleanup rather than leaving a dangling registration
