## Context

The existing lifecycle asks `_probe_runtime()` for a boolean. That boolean combines
process existence, network reachability, authentication, product identity, and
instance identity even though those facts have different safety meanings. The
callers consequently perform destructive cleanup after a single failed request.

The existing Phase 2 bounded `control.lock` remains the lifecycle mutation
authority and is not modified.

## Goals / Non-Goals

**Goals:**

- Centralize runtime classification with explicit stopped, starting, running,
  unreachable, and identity-conflict outcomes.
- Require an authenticated product, managed instance, and process PID match before
  declaring an exact running instance, and additionally require proven alive
  liveness before sending a signal.
- Keep state byte-identical when a live instance is unreachable or conflicts.
- Allow stale-state cleanup only after process death is established and the exact
  state identity is rechecked under the control lock.
- Reap the exact child owned by a failed start before cleaning its reservation.
- Preserve one-child admission under concurrent starts.
- Keep signal-zero liveness probing behind an explicit POSIX capability boundary;
  unsupported hosts remain unknown and fail closed.
- Treat proven process death as terminal before HTTP probing, and bind stale-state
  cleanup to the expected instance ID, PID, and revalidated death.

**Non-Goals:**

- Add HTTP mutation or remote management routes.
- Change Web task views, Store bounds, POSIX lock implementation, MCP payloads,
  workflows, assurance, installer/runtime, versions, namespaces, or Windows.

## Decisions

### 1. Classification keeps liveness, reachability, and identity separate

A single classifier reads a validated runtime state and keeps process liveness
tri-state: alive, dead, or unknown. Signal-zero probing is reachable only when the
host explicitly supports POSIX non-destructive semantics. `ProcessLookupError`
proves death; `PermissionError` proves that a process exists without granting
signal authority; other POSIX errors and every unsupported host are unknown.

Connection failures, timeouts, 503, and temporarily undecodable responses are
unreachable, never stopped. Authenticated metadata with the wrong product,
managed instance, or PID is identity-conflict. Running is emitted only when every
identity matches. Proven process death is terminal and returns stopped before any
HTTP probe, because a responder on the old port cannot belong to the dead PID. For
alive or unknown running state, exact authenticated metadata can directly
establish running or identity-conflict. The classification retains both probe and
liveness evidence so presentation status cannot be mistaken for process mutation
authority. A starting reservation with a live PID stays starting; unknown
starting state is unreachable.

### 2. Authenticated metadata identifies the exact server process

The existing `/api/meta` GET response adds a bounded read-only runtime object with
`managed`, `instance_id`, and `pid`. Managed workers receive their reservation
instance ID at server construction. Standalone servers explicitly return
`managed: false` and a null instance ID. Bearer, Host, Origin, CSP, loopback, and
the closed mutation-method surface remain unchanged.

### 3. Lifecycle mutations fail closed

Status only observes. Start returns an exact running instance, rejects starting or
unreachable state, rejects identity conflict, and only removes state after process
death is proven and the instance ID and PID are rechecked under the control lock.
The shared stale-cleanup gate repeats classification so death must remain proven;
a replacement state aborts cleanup before child creation.

Stop sends SIGTERM only after exact running identity and independently proven
alive liveness are classified under the lock. `running` presentation status alone
never authorizes a signal. It waits outside the lock so the child can perform its
own exact cleanup, then reacquires the lock and removes only the same dead
instance. Unknown liveness, unreachable state, and identity conflict are retained
without signalling. Restart composes safe stop and safe start. Open accepts exact
running presentation state without acquiring signal authority.

### 4. Failed startup retains process ownership

The parent keeps the `Popen` object. On readiness failure it terminates and waits
for that exact child, escalates to `Popen.kill()` only after a bounded timeout, and
waits again. It removes the reservation only after confirmed exit and an exact
instance recheck. If death cannot be confirmed, state remains and the error does
not claim stopped, preventing blind duplicate start.

### 5. Unsupported liveness fails closed without adding Windows functionality

On non-POSIX hosts the shared classifier never calls `os.kill(pid, 0)` and returns
unknown liveness. A failed exact probe therefore leaves state untouched and makes
status unreachable; start, stop, restart, and open fail through the existing
unreachable gate without creating a child or signalling a PID. This containment
does not add a Windows PID-query helper or change Windows product claims.

When exact authenticated metadata succeeds with unknown liveness, status and open
may present the verified running instance and start may prevent a duplicate.
Stop and restart still fail closed because the persisted PID lacks independent
alive evidence; they retain state and send no signal.

The `Popen` object retained by a start attempt is separate exact-child authority.
Its bounded poll, wait, terminate, and kill cleanup remains available on every
host and does not depend on the shared PID-liveness capability.

### 6. Reused ports cannot revive dead persisted instances

When a persisted PID is proven dead, the classifier does not contact the old port.
Status is stopped, open fails, and stop only cleans the exact stale state. Start or
restart may clean that state and create one new child. A service occupying the old
port remains unrelated and untouched; if the caller explicitly reuses that fixed
port, only the new child fails to bind and its exact `Popen` cleanup applies.

## Risks / Trade-offs

- A live process whose endpoint cannot be verified requires explicit inspection or
  later status retry; automatic duplicate recovery is intentionally refused.
- A reused PID may retain state conservatively until identity conflict or process
  death can be established. This favors avoiding signals to unrelated processes.
- Stop cannot use the worker's state deletion as the sole death proof; process
  liveness remains authoritative.
- Unsupported hosts cannot infer stopped from PID state; when exact HTTP identity
  is unavailable they retain runtime state for later inspection.
- Exact HTTP identity proves the responding instance, but cannot by itself
  authorize signalling a persisted PID on a host without safe liveness evidence.
- Port reuse may prevent a new fixed-port bind, but cannot change proven death or
  turn an unrelated responder into the old managed instance.
