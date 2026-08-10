## Why

The shared POSIX file lock blocks indefinitely when another process retains a
membership, repository, task, or Web control lock. Persisted task state is also
read without a byte limit or a pre-parse nesting guard, so one oversized or deeply
nested task can exhaust an inventory operation and prevent healthy tasks from
being returned.

## What Changes

- Acquire shared POSIX exclusive locks with non-blocking attempts, a monotonic
  deadline, bounded polling, and cooperative cancellation.
- Return stable pre-commit timeout and cancellation errors without writing state
  or classifying the result as completion-uncertain.
- Validate cancellation and deadline again after successful POSIX acquisition and
  release an acquired-but-invalid lock before critical-section entry.
- Bound POSIX `state.json` reads before allocation and apply the same byte/depth
  envelope to final canonical candidate bytes before every state replacement.
- Prevent a successful current mutation from creating state that the current
  version cannot subsequently load and replay.
- Isolate each corrupt task behind a bounded, content-free inventory diagnostic.
- Map the new domain errors through CLI and MCP recovery without changing Web
  lifecycle behavior or any Windows-specific implementation.

## Capabilities

### New Capabilities

- `macos-storage-reliability`: bounded POSIX lock acquisition and bounded,
  corruption-isolating current-task state reads.

## Impact

The change is limited to the shared POSIX storage primitive, TaskStore lock/read/write
call paths, required Controller/CLI/MCP error propagation, package validation, and
directly corresponding tests. It does not alter persisted state shape, record or
artifact seals, model/release versions, namespace, workflow or assurance behavior,
Web lifecycle semantics, installer/runtime code, or Windows-specific code/tests.
