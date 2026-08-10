## ADDED Requirements

### Requirement: Shared POSIX locks are bounded and cancellable

Every product operation that acquires the shared POSIX exclusive-file-lock
primitive SHALL use non-blocking acquisition with a monotonic deadline and bounded
polling. The production timeout SHALL be 30 seconds. Mutation call paths with an
existing cancellation check SHALL observe it while waiting. Lock authority SHALL
linearize only after successful OS acquisition is followed by cancellation and
deadline validation.

#### Scenario: A competing process retains a task lock

- **WHEN** an independent process retains a task lock beyond the configured test
  deadline
- **THEN** the contender returns `STATE_LOCK_TIMEOUT` within the bounded interval
- **AND** state bytes, revision, current node, and records remain unchanged
- **AND** the result is not completion-uncertain
- **AND** the operation succeeds after the holder releases the lock

#### Scenario: Cancellation arrives during lock waiting

- **WHEN** a mutation waits for a retained POSIX lock and its cancellation check is
  signalled
- **THEN** it exits promptly with cancellation semantics
- **AND** no state is written

#### Scenario: Cancellation wins after OS acquisition

- **WHEN** the OS lock becomes available after the final waiting check but
  cancellation is observed immediately after successful `flock`
- **THEN** the newly acquired lock is released without entering the critical
  section
- **AND** the mutation returns cancellation without a receipt or
  completion-uncertain classification
- **AND** a later operation can acquire the same lock

#### Scenario: Deadline expires as the OS lock becomes available

- **WHEN** `flock` succeeds but the post-acquire monotonic check finds the
  deadline exhausted
- **THEN** the contender releases the acquired lock and returns
  `STATE_LOCK_TIMEOUT`
- **AND** no critical-section state write occurs

#### Scenario: Canonical multi-repository acquisition

- **WHEN** independent operations present the same repositories in opposite order
- **THEN** both derive the same canonical lock order
- **AND** neither operation deadlocks

#### Scenario: Web control uses the shared primitive

- **WHEN** a Web control operation encounters a retained shared POSIX lock
- **THEN** acquisition is bounded without changing Web lifecycle state semantics

### Requirement: Persisted task state reads are bounded

The current task Store SHALL reject a POSIX `state.json` larger than 64 MiB before
unbounded allocation and SHALL reject JSON container nesting beyond 128 levels
before recursive decoding or model replay.

The Store SHALL apply the same persisted-state byte, UTF-8, strict-JSON, and
nesting envelope to canonical candidate bytes before every `state.json`
replacement. A successful current-version write SHALL therefore be readable by
the current standard load and replay path.

#### Scenario: State exceeds the byte limit

- **WHEN** a task state exceeds the configured byte ceiling
- **THEN** direct inspection fails closed with `STATE_LIMIT_EXCEEDED`
- **AND** the original file is not modified

#### Scenario: State exceeds the nesting limit

- **WHEN** state JSON contains excessive object or array nesting
- **THEN** direct inspection fails closed with `STATE_LIMIT_EXCEEDED`
- **AND** no `RecursionError` escapes
- **AND** braces, brackets, escapes, and Unicode inside strings do not count as
  nesting

#### Scenario: Candidate state exceeds the persisted envelope

- **WHEN** a live Controller action produces canonical candidate state whose
  bytes or nesting exceed the shared persisted-state envelope
- **THEN** the Store returns `STATE_LIMIT_EXCEEDED` before replacement
- **AND** state bytes, revision, node, status, and records remain unchanged
- **AND** no mutation receipt is produced
- **AND** the previous state remains readable

#### Scenario: Every replacement path shares one envelope gate

- **WHEN** task creation, an ordinary Store update, or a repository-bound
  mutation replaces `state.json`
- **THEN** its final canonical bytes pass the same persisted-state envelope used
  by reads before atomic replacement

#### Scenario: Existing over-limit state remains fail-closed

- **WHEN** an already persisted historical file exceeds the product envelope
- **THEN** inspection fails closed with a bounded diagnostic
- **AND** the Store does not migrate, truncate, or rewrite the file

### Requirement: Corrupt inventory entries are isolated

Inventory SHALL return every healthy task that can be validated and one bounded,
content-free diagnostic for each corrupt or over-limit task.

#### Scenario: Mixed healthy and corrupt task entries

- **WHEN** inventory contains healthy state plus oversized, deeply nested, invalid
  UTF-8, duplicate-key, non-finite-number, or structurally damaged state
- **THEN** healthy tasks remain available
- **AND** each corrupt task has an independent stable diagnostic
- **AND** diagnostics expose neither state content nor the data-root path
- **AND** inventory creates no lock, migration, or repair side effect

### Requirement: Existing storage compatibility is preserved

The repair SHALL preserve canonical lock order, revision CAS, capture-to-commit
authority, atomic replacement, persisted state shape and bytes, record/artifact
seals, `MODEL_VERSION`, namespace, and Phase 1 live/replay/task-ID behavior.

#### Scenario: Existing current state is read

- **WHEN** a legal current or historical-compatible `0.4.x` task is inspected
- **THEN** it loads without migration or rewrite
- **AND** persisted bytes remain identical

#### Scenario: Historical confidence replay remains compatible

- **WHEN** a Phase 1 historical-compatible state contains a non-enum confidence
  value within the persisted-state envelope
- **THEN** replay derives conservative `unknown` confidence
- **AND** live non-enum confidence remains strictly rejected
- **AND** read-only replay does not alter state bytes

### Requirement: Storage failures have safe adapter recovery

MCP and CLI SHALL expose stable storage-domain failures without leaking protected
paths or converting a pre-commit lock timeout into completion-uncertain recovery.

#### Scenario: MCP mutation times out before lock acquisition

- **WHEN** a mutation receives `STATE_LOCK_TIMEOUT` before entering its write
  interval
- **THEN** MCP returns that domain code with `retry-later` recovery
- **AND** `blind_retry` is true
- **AND** no lock path or data root is exposed

#### Scenario: MCP direct inspection finds corrupt state

- **WHEN** `dev_flow_get_task` encounters invalid or over-limit state
- **THEN** it returns the stable domain error with inspect-diagnostics recovery
- **AND** it does not return an MCP internal error

#### Scenario: MCP rejects an over-limit candidate before commit

- **WHEN** an action would produce candidate state beyond the shared persisted
  envelope
- **THEN** MCP returns the stable state-limit domain error with non-blind
  current-action recovery
- **AND** it does not return completion-uncertain
