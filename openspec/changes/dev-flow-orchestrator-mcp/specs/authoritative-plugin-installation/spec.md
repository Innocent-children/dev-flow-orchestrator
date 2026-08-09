## Purpose

Extend the existing authoritative source and marketplace lifecycle so supported
installers provision, activate, validate, repair, and remove the MCP-first plugin and
its isolated runtime without weakening source verification or task-data preservation.

## MODIFIED Requirements

### Requirement: Plugin activation failure is explicit and recoverable

The installer SHALL return nonzero when plugin registration, managed-runtime
activation, MCP initialization, tool-catalog validation, or installed server health
fails. It SHALL report source verification, marketplace registration, plugin
activation, runtime activation, MCP visibility, and tool health as separate states.
It SHALL print exact bounded recovery commands for plugin removal/re-addition and MCP
inspection without rewriting or deleting the verified source checkout or Controller
task data.

A prior validated managed runtime SHALL remain available when staged replacement
fails and retaining it is safe. The installer SHALL NOT claim success merely because
`codex plugin add` succeeded before the MCP server failed. It SHALL NOT automatically
fall back to legacy Skills or Hooks.

#### Scenario: Codex rejects plugin activation

- **WHEN** source, package, runtime, and marketplace validation succeed but `codex plugin add` exits unsuccessfully
- **THEN** installation exits unsuccessfully and reports manual plugin recovery while preserving source, runtime staging evidence, and task data

#### Scenario: Plugin activates but MCP startup fails

- **WHEN** Codex accepts the plugin but the installed launcher cannot initialize the MCP server
- **THEN** installation exits unsuccessfully, identifies MCP health as failed, and does not present the plugin as usable

#### Scenario: Tool catalog does not match the candidate

- **WHEN** installed `tools/list` differs from the candidate's approved interface
- **THEN** activation fails and reports the identity or catalog mismatch without enabling a legacy fallback

### Requirement: Candidate validation covers installer authority boundaries

The candidate SHALL include behavior suites that invoke each supported host installer
against isolated Git repositories, marketplaces, Codex executables, MCP configuration,
Python interpreters, and managed-runtime roots. The macOS suite SHALL retain the
complete established source-authority matrix. The Windows suite SHALL retain its
representative native fresh, idempotent, fast-forward, refusal, preservation,
activation-failure, and uninstall boundaries.

Both suites SHALL additionally cover:

- exact locked MCP runtime provisioning and receipt validation;
- runtime staging failure and preservation of a prior valid runtime;
- real installed launcher initialization and stable tool catalog;
- no non-protocol stdout;
- bundled/standalone duplicate registration detection;
- plugin success with MCP failure as an overall failure;
- Python below 3.10 and unsupported interpreter architecture refusal;
- stale, missing, or mismatched runtime ownership receipt;
- safe uninstallation of owned runtime assets while preserving task data;
- absence of installed legacy Skill and Hook authority.

Validation SHALL NOT require either host to execute the other host's shell language.
Windows SHALL NOT duplicate every established Git-history permutation merely for
platform parity, but it SHALL execute the real PowerShell installer, uninstaller, and
Windows MCP launcher. Every required shell, PowerShell, MCP configuration, launcher,
lock, receipt, package validator, and host test asset SHALL be part of candidate
validation.

#### Scenario: Candidate installer behavior is validated on macOS

- **WHEN** focused validation runs on macOS
- **THEN** it retains all authoritative source and marketplace cases and proves the real POSIX MCP runtime, activation, duplicate detection, and uninstall path

#### Scenario: Candidate installer behavior is validated on Windows

- **WHEN** focused validation runs on Windows
- **THEN** it executes real PowerShell lifecycle entry points and native MCP launcher against isolated dependencies and covers representative success, refusal, preservation, and activation failure

#### Scenario: A required MCP lifecycle asset is missing

- **WHEN** `.mcp.json`, a native launcher, runtime lock, managed-runtime receipt contract, or installed MCP smoke is absent
- **THEN** package validation fails before plugin installation

### Requirement: Public installation guidance states the authority boundary

Public English and Simplified Chinese guidance SHALL continue to identify `main` as
the non-configurable authoritative source ref and SHALL explain that automatic
upgrades require the expected origin, a clean attached `main`, and fast-forward-only
history. It SHALL provide the correct native installation and uninstallation entry
points for every supported host.

Guidance SHALL additionally state:

- local STDIO MCP is the default installed interaction boundary;
- supported Python is 64-bit CPython 3.10–3.14;
- the installer creates an isolated owned runtime from the locked dependency set;
- bundled and standalone Dev Flow MCP registrations must not both be active;
- the operator can verify server visibility, identity, and tool catalog with current
  Codex MCP inspection commands or UI;
- mutation approval remains host/user authority;
- legacy Skills, command Hooks, `/hooks` review, and the old PreToolUse guard are no
  longer part of the installed product;
- task data remains in the current `0.4.0` namespace and is preserved on uninstall;
- CLI and Web UI remain recovery/inspection adapters;
- the local-shell residual risk, unsupported environments, and rollback path are
  explicit.

