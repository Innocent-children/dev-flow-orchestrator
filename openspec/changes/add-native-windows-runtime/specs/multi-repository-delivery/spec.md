## ADDED Requirements

### Requirement: Windows exact-set membership uses the canonical host path rule

On documented Windows x64 client systems, repository admission SHALL canonicalize every supplied local worktree root through the native Windows runtime path rule before deriving repository IDs, sorting members, checking duplicate roots, checking ancestor/descendant overlap, comparing controller-data separation, or acquiring active membership leases.

This Windows rule SHALL preserve the existing one-to-eight-member, order-insensitive, immutable exact-set model and SHALL add no platform-specific fields to `TaskState.repositories`.

#### Scenario: Caller order and Windows spelling differ

- **WHEN** two starts supply the same distinct Windows worktrees in different caller orders and use equivalent drive-case or separator spellings
- **THEN** both derive the same canonical member order and repository-set identity

#### Scenario: Windows members overlap

- **WHEN** one canonical Windows worktree root equals or contains another member root or the controller data root
- **THEN** task creation rejects the complete set before state is written

### Requirement: Windows aggregate capture retains all-or-none repository evidence

Repository-backed operations for Windows members SHALL capture the same current repository-set wrapper and one validated member snapshot per canonical task member. The controller SHALL retain its two complete aggregate capture passes and SHALL compare normalized Windows root, worktree Git directory, and common Git directory identities against immutable membership.

A failure or change in any Windows member SHALL fail the complete repository-set operation without committing early-member evidence.

#### Scenario: Two stable Windows members are captured

- **WHEN** both complete passes produce equal valid snapshots for every member
- **THEN** the controller accepts one canonical repository-set snapshot through the existing mutation path

#### Scenario: A later Windows member fails

- **WHEN** an earlier member is captured but a later member is missing, invalid, over budget, or unstable
- **THEN** the controller appends no record and retains no partial member evidence
