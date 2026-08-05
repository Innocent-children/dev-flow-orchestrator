# task-discovery-boundaries Specification

## Purpose
TBD - created by archiving change fix-v5-confirmed-defects. Update Purpose after archive.
## Requirements
### Requirement: Invalid task entries are isolated during discovery
Task inventory discovery SHALL continue loading healthy tasks when another candidate task directory has missing or invalid state. A direct operation on the invalid task SHALL remain a strict error.

#### Scenario: Healthy task and orphan directory coexist
- **WHEN** inventory contains one healthy task and one task directory without state
- **THEN** discovery returns the healthy task without failing the entire inventory

#### Scenario: Invalid task is addressed directly
- **WHEN** a caller explicitly loads the task whose state is missing or invalid
- **THEN** the existing task-specific error is returned

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

### Requirement: Active task discovery covers every member repository
Repository-path discovery SHALL match a non-terminal task when the inspected path equals or is contained by any canonical member repository root. Discovery SHALL return each matching task at most once. Valid 0.3.0 task creation SHALL prevent active worktree overlap, so a healthy current inventory SHALL produce at most one active match for a canonical member path. If persisted valid current task state nevertheless contains conflicting active membership, discovery SHALL report an explicit lease-integrity conflict and SHALL NOT choose one task implicitly. If a current-namespace entry cannot be validated, automatic discovery SHALL isolate and report it without injecting it as task authority, while task admission remains globally fail closed until the current lease inventory is valid. Terminal tasks remain excluded from automatic active discovery.

#### Scenario: Discovery isolates corrupt current state
- **WHEN** Hook discovery encounters a corrupt 0.3 task entry while inspecting a repository path
- **THEN** it injects no authority from that entry, exposes bounded diagnostics, and does not imply that its membership lease was released for a future start

#### Scenario: Hook starts in a secondary repository
- **WHEN** a Codex session starts at or below any non-first member repository of an active task
- **THEN** discovery returns that same task and the Hook can inject its one current projection

#### Scenario: One task has multiple matching roots
- **WHEN** a candidate path could otherwise match more than one member record of the same task
- **THEN** discovery returns the task once

#### Scenario: Valid active task overlap is detected
- **WHEN** inventory contains two valid non-terminal current tasks that claim the same canonical member despite admission enforcement
- **THEN** discovery reports a lease-integrity conflict with both task IDs and injects neither as implicit authority

#### Scenario: Multiple tasks cover the same path
- **WHEN** two non-terminal tasks include a repository that contains the inspected path
- **THEN** discovery retains both task identities and requires explicit task selection

#### Scenario: Matching task is terminal
- **WHEN** the only task containing the inspected path is terminal
- **THEN** automatic active-task discovery excludes it and the worktree is eligible for a new task admission

### Requirement: Task creation enforces one active membership lease
Task creation SHALL acquire one controller-data-directory membership lock, canonicalize and stably capture the complete requested repository set, and inspect every current-namespace task before revision-zero state is written. A canonical worktree root or worktree-specific Git administrative directory SHALL belong to at most one active task. Any conflict SHALL reject the entire start and identify the owning task and repository member. Lease authority SHALL be derived from persisted immutable membership plus a validated controller-confirmed terminal state and SHALL NOT use a separately editable lease ledger or an expiration timeout. A current-namespace entry whose membership or terminal state cannot be validated SHALL make the lease inventory unavailable and SHALL reject new task creation without inspecting prior-version namespaces, modifying the entry, or inferring lease release.

#### Scenario: Requested member belongs to another active task
- **WHEN** a caller starts a task with a repository root or worktree-specific Git directory already owned by a non-terminal task
- **THEN** task creation rejects the complete set, reports the owning task, and writes no new task state

#### Scenario: Owning task reaches terminal state
- **WHEN** the existing task reaches controller-confirmed `DONE`, `INCOMPLETE`, or `CANCELLED`
- **THEN** a later start may acquire that worktree after performing the complete current admission checks

#### Scenario: Two starts race for the same member
- **WHEN** concurrent starts request an overlapping canonical member
- **THEN** the membership lock permits exactly one revision-zero creation and the other receives the committed owner identity

#### Scenario: Concurrent work uses distinct worktrees
- **WHEN** a user supplies separate prepared worktrees with distinct canonical roots and worktree-specific Git directories, including linked worktrees that share one Git common directory
- **THEN** each valid repository set may be leased by its own active task

#### Scenario: Current inventory contains an unreadable task
- **WHEN** admission encounters any task entry in the 0.3 namespace whose immutable membership or controller-confirmed terminal state cannot be validated
- **THEN** it rejects the new start with lease-inventory diagnostics and writes no task state rather than treating the unreadable entry as terminal or unleased
