## Context

`Controller.apply`, contract revision, decision, finding disposition, and
cancellation currently capture repositories before entering `TaskStore.update`.
`TaskStore.update` later acquires the task lock, checks the revision, derives a
candidate from a closure containing that earlier snapshot, and atomically replaces
the state file. The two-pass capture proves only that the repository set was stable
during capture. It does not bind that observation to the mutation's linearization
point.

No application can prevent an unrelated, non-cooperating process from changing
ordinary worktree files. Dev Flow can serialize its own processes and can reject
drift observed by a final pre-write revalidation, but ordinary file locks cannot
eliminate the residual interval from that observation to an atomic state-file
replacement. The product therefore uses an explicit containment protocol: bind the
candidate to one in-lock snapshot, revalidate before replacement, and make a new
post-write observation before claiming currentness. Commit occurrence and
post-commit freshness are separate authorities.

The uninstallers have a structurally similar time-of-check/time-of-use problem but a
more severe consequence. They validate a path, execute several external effects,
and finally remove the entire source root recursively. Existing installations have
no exact ownership manifest. Path, origin, branch, cleanliness, and commit ancestry
cannot prove ownership of every entry at deletion time.

## Goals / Non-Goals

**Goals:**

- Fail drift detected by pre-write revalidation without a receipt, revision
  increment, node transition, or terminal `DONE`; for residual-window drift, retain
  the committed receipt while refusing a current Dossier claim.
- Cover ordinary apply, revision, decision, disposition, cancellation, finalization,
  and a changed member of a multi-repository set with deterministic tests.
- Preserve source on default uninstall on both script implementations and make the
  containment explicit to humans and automation.
- Restore a hermetic full unittest baseline before relying on later evidence.

**Non-Goals:**

- Prevent arbitrary external processes from changing a repository after the
  mutation linearization point.
- Change the persisted `0.4.0` model or silently migrate old tasks.
- Implement the installer/runtime transaction findings DFO-AUDIT-006 through
  DFO-AUDIT-010.
- Claim native Windows lifecycle evidence from a non-Windows host.
- Re-enable source deletion for legacy or newly installed checkouts in this phase.

## Decisions

### 1. One fixed lock order and canonical repository identities

Every repository-dependent mutation uses one Controller/Store commit helper and the
same acquisition order:

1. current-namespace membership lock;
2. one authority lock per repository, sorted by a canonical byte-stable identity;
3. task lock.

The repository lock identity is derived from the immutable canonical worktree root
and its worktree-specific Git directory identity after platform canonicalization; it
is never derived from caller spelling, repository input order, or a caller-selected
identifier. The membership lock remains held for the full protocol so repository
membership cannot change while authority locks are selected. Repository locks add
cross-task and cross-process serialization for cooperating Dev Flow processes;
they do not claim to block arbitrary editors or Git processes. Context-managed lock
release occurs in reverse order for cancellation, capture, derivation, validation,
write, and post-write observation outcomes. No path may acquire an earlier lock
while holding a later one.

### 2. Explicit capture, derive, revalidate, replace, observe phases

After the three lock layers are held, the helper reloads the task and checks revision
compare-and-swap. It then executes these named phases:

1. `capture`: perform a complete stable repository-set capture `S` with the exact
   resource request required by the mutation;
2. `derive`: build and validate a pure candidate transition only from current task
   state, validated inputs, and `S`; candidate derivation performs no external
   effect;
3. `before-revalidation`: expose a deterministic test-only fault seam;
4. `revalidate`: capture `S'` with the identical membership and resource request;
5. reject with `SNAPSHOT_UNSTABLE` and no durable change when `S' != S`;
6. `after-revalidation`: expose a second deterministic seam for the residual window;
7. `replace`: atomically replace the task state with the candidate bound to `S`;
8. `before-observation`: expose a post-write fault seam;
9. `observe`: perform a new complete live capture used only for response freshness
   and the returned live projection.

Equality of `S` and `S'` proves authority only at the revalidation observation
point. An arbitrary writer may still change the worktree between `S'` and replace.
That residual is why DFO-AUDIT-001 remains `CONTAINED`. Adding another lock-external
capture, retrying a non-idempotent mutation, or treating `S`/`S'` as post-write
freshness is not conforming.

### 3. Durable commit and response freshness are separate results

If revalidation detects drift, the operation fails before replace: no receipt,
revision increment, record, node/status transition, or new `DONE` is produced. Once
atomic replacement succeeds, the mutation is committed and is never converted into
an ordinary failure merely because the post-write observation differs or fails.

