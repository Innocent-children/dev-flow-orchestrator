## ADDED Requirements

### Requirement: Managed Web runtime classification is explicit

The managed Web controller SHALL classify runtime state using separate state
validity, tri-state process liveness, HTTP reachability, Bearer authentication,
product identity, managed instance identity, and process PID facts. A failed HTTP
probe alone SHALL NOT prove that the process stopped. Signal-zero PID probing SHALL
be reachable only on hosts with explicit POSIX non-destructive semantics.

#### Scenario: A live managed PID is temporarily unreachable

- **WHEN** valid running state names a live PID but its endpoint times out, refuses
  a connection, returns 503, or cannot temporarily be decoded
- **THEN** status reports `unreachable`
- **AND** state bytes and process ownership data remain unchanged
- **AND** status neither signals nor starts a process

#### Scenario: A starting reservation names a live PID

- **WHEN** state is `starting` and its PID exists
- **THEN** classification remains `starting`
- **AND** another start does not create a child

#### Scenario: Process death is proven

- **WHEN** POSIX liveness returns `ProcessLookupError` for the state PID
- **THEN** classification is `stopped`
- **AND** no HTTP response on the old port can override proven death
- **AND** cleanup may remove only that exact stale instance under the control lock

#### Scenario: Process liveness capability is unavailable

- **WHEN** the host does not support non-destructive signal-zero PID probing
- **THEN** process liveness is `unknown` without calling `os.kill(pid, 0)`
- **AND** a failed exact probe is `unreachable`, never `stopped`
- **AND** runtime state remains unchanged

#### Scenario: Unknown liveness still has exact authenticated evidence

- **WHEN** liveness is `unknown` and authenticated metadata exactly matches the
  product, managed instance ID, and state PID
- **THEN** classification is `running`
- **AND** status and open may return the existing verified instance
- **AND** start treats it as an existing instance and creates no child
- **AND** presentation status does not grant process signal authority

#### Scenario: Unknown liveness has conflicting authenticated evidence

- **WHEN** liveness is `unknown` and authenticated metadata conflicts on product,
  managed instance ID, or PID
- **THEN** classification is `identity-conflict`
- **AND** it is not downgraded to ordinary unreachable

### Requirement: Authenticated metadata proves exact managed identity

The existing authenticated read-only metadata route SHALL return product identity,
managed instance ID, and current server PID without exposing data roots, task
content, tokens, command lines, or mutation authority.

#### Scenario: Exact managed endpoint responds

- **WHEN** Bearer authentication succeeds for a managed worker
- **THEN** metadata identifies the product, reservation instance ID, and worker PID
- **AND** running classification requires exact equality with state

#### Scenario: Standalone endpoint responds

- **WHEN** the foreground Web server serves metadata
- **THEN** it explicitly identifies itself as unmanaged
- **AND** it cannot satisfy a managed-state identity check

#### Scenario: Endpoint identity conflicts

- **WHEN** the endpoint returns a wrong product, instance ID, PID, or authenticated
  service identity
- **THEN** classification is `identity-conflict`
- **AND** start creates no child, stop sends no signal, and state is retained

### Requirement: Managed lifecycle commands preserve authority

Status SHALL observe without mutation. Start, stop, restart, and open SHALL use the
explicit classification and the existing bounded control lock without destructive
decisions based only on reachability. Process signal authority SHALL require both
exact authenticated identity and independently proven `alive` liveness; display
status `running` alone SHALL NOT authorize a signal.

#### Scenario: Start sees an unreachable live instance

- **WHEN** state has a live PID but exact HTTP identity cannot be verified
- **THEN** start returns `WEB_INSTANCE_UNREACHABLE`
- **AND** it neither removes state nor creates another process

#### Scenario: Stop sees an unreachable live instance

- **WHEN** state has a live PID but exact HTTP identity cannot be verified
- **THEN** stop returns `WEB_INSTANCE_UNREACHABLE`
- **AND** it sends no signal and retains state

#### Scenario: Unsupported host cannot verify a failed endpoint

- **WHEN** liveness is `unknown` and exact authenticated probing fails
- **THEN** status reports `unreachable`
- **AND** start and restart create no child
- **AND** stop sends no signal and removes no state
- **AND** open returns no stale URL

#### Scenario: Exact running instance is stopped

