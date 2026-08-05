## ADDED Requirements

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

## MODIFIED Requirements

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