Neither language SHALL imply that plugin registration proves MCP health, that tool
annotations grant approval, that the installer migrates task data, or that the MCP
server prevents unrestricted local shell access.

#### Scenario: macOS operator reviews installation guidance

- **WHEN** an operator reads the macOS instructions
- **THEN** they can determine source authority, eligible upgrade state, Python and runtime requirements, MCP verification, registration mode, approval boundary, uninstall behavior, and rollback

#### Scenario: Windows operator reviews installation guidance

- **WHEN** an operator reads the Windows instructions
- **THEN** they can identify the native PowerShell command, x64 client boundary, Git and Python prerequisites, MCP health check, duplicate-registration rule, Web UI command, and data-preserving uninstall

#### Scenario: Documentation still requires Hook trust

- **WHEN** public guidance instructs the operator to trust `/hooks` as part of current `0.5.0` activation
- **THEN** package validation fails as stale product guidance

### Requirement: Supported host entry points apply one authoritative installation lifecycle

The product SHALL provide `scripts/install.sh` for supported macOS hosts and
`scripts/install.ps1` for supported Windows x64 clients. Each entry point SHALL
enforce authoritative `main`, eligible existing checkout, candidate package
validation, marketplace isolation, managed-runtime staging, plugin activation,
installed MCP protocol smoke, duplicate-registration checks, and final receipt before
reporting success.

The managed runtime SHALL be outside source, task data, and user repositories. It
SHALL be produced from the candidate's exact lock under a supported 64-bit CPython
3.10–3.14 interpreter and SHALL be activated only after import and MCP smoke success.
Platform-specific syntax MAY differ, but neither host SHALL weaken source authority,
mutate an ineligible checkout, replace a malformed marketplace, reuse an unverified
runtime, report plugin-only success, grant blanket tool approval, or install legacy
Skill/Hook authority.

#### Scenario: Fresh macOS installation succeeds

- **WHEN** a supported macOS host has required tools, no source checkout, no duplicate registration, and a valid or absent marketplace
- **THEN** the installer verifies `main`, validates the package, provisions the runtime, activates the plugin, proves the installed MCP server, and emits one complete receipt

#### Scenario: Fresh Windows installation succeeds

- **WHEN** a supported Windows x64 client has required tools, no source checkout, no duplicate registration, and a valid or absent marketplace
- **THEN** the PowerShell installer performs the same authority lifecycle through native executables and reports MCP health separately

#### Scenario: Existing installation is repaired or upgraded

- **WHEN** source is the expected clean attached `main` and equal to or behind fetched `main`
- **THEN** the installer leaves or fast-forwards it, stages or reuses an exact matching runtime, validates the installed MCP artifact, and reports repair or upgrade accurately

#### Scenario: Existing source is ineligible

- **WHEN** source has an unexpected origin or branch, reported changes, local-ahead history, divergence, or an ignored-path collision
- **THEN** installation fails without switching, resetting, stashing, cleaning, overwriting, registering, or activating that source

#### Scenario: A duplicate Dev Flow registration is active

- **WHEN** bundled activation would coexist with a standalone registration for the same owned launcher
- **THEN** installation fails with explicit resolution guidance and does not claim one deterministic server

#### Scenario: Runtime validation fails after staging

- **WHEN** dependency, import, identity, protocol, or tool-catalog validation fails
- **THEN** the candidate is not activated, a prior validated runtime remains authoritative where safe, and task data is unchanged

### Requirement: Windows uninstallation removes only validated installation assets

The product SHALL provide `scripts/uninstall.ps1` for supported Windows x64 clients.
It SHALL remove the installed plugin when present, atomically remove only the Dev
Flow entry from a valid personal marketplace, and remove only validated
installer-owned MCP runtime and launcher assets. It SHALL preserve external
Controller task data in all cases and SHALL preserve unrelated bundled or standalone
MCP registrations.

By default, source deletion SHALL occur only after validating the expected product,
an allowed origin, attached `main`, no tracked, untracked, or ignored content, and no
local-only commits. A keep-source option SHALL preserve source. Runtime deletion
SHALL require an exact ownership receipt and expected location; uncertainty SHALL
fail closed and leave the runtime for manual handling. Uninstallation SHALL report
plugin, marketplace, MCP registration, runtime, source, and task-data outcomes
separately.

#### Scenario: Ordinary Windows uninstall succeeds

- **WHEN** plugin, marketplace entry, runtime, launchers, and source are all validated as installer-owned and safe
- **THEN** those assets are removed and the receipt states that Controller task data was preserved

#### Scenario: Windows source contains user work

- **WHEN** source has local changes, ignored content, local-only commits, unexpected origin, or another unsafe identity
- **THEN** uninstallation refuses to delete source and reports the reason without deleting task data or unrelated MCP configuration

#### Scenario: Managed-runtime ownership is uncertain

- **WHEN** the runtime receipt is missing, inconsistent, or points outside the expected owned path
- **THEN** uninstallation leaves the runtime for manual handling and does not infer ownership from directory name alone

#### Scenario: Keep source is requested

- **WHEN** the operator supplies the documented keep-source option
- **THEN** independently safe plugin, marketplace, and owned runtime removal may proceed while source and task data remain unchanged
