## Context

Current POSIX locking calls `flock(LOCK_EX)` and therefore has no point at which a
deadline or existing MCP cancellation check can be observed. Current state reads
call an unbounded `read()` and enter Python's recursive JSON decoder before any
nesting policy is enforced. Inventory catches ordinary domain and OS failures but
not recursion failures.

The repair must preserve the established lock order:

```text
membership -> canonical sorted repository authority locks -> task lock
```

It must also preserve the capture-to-commit interval, revision CAS, atomic
replacement, immutable workflow identity, and historical `0.4.x` replay.

## Goals / Non-Goals

**Goals:**

- Bound every shared POSIX exclusive-lock acquisition at 30 seconds in production,
  with 50ms-or-shorter final polling and a monotonic deadline.
- Allow existing mutation cancellation checks to abort lock waiting before any
  state replacement.
- Bound current task state to 64 MiB and JSON container nesting to 128 levels.
- Return healthy inventory entries alongside one sanitized diagnostic per corrupt
  task.
- Preserve original state bytes on every successful and failed read.

**Non-Goals:**

- Redesign Web running/unreachable/stopped lifecycle behavior.
- Change Windows locking, path handling, tests, or support claims.
- Change installer, uninstaller, managed runtime, payload contracts, assurance,
  workflows, persisted JSON shape, model version, namespace, or release version.

## Decisions

### 1. POSIX acquisition is non-blocking and pre-commit

The shared primitive uses `LOCK_EX | LOCK_NB`. On contention it checks cooperative
cancellation, compares `time.monotonic()` with a fixed deadline, and sleeps only up
to the smaller of the poll interval and remaining duration. Exhausting the deadline
raises `STATE_LOCK_TIMEOUT` without lock-path details. A truthy cancellation check
raises `REQUEST_CANCELLED`; a check that raises the adapter's existing cancellation
exception is propagated unchanged.

Successful `flock` alone does not transfer lock authority. The primitive records
cleanup ownership of the raw OS lock, then checks cancellation first and the
monotonic deadline second. Only after both pass does it enter the context body;
this combined point is the lock-authority linearization point. Failure releases
the acquired flock and closes the descriptor without exposing the critical
section.

TaskStore passes the same cancellation check through membership, sorted repository,
and task lock acquisition for mutation admission and repository commits. No lock
order changes. Because timeout/cancellation occurs before the relevant context is
entered and before `_atomic_write`, recovery may safely be `retry-later` with blind
retry for timeout, while cancellation retains existing cancellation semantics.

The Windows branch is left structurally and behaviorally unchanged. Web start,
stop, and worker code is not edited; its existing calls inherit the bounded shared
POSIX primitive.

### 2. Reads and candidate writes share one persisted-state envelope

The 64 MiB limit is intentionally well above ordinary current `0.4.x` states and
the 64 KiB action-payload budget, while still placing a firm per-task allocation
ceiling. POSIX reads reject an already oversized regular file from `fstat`, then
read at most limit-plus-one bytes to handle concurrent growth safely.

After strict UTF-8 decoding, a single-pass scanner tracks quoted strings, escapes,
and matching object/array delimiters. It rejects depth above 128 before `json.loads`
and never counts brackets inside strings. Residual `RecursionError` from decoding
or model replay is converted to a stable state-domain error.

The same envelope routine validates final canonical candidate bytes before
`atomic_write_bytes` can create and replace a temporary file. It owns the byte
ceiling, UTF-8 decoding, nesting scanner, strict JSON parsing, and recursion error
conversion for both directions. `_atomic_write` is the single replacement gate,
so creation, ordinary Store updates, and repository-bound mutations cannot bypass
it. Candidate failures use `STATE_LIMIT_EXCEEDED` with a bounded
`candidate-write` phase marker, leave the previous bytes unchanged, and produce no
receipt.

Existing files are never rewritten merely because they are read. Historical
states inside the envelope continue through the Phase 1 replay rules, including
conservative normalization of historical non-enum confidence. Already persisted
files outside the envelope remain fail-closed and diagnostic-only; the repair does
not migrate, truncate, or loosen the product limits.

### 3. Inventory corruption remains task-local and bounded

Read-only inventory catches the bounded family of state corruption failures per
entry. Diagnostics contain only a stable code and validated task ID (or a truncated
entry name), never state bytes, exception text, or the data-root path. CLI list and
MCP inventory expose those diagnostics while continuing to return healthy tasks.

## Risks / Trade-offs

- A legitimately held lock longer than 30 seconds causes a retryable timeout; the
  value is deliberately much longer than normal critical sections and tests inject
  a shorter value without changing production policy.
- The byte ceiling rejects pathological legacy tasks rather than attempting an
  unbounded replay. The 64 MiB allowance is conservative for current legal states
  and does not change their schema or identity.
- A live payload can satisfy its action schema yet still make the complete state
  envelope too deep; rejecting the final canonical candidate preserves round-trip
  readability without changing payload contracts or persisted shape.