- **WHEN** product, instance, and PID identity all match under the lock and process
  liveness is explicitly `alive`
- **THEN** stop sends SIGTERM to that PID and waits a bounded interval
- **AND** state is removed only after process death and exact instance recheck

#### Scenario: Exact endpoint has unknown process liveness

- **WHEN** authenticated metadata exactly matches the product, instance ID, and PID
  but process liveness is `unknown`
- **THEN** status and open may present the verified running instance
- **AND** start creates no duplicate child
- **AND** stop returns `WEB_PROCESS_LIVENESS_UNKNOWN` without signalling or deleting
  state
- **AND** restart fails its stop phase without signalling or starting a child

#### Scenario: Alive PID has conflicting endpoint identity

- **WHEN** process liveness is `alive` but authenticated product, instance ID, or
  PID evidence conflicts with state
- **THEN** stop sends no signal and retains state
- **AND** classification remains `identity-conflict`

#### Scenario: Dead PID has a reused HTTP port

- **WHEN** the persisted PID is proven dead and another service on the old port
  returns 401, 404, conflicting metadata, or exact-looking metadata
- **THEN** classification is `stopped` without probing or modifying that service
- **AND** status remains observational and open returns no stale URL
- **AND** stop sends no signal and may clean only the exact stale state

#### Scenario: Start recovers a dead state with a reused port

- **WHEN** start revalidates the same instance ID, PID, and proven death under the
  control lock
- **THEN** it removes only that stale state and creates at most one new child
- **AND** dynamic-port start uses new instance, PID, token, and port values
- **AND** an occupied requested fixed port only causes bounded new-child failure
- **AND** the unrelated port service remains untouched

#### Scenario: Stale state is replaced before cleanup

- **WHEN** state changes to a different instance ID or PID after stale
  classification but before cleanup
- **THEN** cleanup returns identity conflict without deleting or overwriting the
  replacement state
- **AND** start creates no child from the superseded classification

#### Scenario: Restart or open cannot bypass classification

- **WHEN** the current instance is starting, unreachable, identity-conflicting, or
  not proven stopped
- **THEN** restart does not start another process
- **AND** open does not return a stale URL

### Requirement: Startup child ownership is bounded

The parent SHALL retain authority over the exact `Popen` child created by one start
attempt and SHALL prove its exit before deleting that attempt's reservation after a
readiness failure.

#### Scenario: Readiness deadline expires and child terminates

- **WHEN** the owned child does not become exactly ready before the deadline
- **THEN** the parent terminates and waits for that child, with bounded kill
  escalation when required
- **AND** it removes only the same reservation after confirmed child exit
- **AND** no orphan remains

#### Scenario: Child death cannot be confirmed

- **WHEN** terminate and bounded kill cannot prove the owned child exited
- **THEN** state is retained
- **AND** the failure is unverified rather than stopped
- **AND** a later start cannot create a duplicate child

#### Scenario: Exact child authority is independent of host PID probing

- **WHEN** the parent owns the `Popen` object for its start attempt
- **THEN** bounded poll, wait, terminate, and kill cleanup remains available
- **AND** unsupported shared PID liveness does not weaken child cleanup

### Requirement: Concurrent start creates at most one managed instance

Managed start SHALL classify and reserve under the existing bounded control lock.

#### Scenario: Two independent starts race

- **WHEN** two independent processes request start concurrently
- **THEN** at most one creates a child
- **AND** the other observes starting or exact running state
- **AND** the lock remains bounded and no deadlock or orphan remains

### Requirement: Web safety and product compatibility are preserved

The repair SHALL preserve loopback binding, Bearer/Host/Origin/CSP boundaries,
read-only HTTP authority, task schemas, product/model/release identities, Phase 1
contracts and replay, and Phase 2 lock and Store behavior.

#### Scenario: Existing read-only Web surface is exercised

- **WHEN** static assets, metadata, stored views, live capture, 429/503 bounds, and
  forbidden HTTP methods are tested
- **THEN** existing read behavior remains available
- **AND** no HTTP mutation route exists

#### Scenario: Existing runtime state lacks new response metadata

- **WHEN** a legal existing runtime state names a live process but exact endpoint
  identity cannot be established
- **THEN** it is retained conservatively as starting, unreachable, or conflict
- **AND** it is not silently adopted, signalled, or deleted
