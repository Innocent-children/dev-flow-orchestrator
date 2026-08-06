## ADDED Requirements

### Requirement: Windows admission and discovery share one canonical path comparison

On documented Windows x64 client systems, task admission, repository-path discovery, active membership leases, repository overlap, and controller-data separation SHALL use the same normalized host path comparison. Discovery SHALL match a path equal to or contained by any active member regardless of equivalent drive-letter case or separator spelling and SHALL return each matching task at most once.

The data root may be created after its canonical non-strict path is derived; repository roots SHALL already exist and SHALL still be validated as exact Git worktree roots before task state is created.

#### Scenario: Discovery uses a different Windows spelling

- **WHEN** the inspected current directory is beneath an active member but differs in drive-letter case or separator spelling
- **THEN** discovery returns the same active task

#### Scenario: Data root and repository are on different drives

- **WHEN** a valid local data root and valid local repository root are on different Windows drives
- **THEN** containment comparison treats them as disjoint without raising a path-comparison failure

#### Scenario: Repository is inside the data root

- **WHEN** the normalized Windows repository root equals or is contained by the normalized controller data root, or contains it
- **THEN** task creation fails before revision-zero state is written
