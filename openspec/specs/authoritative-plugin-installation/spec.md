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
The candidate SHALL include a macOS-only standard-library behavior suite that invokes the real installer against isolated Git repositories, marketplaces, and Codex executables. Focused CI and package validation SHALL include that suite and its static asset.

#### Scenario: Candidate installer behavior is validated
- **WHEN** focused validation runs on macOS
- **THEN** it covers fresh authoritative-ref selection, idempotent and fast-forward upgrades, dirty state, ignored-path collision, unexpected origin and branch, local-ahead and diverged histories, marketplace preservation and rejection, and plugin activation failure

### Requirement: Public installation guidance states the authority boundary
Public English and Chinese installation documentation SHALL identify `main` as the installer's authoritative source ref and SHALL explain that automatic upgrades require the expected origin, a clean `main` checkout, and fast-forward-only history.

#### Scenario: Operator reviews installation guidance
- **WHEN** an operator reads a public installation entry point
- **THEN** the operator can determine which ref is installed and which existing checkout states require manual intervention
