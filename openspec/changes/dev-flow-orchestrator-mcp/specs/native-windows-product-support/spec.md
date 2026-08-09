## Purpose

Replace Windows command-Hook product integration with one native installed STDIO MCP
server while retaining the same Controller state, workflow, assurance, Web UI,
installer authority, and bounded Windows x64 support claim.

## REMOVED Requirements

### Requirement: The installed plugin launches its current Hook natively on supported Windows clients

**Reason:** The `0.5.0` model-facing interaction path is the bundled MCP server, not a
command Hook. Keeping the Hook would preserve a second invocation and context
authority and would not solve repeated source and Skill reading.

**Migration:** The native `.cmd` launcher starts `dev_flow_mcp.py --stdio` from the
managed runtime. Context restoration uses `dev_flow_find_tasks_for_path` and
`dev_flow_get_next_action`.

### Requirement: Windows Hook context uses the same task authority and a copyable PowerShell locator

**Reason:** MCP tools replace injected CLI locators and shell-escaped JSON commands.
The Controller and current data namespace remain unchanged.

**Migration:** Operators use the stable MCP tool catalog for normal tasks and retain
the standalone JSON CLI only for documented recovery or scripting.

### Requirement: Windows Hook guards remain practical and explicitly bounded

**Reason:** An MCP server cannot observe every Bash, PowerShell, edit, or patch call.
Retaining only this Hook would keep an incomplete Codex-specific guard and a second
trust surface.

**Migration:** Task data stays outside admitted repositories; MCP responses and
normal diagnostics do not expose its path; model-facing mutations are closed tools;
documentation states that unrestricted local shell access remains outside the MCP
security boundary.

### Requirement: Hook activation remains an explicit user trust decision

**Reason:** The installed product no longer uses command Hooks. MCP visibility and
mutation approval are governed by Codex MCP registration and tool-approval behavior.

**Migration:** Installation receipts distinguish verified source, managed runtime,
plugin activation, MCP server health, tool visibility, and remaining host/user
approval.

## ADDED Requirements

### Requirement: The installed plugin launches its MCP server natively on supported Windows clients

The packaged Windows MCP configuration SHALL invoke the installed Windows MCP
launcher and the same MCP bootstrap used on macOS. The launcher SHALL locate the
validated installer-owned runtime and supported 64-bit CPython 3.10–3.14, SHALL
preserve UTF-8 STDIO and exact argument boundaries, and SHALL require no WSL, Git
Bash, Cygwin, or POSIX shell.

The Windows server SHALL expose the same `dev-flow-mcp/1.0.0` identity, instructions,
tool names, input/output schemas, annotations, Controller errors, and current model
values as macOS. It SHALL not create a Windows-specific MCP interface, task type,
workflow, data namespace, or release line.

#### Scenario: Installed MCP launches from an ordinary Windows path

- **WHEN** Codex starts the plugin from a local Windows path containing spaces or valid Unicode
- **THEN** the native launcher initializes the protocol and lists the current stable catalog without shell emulation

#### Scenario: Supported Python is unavailable

- **WHEN** no supported 64-bit Python 3.10–3.14 interpreter or valid installer-owned runtime can execute the server
- **THEN** launch fails with bounded stderr diagnostics, emits no malformed protocol stdout, and does not mutate Controller state

#### Scenario: macOS and Windows catalogs are compared

- **WHEN** installed artifact tests initialize both supported host packages for the same release
- **THEN** server identity, instructions digest, tool catalog, schemas, and annotations are equivalent except for native launcher details

### Requirement: Windows MCP discovery uses current canonical task authority

On supported Windows clients, `dev_flow_find_tasks_for_path`, task admission, active
membership leases, overlap checks, and Controller-data separation SHALL use the same
current Windows path comparison. Discovery from any member or contained path SHALL
return the same active task despite supported drive-letter case or separator
spelling differences. It SHALL return a bounded PowerShell-independent task identity,
not an injected shell locator.

The MCP server SHALL use the same Controller and current model namespace as the CLI
and Web UI. It SHALL NOT create platform-specific projections or persist the client
working directory as task authority.

#### Scenario: A task resumes from a secondary Windows member

- **WHEN** a client discovers from a contained path in any non-first member
- **THEN** it receives the same current task ID and can obtain the same exact action binding as discovery from the first member

#### Scenario: No active task covers the path

- **WHEN** the canonical Windows path is outside every healthy active member
- **THEN** discovery returns `none` without creating task state or a data directory inside the repository

### Requirement: Windows MCP approval and residual local-shell risk are explicit

The Windows installer and public guidance SHALL direct the operator to inspect the
MCP server identity and tool catalog and SHALL explain the host's approval behavior
for mutation tools. Installation SHALL NOT be represented as blanket approval and
SHALL NOT rewrite unrelated user policy.

Documentation SHALL state that the MCP server cannot prevent an unrestricted
PowerShell or other local process from searching for or changing files outside the
MCP interface. It SHALL state the current controls: no tool exposes the data path,
all normal mutations use Controller tools, data and repositories are disjoint, server
logs redact protected paths, and direct state access remains unsupported.

#### Scenario: Codex asks for mutation approval

- **WHEN** host policy requires approval for a Windows MCP mutation tool
- **THEN** the prompt is treated as expected user authority and not diagnosed as server failure

#### Scenario: An arbitrary PowerShell command targets task data

- **WHEN** a user or model with unrestricted local shell constructs a path outside the MCP server
- **THEN** the product makes no claim that MCP intercepted it and documentation describes only the current MCP-first security boundary

## MODIFIED Requirements

### Requirement: Native Windows support remains one bounded whole-product claim

The Windows installation SHALL expose the same plugin name, `RELEASE_VERSION`,
`MODEL_VERSION`, product identity, workflow catalog, Controller state model,
assurance policy, Delivery Dossier, CLI, Web UI, and MCP interface as macOS. It SHALL
NOT declare a Windows-specific release, model version, MCP catalog, package,
marketplace entry, data namespace, workflow, compatibility line, or release gate.

The public supported Windows boundary SHALL be Windows 10 22H2 x64 and Windows 11
x64 client systems using supported 64-bit CPython 3.10–3.14, Git for Windows, Codex
plugin and local STDIO MCP support, native PowerShell for lifecycle commands, and
ordinary local repositories. Windows ARM64, 32-bit Python, Windows Server, WSL
execution, UNC/SMB/NAS or mapped network repositories, `\\wsl$`, remote MCP serving,
historical migration, and cross-operating-system task transfer SHALL remain outside
the claim.

#### Scenario: Supported Windows client completes an installed MCP task

- **WHEN** a documented Windows x64 client installs the plugin and completes a representative workflow through MCP
- **THEN** every task record and output uses the same current product authorities and persisted model as macOS

#### Scenario: Existing current task is resumed after upgrade

- **WHEN** a model `0.4.0` task created by the prior Hook/CLI product is opened by the Windows MCP release
- **THEN** it resumes in place with no state migration or Windows-specific conversion

#### Scenario: Unsupported Windows environment is used

- **WHEN** the product runs outside the documented support boundary
- **THEN** the project makes no compatibility claim and is not required to add a broad platform-detection, remote path, or compatibility subsystem for this change
