## ADDED Requirements

### Requirement: Lite execution has no workflow-specific approval placement
The package-owned `lite@4` graph SHALL enter its real execution target directly
after successful preflight. For one repository the target SHALL be `implement`
with status `IMPLEMENTING`; for multiple repositories the target SHALL be
`repository-plan` with status `ORCHESTRATING`. The Lite graph MUST NOT contain
`lite-approval`, `gate.lite.approve` or an equivalent workflow-specific human
gate.

#### Scenario: Preflight one Lite repository
- **WHEN** a `lite@4` task with one repository completes preflight
- **THEN** its next node is `implement` and no confirmation request is created for Lite entry

#### Scenario: Preflight multiple Lite repositories
- **WHEN** a `lite@4` task with multiple repositories completes preflight
- **THEN** its next node is the shared `repository-plan` and no full-only or Lite-approval node is introduced

#### Scenario: Run the Full workflow
- **WHEN** a `full@4` task reaches its declared plan approval
- **THEN** the full gate remains authority-required through durable conversation confirmation

#### Scenario: Inspect workflow identity
- **WHEN** package validation derives current full and Lite identities
- **THEN** the removed Lite placement changes only the declared Lite graph and topology entry while every reachable node remains contract-complete
