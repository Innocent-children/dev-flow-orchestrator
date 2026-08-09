## Purpose

Replace automatic Hook context injection with explicit bounded MCP discovery while
preserving current inventory isolation, path canonicalization, active membership
leases, ambiguity handling, and fail-closed admission.

## MODIFIED Requirements

### Requirement: Active task discovery covers every member repository

Repository-path discovery SHALL match a non-terminal task when the inspected path
equals or is contained by any canonical member repository root. Discovery SHALL
return each matching task at most once. Valid model `0.4.0` task creation SHALL
prevent active worktree overlap, so a healthy current inventory SHOULD produce at
most one active match for a canonical member path.

The installed MCP product SHALL expose this behavior through
`dev_flow_find_tasks_for_path`. The tool SHALL return a closed classification of
`none`, `single`, `ambiguous`, or `inventory-unavailable`, bounded task identities,
and current inventory diagnostics. It SHALL NOT inject hidden authority into the
session, select an ambiguous task, create a task, or create a live action binding by
default. A caller SHALL explicitly select the returned task ID and obtain its current
action before mutation.

If persisted valid current task state nevertheless contains conflicting active
membership, discovery SHALL report an explicit lease-integrity conflict and SHALL
NOT choose one task implicitly. If a current-namespace entry cannot be validated,
discovery SHALL isolate and report it without treating it as task authority or
released membership; task admission SHALL remain globally fail closed until the
current lease inventory is valid. Terminal tasks SHALL remain excluded from active
automatic matching.

#### Scenario: MCP discovery isolates corrupt current state

- **WHEN** `dev_flow_find_tasks_for_path` encounters a corrupt model `0.4.0` task entry while inspecting a repository path
- **THEN** it returns no authority from that entry, exposes bounded diagnostics, and does not imply that its membership lease was released

#### Scenario: MCP discovery starts in a secondary repository

- **WHEN** a client supplies a path at or below any non-first member repository of one active task
- **THEN** discovery returns that same task once and the caller can explicitly request its current action

#### Scenario: One task has multiple matching roots

- **WHEN** a candidate path could otherwise match more than one member record of the same task
- **THEN** discovery returns that task once

#### Scenario: Valid active task overlap is detected

- **WHEN** inventory contains two valid non-terminal current tasks that claim the same canonical member despite admission enforcement
- **THEN** discovery reports a lease-integrity conflict with both task IDs and selects neither as implicit authority

#### Scenario: Multiple tasks cover the inspected path

- **WHEN** multiple non-terminal tasks are returned for a path because of persisted conflicting state or another current ambiguity
- **THEN** discovery reports `ambiguous`, retains all bounded task identities, and requires explicit operator resolution

#### Scenario: Matching task is terminal

- **WHEN** the only task containing the inspected path is `DONE`, `INCOMPLETE`, or `CANCELLED`
- **THEN** active discovery returns `none` and the worktree may be considered for a new task only after complete admission checks

#### Scenario: Discovery is requested with a different Windows spelling

- **WHEN** the inspected Windows path differs from an active member only by supported drive-letter case, separator, or redundant-component spelling
- **THEN** discovery uses the existing canonical comparison and returns the same active task

#### Scenario: Discovery has no match

- **WHEN** the canonical path is outside every healthy non-terminal member
- **THEN** the tool returns `none` without starting a task or acquiring a membership lease
