## ADDED Requirements

### Requirement: Repository-dependent mutations use one containment protocol

Every repository-dependent apply, contract revision, decision, finding disposition,
cancellation, and non-cancelled finalization SHALL use one Controller/Store commit
protocol. It SHALL acquire the current-namespace membership lock, canonically sorted
repository authority locks, and task lock in that order and hold them through the
post-write observation.

After reloading task authority and validating revision compare-and-swap, the protocol
SHALL capture the exact complete repository set and resource request as `S`, derive
and validate a pure candidate exclusively from `S`, and capture the identical
authority again as `S'` immediately before replacement. Candidate derivation SHALL
perform no external effect. If `S' != S`, the operation SHALL fail with bounded
`SNAPSHOT_UNSTABLE` diagnostics before persistence, return no successful receipt,
and leave revision, ledger, node, status, and repository membership unchanged. It
SHALL NOT retry a non-idempotent mutation automatically.

Equality proves authority only at the `S'` observation point. Every pure candidate
and commit authorization SHALL use `S`. An existing repository-backed or terminal
record whose schema carries repository evidence SHALL bind that evidence to `S`,
while a governance decision record whose existing schema uses `snapshot: null`
SHALL remain null and SHALL NOT gain a new persisted snapshot field in this phase.
No durable record SHALL represent permanent workspace currentness. Atomic
replacement SHALL be followed by a new complete observation used for the mutation
response. A non-cooperating external writer may still change the worktree between
`S'` and replacement, so this protocol is containment rather than an absolute
cross-filesystem transaction.

#### Scenario: Drift is detected between candidate capture and revalidation

- **WHEN** a tracked path or any member identity changes after `S` is returned but
  before `S'` is captured
- **THEN** `S' != S`, the mutation fails before replacement, no success receipt is
  returned, and the stored task remains byte-for-byte at its prior revision

#### Scenario: Governance mutation loses pre-write authority

- **WHEN** the same detected mismatch occurs during contract revision, decision, or
  finding disposition
- **THEN** the selected mutation fails atomically and a later authoritative read can
  safely continue from the unchanged task

#### Scenario: Cancellation loses pre-write authority

- **WHEN** a workflow-authorized cancellation observes `S' != S`
- **THEN** it leaves the task active at the same revision and does not release its
  repository membership through a terminal transition

#### Scenario: One member of a larger set changes before revalidation

- **WHEN** any non-first member of a multi-repository set changes between `S` and
  `S'` while all other members remain stable
- **THEN** the aggregate mutation fails and no per-member or task result is committed

#### Scenario: Drift occurs in the residual pre-replace interval

- **WHEN** a deterministic fault changes a repository after `S'` and before atomic
  replacement
- **THEN** historical task evidence may commit, but the response never derives
  currentness from `S` or `S'`; a post-write observation reports false when it sees
  the drift or unknown when it cannot make a valid observation

### Requirement: Commit lock order is canonical and cross-process safe

The exact acquisition order SHALL be membership lock, repository authority locks
sorted by a canonical byte-stable key, then task lock. Repository lock identity
SHALL derive from the canonical worktree root and worktree-specific Git directory
identity after host-platform canonicalization, including Windows path semantics. It
SHALL NOT depend on caller spelling, caller repository order, or a caller-selected
repository identifier.

The membership lock SHALL remain held while repository identities are selected and
through the entire commit protocol. Repository locks serialize cooperating Dev Flow
processes that touch the same worktree; they SHALL NOT be described as mandatory
locks on arbitrary editors or Git processes. Every exit SHALL release locks in
reverse order after capture, derivation, cancellation, validation, write, or
post-write observation outcomes. No path SHALL acquire an earlier lock while holding
a later lock.

#### Scenario: Opposite repository input orders contend

- **WHEN** two processes or threads present the same repositories in opposite orders
- **THEN** both derive the same lock identities and acquisition order, complete or
  fail within bounded time, and do not deadlock

#### Scenario: Two processes target the same task

- **WHEN** two repository-dependent mutations contend for one task
- **THEN** at most one revision compare-and-swap commits and the loser receives the
  fresh conflict result after every acquired lock is released

#### Scenario: A protocol phase fails

- **WHEN** lock acquisition, capture, candidate validation, cancellation,
  replacement, or observation fails
- **THEN** all acquired locks are released in reverse order and a later operation
  can acquire them normally

### Requirement: Committed mutation responses separate commit and freshness

Once atomic replacement succeeds, the mutation SHALL remain classified as committed
even when post-write observation finds drift or fails. The receipt SHALL include the
committed revision, an explicit committed state, a versioned workspace-freshness
object with status `true`, `false`, or `unknown`, `blind_retry=false`, and bounded
read-after-write recovery guidance.

Freshness `true` SHALL require a successful post-write complete observation equal to
`S`. Freshness `false` SHALL require a successful differing observation and bounded
reasons. Freshness `unknown` SHALL mean no valid post-write observation is available.
The latter two outcomes SHALL NOT be surfaced as ordinary mutation failures and
SHALL NOT roll back a committed task. A caller SHALL be directed to read current
authority before another mutation.

#### Scenario: Post-write drift is observed

- **WHEN** replacement succeeds and the post-write observation differs from `S`
- **THEN** the receipt reports committed state and freshness false, forbids blind
  retry, and the returned Dossier does not claim currentness

#### Scenario: Post-write observation is unavailable

- **WHEN** replacement succeeds but the new complete observation fails
- **THEN** the receipt reports committed state and freshness unknown, preserves the
  committed revision, forbids blind retry, and provides read-after-write recovery

#### Scenario: Response is lost after replacement

- **WHEN** process or transport failure prevents delivery after atomic replacement
- **THEN** completion is treated as uncertain and recovery reads current task
  authority rather than blindly replaying the non-idempotent mutation
