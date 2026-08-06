## ADDED Requirements

### Requirement: Candidate validation includes Windows product-integration assets proportionally

The candidate package SHALL require the Windows Hook command, `.cmd` Python launcher, PowerShell installer, PowerShell uninstaller, and focused Windows integration tests as current-product assets. It SHALL validate that every packaged command Hook retains its existing `command` and provides a non-empty `commandWindows`, that public bootstraps select the correct launcher, and that no Windows-specific product identity, Schema, namespace, workflow, package, or Web UI version is introduced.

Host-neutral validation SHALL inspect all static assets. Host-executed validation SHALL run POSIX lifecycle behavior on macOS and Windows launcher, Hook, lifecycle, Web UI, and installed-smoke behavior on Windows. The existing macOS focused job SHALL remain the broad product regression gate; Windows automation SHALL NOT duplicate every shared workflow, assurance profile, installed journey, Python minor, and boundary maximum.

#### Scenario: Complete Windows integration candidate is inspected

- **WHEN** package validation scans Hook configuration, launchers, lifecycle scripts, tests, manifests, runtime imports, and public documents
- **THEN** all required assets are present, paired host commands are valid, and all surfaces identify the same whole product

#### Scenario: Windows Hook override is missing

- **WHEN** one packaged command Hook lacks `commandWindows` or points to a missing launcher or handler
- **THEN** candidate validation fails before installation

#### Scenario: Platform test scope expands into a duplicated product matrix

- **WHEN** the candidate requires Windows to rerun every platform-neutral workflow and assurance permutation without a Windows-specific failure hypothesis
- **THEN** review reduces the matrix to platform adapters, one vertical installed journey, and one multi-repository smoke while preserving the main product suite

### Requirement: Installed Windows evidence proves the complete user path

The installed evidence SHALL contain one native Windows vertical journey from the immutable installed plugin snapshot. It SHALL cover verified source selection, personal marketplace registration, plugin activation, real Hook bootstrap execution, one representative Controller task through current assurance and Delivery Dossier completion, local read-only Web UI inspection, plugin removal, marketplace cleanup, and preserved task data.

A second shorter journey SHALL prove an exact two-repository task can be discovered and resumed from the non-first member and can obtain one current aggregate repository-set observation. Optional external drivers MAY report their existing available, degraded, or unavailable states and SHALL NOT become separate Windows installation requirements.

#### Scenario: Installed Windows vertical journey succeeds

- **WHEN** the candidate is installed on a supported Windows x64 client or equivalent installed test environment and its representative task completes
- **THEN** Hook, Controller, workflow, assurance, Dossier, Web UI, and lifecycle outputs all bind the same installed product snapshot

#### Scenario: Multi-repository recovery succeeds

- **WHEN** the installed Hook starts from the second member of an active two-repository task
- **THEN** it restores that task and the Controller derives the current aggregate evidence without substituting membership

#### Scenario: Uninstall follows the journey

- **WHEN** the installed journey invokes the Windows uninstaller after plugin use
- **THEN** plugin and marketplace installation assets are removed as authorized while Controller task data remains present

### Requirement: Public Windows support claims match tested consumer-client evidence

Before documentation labels native Windows support as delivered, release evidence SHALL include one complete Windows 11 x64 client install-to-uninstall journey. A Windows 10 22H2 x64 smoke SHALL cover installation, Hook launch, task resume, Web UI startup, and uninstallation before that client version is included in the public support claim. Evidence SHALL identify OS build, PowerShell, Python, Git, and Codex versions and the actual result.

GitHub-hosted Windows Server automation MAY satisfy continuous implementation checks but SHALL NOT by itself establish Windows Server support or replace consumer-client evidence. Every reproducible supported-client defect found during release validation SHALL receive one targeted regression test.

English and Simplified Chinese README, INSTALL, ARCHITECTURE, ROADMAP, and CONTRIBUTING documents SHALL agree on supported Windows clients, x64 and Python requirements, PowerShell commands, Hook trust, ordinary local repository scope, unsupported environments, Web UI behavior, validation limits, and no historical or cross-operating-system migration promise.

#### Scenario: Windows 11 client evidence passes

- **WHEN** the complete installed journey passes on a documented Windows 11 x64 client
- **THEN** the release may claim native Windows support within the stated boundary

#### Scenario: Only hosted Server automation exists

- **WHEN** CI passes on `windows-latest` but no supported consumer-client journey has been recorded
- **THEN** the candidate remains an implementation preview and public documentation does not claim completed client support

#### Scenario: Bilingual support guidance drifts

- **WHEN** English or Simplified Chinese guidance disagrees on a Windows command, supported host, Hook trust step, unsupported path, Web UI behavior, or validation limit
- **THEN** candidate documentation validation fails
