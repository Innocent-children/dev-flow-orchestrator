# authoritative-plugin-installation Specification

## Purpose
TBD - created by archiving change fix-installer-authoritative-ref. Update Purpose after archive.
## Requirements
### Requirement: Fresh installation selects the authoritative ref
The installer SHALL treat repository branch `main` as its non-configurable authoritative ref, SHALL select that branch explicitly when cloning, and SHALL activate no package unless the resulting checkout is a clean attached `main` checkout whose `HEAD` equals the commit fetched from the expected origin's `refs/heads/main`.

#### Scenario: Remote default branch is not main
- **WHEN** a fresh installation uses a repository whose advertised default branch differs from `main` but whose `main` branch exists
- **THEN** the installer clones and activates the verified `main` commit

#### Scenario: Authoritative branch cannot be fetched
- **WHEN** the expected origin does not provide `refs/heads/main`
- **THEN** the installer fails before package validation, marketplace registration, or plugin activation

### Requirement: Existing installation upgrades only by verified fast-forward
The installer SHALL require an existing source checkout to have the exact expected origin URL, no reported tracked or untracked working-tree changes, and an attached `main` branch. It SHALL fetch the authoritative `main` ref explicitly, SHALL allow an update only when the installed `HEAD` is an ancestor of the fetched commit, SHALL make the fast-forward refuse to overwrite any ignored local path, and SHALL verify clean state and exact commit equality before package validation or activation.

#### Scenario: Existing checkout already equals the authoritative commit
- **WHEN** an existing clean `main` checkout with the expected origin already equals the fetched authoritative commit
- **THEN** reinstalling is idempotent and proceeds without changing its commit

#### Scenario: Existing checkout is behind the authoritative commit
- **WHEN** an existing clean `main` checkout with the expected origin is an ancestor of the fetched authoritative commit
- **THEN** the installer fast-forwards it and proceeds only after `HEAD` equals that fetched commit

#### Scenario: Existing checkout has an unexpected origin
- **WHEN** an existing checkout's `origin` URL differs from the configured repository URL
- **THEN** the installer fails without changing the checkout, marketplace, or plugin activation state

#### Scenario: Existing checkout is not on main
- **WHEN** an existing checkout is on another branch or has a detached `HEAD`
- **THEN** the installer fails without switching branches or activating the plugin

#### Scenario: Existing checkout is dirty
- **WHEN** an existing checkout has tracked or untracked working-tree changes
- **THEN** the installer fails without stashing, cleaning, resetting, or overwriting those changes

#### Scenario: Ignored local path collides with incoming main
- **WHEN** an existing clean checkout contains an ignored local path that the fetched authoritative commit would begin tracking
- **THEN** the installer fails without changing `HEAD`, the ignored path, marketplace content, or plugin activation state

#### Scenario: Unrelated ignored content does not block an upgrade
- **WHEN** an existing clean checkout contains ignored local content at paths that the fetched authoritative commit does not update
- **THEN** an otherwise eligible fast-forward proceeds without deleting or rewriting that ignored content

#### Scenario: Existing checkout has local commits
- **WHEN** the fetched authoritative commit is an ancestor of the existing checkout's `HEAD` but the commits are not equal
- **THEN** the installer reports the local-ahead state and fails without resetting or activating that checkout

#### Scenario: Existing checkout has diverged
- **WHEN** neither the existing checkout's `HEAD` nor the fetched authoritative commit is an ancestor of the other
- **THEN** the installer reports the divergence and fails without merging, resetting, or activating that checkout

### Requirement: Marketplace registration remains isolated and deterministic
After source verification and package validation succeed, the installer SHALL atomically replace only the `dev-flow-orchestrator` entry in a valid personal marketplace, SHALL preserve unrelated entries, and SHALL leave exactly one entry that resolves to the verified source checkout.

#### Scenario: Existing valid marketplace contains unrelated entries
- **WHEN** installation succeeds with a marketplace containing unrelated plugin entries and an older Dev Flow entry
- **THEN** unrelated entries remain unchanged and exactly one Dev Flow entry points to the verified source path

#### Scenario: Marketplace JSON is malformed
- **WHEN** the marketplace cannot be parsed as an object containing a plugins array
- **THEN** installation fails without replacing the malformed file or invoking plugin activation

### Requirement: Plugin activation failure is explicit and recoverable
The installer SHALL return a non-zero status when `codex plugin add` fails and SHALL print the manual remove-and-add recovery commands without rewriting or deleting the verified source checkout.

#### Scenario: Codex rejects plugin activation
- **WHEN** source verification, package validation, and marketplace registration succeed but `codex plugin add` exits unsuccessfully
- **THEN** the installer exits unsuccessfully and reports the manual recovery commands

### Requirement: Candidate validation covers installer authority boundaries

The candidate SHALL include standard-library behavior suites that invoke each supported host installer against isolated Git repositories, marketplaces, and Codex executables. The existing macOS suite SHALL continue to cover the complete established authority matrix. A focused Windows suite SHALL cover the native entry point, fresh installation, idempotent repair, one eligible fast-forward, dirty or otherwise ineligible source refusal, marketplace preservation and rejection, plugin activation failure, and the uninstall safety boundary. Focused CI and package validation SHALL include the applicable host suite and every required static lifecycle asset.

