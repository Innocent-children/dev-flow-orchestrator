## Why

Managed Web lifecycle currently compresses every authenticated HTTP probe failure
into one false value and then treats false as proof that the managed process has
stopped. A transient timeout, 503 response, invalid temporary response, or endpoint
identity conflict can therefore discard live-instance state, start a duplicate
process, or report a stop without proving process death.

The parent also removes a failed startup reservation without first proving that the
exact child it created has exited, which can leave an orphan process.

## What Changes

- Classify managed runtime state from separate process-liveness, HTTP reachability,
  authentication, product identity, instance identity, and process identity facts.
- Distinguish `starting`, `running`, `unreachable`, `identity-conflict`, and
  `stopped` lifecycle outcomes.
- Expose exact managed instance identity and process PID through the existing
  authenticated, read-only metadata route.
- Make status observational and make start, stop, restart, and open fail closed
  when an instance is live but not exactly verifiable.
- Reap an owned startup child before removing its exact reservation; retain state
  when child death cannot be confirmed.
- Preserve bounded control locking and prevent concurrent starts from creating
  more than one managed child.
- Restrict signal-zero PID probing to POSIX hosts and treat unsupported process
  liveness as unknown, while allowing exact authenticated metadata to establish
  running or identity-conflict without a signal probe.
- Separate presentation authority from process mutation authority: exact
  authenticated metadata may support status, open, and duplicate-start
  prevention, but signalling a persisted PID additionally requires proven alive
  liveness.
- Give proven process death priority over every HTTP probe result and revalidate
  instance ID, PID, and death under the control lock before exact stale-state
  cleanup, without touching a service that reused the old port.

## Capabilities

### New Capabilities

- `macos-web-lifecycle`: exact-instance managed Web lifecycle classification and
  safe local process ownership.

## Impact

The change is limited to the POSIX/macOS managed Web lifecycle, authenticated
read-only metadata, direct CLI presentation, package validation, one OpenSpec
change, and Web lifecycle tests. It does not change task persistence, shared lock
implementation, MCP payloads, assurance, workflows, installer/runtime ownership,
model/release versions, namespace, or Windows-specific files and tests. The shared
non-POSIX path only contains the Phase 3 signal-zero regression; it does not add a
Windows process-liveness implementation.