Every mutation receipt carries an explicit committed state, committed revision,
versioned workspace-freshness object, `blind_retry=false`, and read-after-write
recovery guidance. Freshness is tri-state:

- `true`: post-write observation succeeded and equals `S` at its `observed_at` time;
- `false`: post-write observation succeeded and differs from `S`, with bounded
  reasons;
- `unknown`: the post-write observation failed and currentness cannot be proved.

For `false` and `unknown`, the committed receipt remains a success and directs the
caller to obtain current authority before another mutation. A response lost after
replace remains completion-uncertain and uses read-after-write recovery; it is not
made safe by blind retry.

The persisted terminal record and Delivery Dossier remain immutable historical
evidence bound to `S`. A response may set `dossier.current=true` only from a
successful post-write observation equal to `S`; mismatch yields false and failed
observation yields null/unknown. Stored-only inspection already uses no live
snapshot and therefore remains unknown. Subsequent Controller, MCP, CLI, and Web
live reads capture again. Historical persisted `current` observations are never
trusted as permanent currentness.

The versioned freshness object is response-only; this phase does not alter the
persisted task model, action binding, or terminal artifact schema, so existing tasks
require no migration. If a later design persists a token or freshness field, it must
use a new schema and define explicit compatible read or fail-closed behavior.
In particular, a simple governance decision still persists `snapshot: null` and
retains its replay identity even though its candidate and commit pass through the
same repository authority protocol and its response uses the new live observation.

### 4. Destructive source removal is disabled until exact ownership exists

Default uninstall and the documented keep-source mode both preserve the source
checkout. The receipt reports factual per-component outcomes for plugin, launcher,
runtime, and marketplace steps without reclassifying runtime removal as exact-owned
or independently safe; it separately reports source retention and states that exact
source ownership proof is unavailable. It does not print `source removed` or another
complete-removal success claim. Task data is never removed. Runtime ownership remains
the open DFO-AUDIT-010 risk.

Any future source-removal implementation must start at installation time with a
versioned manifest bound to the installation receipt. The manifest must enumerate
every installer-created entry, expected type, content or Git/tree identity, and
symlink/special-entry identity. Removal must atomically rename the proven source to
a same-filesystem quarantine, preserve a newly created original path, compare the
quarantine with the exact manifest, remove only proven entries, stop on every
unknown or changed entry, and restore or retain the quarantine on failure. Recursive
root deletion is forbidden. An old installation without that manifest remains
preserved.

Implementing that full protocol overlaps the later installer/runtime transaction
phase and is intentionally deferred. The finding can only be reported as
`CONTAINED — destructive source removal disabled` in this phase.

### 5. Test authority is explicit and local

Shared test helpers construct child environments from a minimal platform allowlist,
remove all inherited Dev Flow data authorities, and then set test-owned data,
runtime, source, marketplace, profile, home, temporary, and executable roots. The
  inventory covers CLI, installer, uninstaller, managed runtime, installed journeys,
  Web runtime, MCP runtime, Windows runtime, and lifecycle subprocess fixtures.

Hostile-parent tests cover `DEV_FLOW_DATA_DIR`, `PLUGIN_DATA`, `CODEX_HOME`, each
pair, and all three together. Higher-priority variables point to external temporary
roots containing recognizable sentinels, running Web state, PID/status, and task
data, while the child's declared temporary root contains no running state. Each case
asserts the resolver result is below its own `TemporaryDirectory` and that every
external byte remains unchanged. Intentional fallback tests remove only the higher
priorities they are designed to bypass; production precedence is unchanged.

Native Windows lifecycle and lock tests receive temporary `DEV_FLOW_RUNTIME_HOME`,
`LOCALAPPDATA`, `USERPROFILE`, `CODEX_HOME`, data, source, marketplace, and command
roots before production behavior. Host-neutral/static checks run on this host;
native Windows dynamic checks remain `NOT RUN — native Windows host unavailable`.

## Risks / Trade-offs

- Holding the global membership lock during Git capture serializes repository-backed
  mutations across tasks. Safety and simple lock ordering take priority in this
  critical phase; finer-grained concurrency is deferred.
- Repository state can change after `S'`, after replacement, or after the live
  observation. `current=true` is only a point-in-time observation, never a guarantee
  through response delivery or a claim of permanent workspace immutability.
- Per-repository authority locks serialize cooperating Dev Flow processes only and
  do not exclude non-cooperating external writers.
- Default uninstall leaves disk usage behind. The receipt and documentation make
  the retained path and manual recovery explicit, which is safer than inferring
  ownership from legacy state.
- PowerShell behavior can be checked statically and with host-neutral assertions on
  this host, but only a supported native Windows run can become dynamic lifecycle
  evidence.
