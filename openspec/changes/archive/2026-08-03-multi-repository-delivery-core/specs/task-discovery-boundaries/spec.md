## MODIFIED Requirements

### Requirement: Repository and data directory are disjoint
Starting a task SHALL require the controller data directory to be disjoint in both directions from every canonical target repository root. Repository-set validation SHALL also reject duplicate canonical roots and roots that contain one another before revision-zero state is written.

#### Scenario: Data directory is inside repository
- **WHEN** the controller data directory equals or is contained by any target repository
- **THEN** task creation fails before state is written and identifies the conflicting repository

#### Scenario: Repository is inside data directory
- **WHEN** any target repository equals or is contained by the controller data directory
- **THEN** task creation fails before state is written and identifies the conflicting repository

#### Scenario: Repository roots overlap
- **WHEN** two supplied paths resolve to the same canonical root or one canonical root contains another
- **THEN** task creation fails as an invalid exact repository set instead of silently removing or prioritizing a member

## ADDED Requirements

### Requirement: Active task discovery covers every member repository
Repository-path discovery SHALL match a non-terminal task when the inspected path equals or is contained by any canonical member repository root. Discovery SHALL return each matching task at most once and SHALL preserve explicit ambiguity when multiple active tasks cover the inspected path.

#### Scenario: Hook starts in a secondary repository
- **WHEN** a Codex session starts at or below any non-first member repository of an active task
- **THEN** discovery returns that same task and the Hook can inject its one current projection

#### Scenario: One task has multiple matching roots
- **WHEN** a candidate path could otherwise match more than one member record of the same task
- **THEN** discovery returns the task once

#### Scenario: Multiple tasks cover the same path
- **WHEN** two non-terminal tasks include a repository that contains the inspected path
- **THEN** discovery retains both task identities and requires explicit task selection

#### Scenario: Matching task is terminal
- **WHEN** the only task containing the inspected path is terminal
- **THEN** automatic active-task discovery excludes it
