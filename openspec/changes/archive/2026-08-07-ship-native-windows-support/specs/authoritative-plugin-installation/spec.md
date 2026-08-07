## ADDED Requirements

### Requirement: Supported host entry points apply one authoritative installation lifecycle

The product SHALL provide `scripts/install.sh` for supported macOS hosts and `scripts/install.ps1` for supported Windows x64 clients. Each entry point SHALL enforce the existing authoritative `main`, existing-checkout, package-validation, marketplace-isolation, and plugin-activation Requirements before reporting success. The Windows entry point SHALL use native PowerShell and ordinary Windows executables without requiring a POSIX compatibility layer.

Platform-specific syntax and presentation MAY differ, but neither entry point SHALL weaken source verification, mutate an ineligible checkout, replace a malformed marketplace, or report successful activation after a failed Codex command.

#### Scenario: Fresh Windows installation succeeds

- **WHEN** a supported Windows x64 client has the required tools, no source checkout, and a valid or absent personal marketplace
- **THEN** the PowerShell installer verifies the authoritative `main` candidate, registers exactly one marketplace entry, installs the plugin, and emits a successful receipt with Hook review guidance

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

## MODIFIED Requirements

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
- **THEN** the operator can determine which ref is installed, which checkout states require manual intervention, and how to review the installed Hook

#### Scenario: Windows operator reviews installation guidance

- **WHEN** an operator reads a public Windows installation entry point
- **THEN** the operator can identify the PowerShell command, supported host boundary, source authority, upgrade refusals, Hook trust handoff, Web UI command, and uninstall data-preservation behavior
