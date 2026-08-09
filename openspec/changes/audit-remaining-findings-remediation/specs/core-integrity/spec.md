## ADDED Requirements

### Requirement: Source actions retain complete repository change evidence

The system SHALL compare the before and after Git trees when HEAD changes on the same
branch and repository/worktree authority, merge that committed delta with final dirty
changes, and fail closed on authority, branch, or unreadable-tree drift.

#### Scenario: A clean action creates a commit

- **WHEN** a source-producing action begins and ends clean but changes HEAD
- **THEN** add, modify, delete, rename, mode, symlink, and final merge-tree changes SHALL
  be present in the task manifest and its assurance, review, and delivery projections

#### Scenario: A commit is followed by dirty work

- **WHEN** the action commits changes and then stages, modifies, or creates more paths
- **THEN** committed and dirty deltas SHALL both be retained without losing either source

#### Scenario: Repository authority changes

- **WHEN** branch, worktree, or common repository authority differs from the baseline
- **THEN** the action SHALL fail without advancing revision or writing an empty manifest

### Requirement: Review impact closure uses complete typed locators

The system SHALL compare canonical values for every existing locator discriminator,
including repository, kind, path, symbol, location label, resource, and integration.

#### Scenario: A pathless locator differs

- **WHEN** an affected finding differs by symbol, label, resource, integration, or
  repository, or cannot be unambiguously normalized
- **THEN** it SHALL be an impact gap and re-enter planning as `triage-required`

#### Scenario: Complete locators match

- **WHEN** every canonical locator discriminator is equal
- **THEN** the finding MAY follow the existing closure-internal rework path

### Requirement: Active repository leases remain unique

Every repository-dependent public projection and mutation SHALL, under the established
membership → canonical repository locks → task order, prove the current task is the
only active owner of each repository worktree/common-dir authority.

#### Scenario: Conflicting active inventory exists

- **WHEN** two stored active tasks claim the same authority
- **THEN** projection SHALL expose no executable action or binding and mutation SHALL
  fail with `LEASE_INTEGRITY_CONFLICT` without state change

#### Scenario: A terminal task shares the authority

- **WHEN** only a terminal task also names the authority
- **THEN** the active task SHALL not be treated as lease-conflicted
