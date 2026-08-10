## 1. Preserve the regressions

- [x] 1.1 Add real independent-process tests for task, membership, repository, and
  Web control lock contention, timeout, cancellation, post-acquire rejection,
  release recovery, mutation non-entry, and canonical multi-repository order.
- [x] 1.2 Add oversized, 100,000-level, boundary, escaped-string, strict-JSON,
  damaged-record, byte-preservation, candidate round-trip rejection, shared write
  gate, and mixed-inventory failure tests.

## 2. Bound POSIX lock acquisition

- [x] 2.1 Implement non-blocking POSIX acquisition with a monotonic 30-second
  deadline, bounded polling, stable timeout, cooperative cancellation, and a
  post-acquire cancellation/deadline linearization gate.
- [x] 2.2 Propagate cancellation through membership, canonical repository, and task
  locks without changing lock order or Windows-specific behavior.
- [x] 2.3 Map pre-commit timeout/cancellation through Controller, CLI, and MCP without
  completion-uncertain recovery or protected-path disclosure, including an
  acquired-but-rejected lock.

## 3. Bound and isolate state reads

- [x] 3.1 Add a 64 MiB product state limit and limit-plus-one POSIX regular-file
  reads before parsing, with one shared envelope for read bytes and final
  canonical candidate bytes before replacement.
- [x] 3.2 Add a 128-level JSON nesting scanner that handles strings, escapes, and
  Unicode, plus residual recursion conversion and symmetric write rejection.
- [x] 3.3 Isolate corrupt tasks behind bounded diagnostics while preserving healthy
  inventory and read-only bytes/filesystem behavior.

## 4. Verify the bounded change

- [x] 4.1 Run lock and Store focused tests, then directly affected integrity,
  controller, stale mutation, capture-to-commit, candidate-write, post-acquire,
  CLI, MCP, shared-lock Web, and read-only inspection tests.
- [x] 4.2 Run Phase 1 contract/replay/task-ID regression tests and freeze the
  implementation.
- [x] 4.3 Run complete unittest discovery once, package validation, every active
  OpenSpec strict validation, `git diff --check`, and one independent read-only
  review.