Validation SHALL NOT require either host to execute the other host's shell language, and the Windows suite SHALL NOT duplicate every established Git-history permutation merely for platform parity.

#### Scenario: Candidate installer behavior is validated

- **WHEN** focused validation runs on macOS
- **THEN** it retains the established fresh authoritative-ref selection, idempotent and fast-forward upgrades, dirty state, ignored-path collision, unexpected origin and branch, local-ahead and diverged histories, marketplace preservation and rejection, and plugin activation failure coverage

#### Scenario: Candidate installer behavior is validated on Windows

- **WHEN** focused validation runs on Windows
- **THEN** it executes the real PowerShell install and uninstall entry points against isolated dependencies and covers their representative success, refusal, preservation, and activation-failure paths

#### Scenario: A supported lifecycle asset is missing

- **WHEN** the candidate omits a required shell, PowerShell, launcher, or host behavior test asset
- **THEN** package validation fails before plugin installation

### Requirement: Public installation guidance states the authority boundary

Public English and Simplified Chinese installation documentation SHALL identify `main` as the installer's authoritative source ref, SHALL explain that automatic upgrades require the expected origin, a clean attached `main`, and fast-forward-only history, and SHALL provide the correct native installation and uninstallation entry points for every publicly supported host.

Windows guidance SHALL state the x64 client support boundary, native PowerShell and Git for Windows prerequisites, Hook `/hooks` review step, preserved task-data behavior, and explicit unsupported environments. macOS guidance SHALL retain its existing shell path. Neither language SHALL imply that installing a plugin automatically trusts its Hook.

#### Scenario: Operator reviews installation guidance

- **WHEN** an operator reads a public macOS installation entry point
- **THEN** the operator can determine which ref is installed, which checkout states require manual intervention, and how to review the bundled MCP server and tool catalog

#### Scenario: Windows operator reviews installation guidance

- **WHEN** an operator reads a public Windows installation entry point
- **THEN** the operator can identify the PowerShell command, supported host boundary, source authority, upgrade refusals, MCP approval boundary, CLI/Web commands, and uninstall data-preservation behavior

### Requirement: Supported host entry points apply one authoritative installation lifecycle

The product SHALL provide `scripts/install.sh` for supported macOS hosts and `scripts/install.ps1` for supported Windows x64 clients. Each entry point SHALL enforce the existing authoritative `main`, existing-checkout, package-validation, marketplace-isolation, and plugin-activation Requirements before reporting success. The Windows entry point SHALL use native PowerShell and ordinary Windows executables without requiring a POSIX compatibility layer.

Platform-specific syntax and presentation MAY differ, but neither entry point SHALL weaken source verification, mutate an ineligible checkout, replace a malformed marketplace, or report successful activation after a failed Codex command.

#### Scenario: Fresh Windows installation succeeds

- **WHEN** a supported Windows x64 client has the required tools, no source checkout, and a valid or absent personal marketplace
- **THEN** the PowerShell installer verifies the authoritative `main` candidate, registers exactly one marketplace entry, installs the plugin and owned CLI/MCP launchers, and emits a successful receipt with MCP review guidance

#### Scenario: Existing Windows installation is repaired or upgraded

- **WHEN** the existing Windows source is the expected clean attached `main` checkout and is equal to or behind the fetched authoritative commit
- **THEN** the installer leaves or fast-forwards it as applicable, validates it, reinstalls the plugin snapshot, and reports repair or upgrade accurately

#### Scenario: Windows source is ineligible

- **WHEN** the existing Windows source has an unexpected origin or branch, reported changes, local-ahead history, divergence, or an ignored-path collision with incoming `main`
- **THEN** installation fails without switching, resetting, stashing, cleaning, overwriting, registering, or activating that source

### Requirement: Windows uninstallation removes only validated installation assets

The product SHALL provide `scripts/uninstall.ps1` for supported Windows x64 clients. It SHALL remove the installed plugin when present and SHALL atomically remove only the Dev Flow entry from a valid personal marketplace while preserving unrelated entries. It SHALL preserve external Controller task data in all cases.

By default, it SHALL remove the source checkout only after validating the expected product, an allowed origin, attached `main`, no tracked, untracked, or ignored content, and no local-only commits. A keep-source option SHALL preserve the checkout. Any uncertainty about the source removal target SHALL fail closed and leave that source for manual handling.

#### Scenario: Ordinary Windows uninstall succeeds

- **WHEN** the plugin and marketplace entry exist and the source is a clean validated installer-managed checkout
- **THEN** the uninstaller removes those installation assets and reports that Controller task data was preserved

#### Scenario: Windows source contains user work

- **WHEN** the source has local changes, ignored content, local-only commits, an unexpected origin, or another unsafe identity
- **THEN** the uninstaller refuses to delete the source and reports the reason without deleting task data

#### Scenario: Keep source is requested

- **WHEN** the operator supplies the documented PowerShell keep-source option
- **THEN** plugin and marketplace removal may proceed while the source checkout remains unchanged
