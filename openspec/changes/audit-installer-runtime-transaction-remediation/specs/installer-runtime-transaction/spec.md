## ADDED Requirements

### Requirement: Install upgrade and repair use one durable transaction

Before a source clone/fast-forward or the first staging, runtime, launcher,
marketplace, plugin, health, or active-record mutation, the lifecycle SHALL durably
create a unique transaction containing the previous authority class, all previous
identities actually available, explicit unresolved candidate fields, and a
per-component plan. The `staged` transition SHALL atomically bind the selected
commit/tree, candidate/release IDs, manifest, wheel, and final lock identities and
SHALL make them immutable for later states. It SHALL persist atomic state
transitions through `prepared`, `staged`,
`promoted`, `activating`, `activated`, `verified`, and `committed`, or through
`failed` to `rolled-back` or `partial`. An unfinished transaction SHALL be resolved
before another lifecycle operation begins.

#### Scenario: Fresh install is prepared

- **WHEN** no previous Dev Flow release is active
- **THEN** the transaction records previous identity as `none`, stages a complete
  candidate before external activation, and owns only entries it creates

#### Scenario: Upgrade or repair is prepared

- **WHEN** a conforming previous release is active
- **THEN** the transaction binds the previous sealed plugin, runtime, marketplace,
  launcher, active-record, receipt, and ownership identities before mutation

#### Scenario: Legacy previous release is observed

- **WHEN** a Phase 0 or older release is active without sealed plugin, active-record,
  attestation, or exact-ownership authority
- **THEN** the transaction classifies it `legacy-observed`, records only available
  observations and retained paths, and does not call it immutable or exact-owned

#### Scenario: Process stops with an unfinished transaction

- **WHEN** a later invocation finds a journal not in `committed`, `rolled-back`, or a
  terminal truthful `partial` state
- **THEN** it resumes only a proven idempotent step or performs observed
  compensation, and it does not begin a blind repair

### Requirement: Lifecycle operations share one profile-scoped lock authority

Each supported personal Codex profile SHALL have one stable, process-independent
Dev Flow lifecycle lock whose identity is derived only from the normalized profile
root and product ID. The lock object SHALL live in an installer-controlled profile
control path outside the source, runtime release, launcher, marketplace, and active
record paths that lifecycle operations replace or remove. Install, upgrade, repair,
and uninstall for that profile SHALL use this same lock; all of their resolved
source, runtime, launcher, marketplace, active-record, and journal roots are
subordinate to it. They SHALL NOT acquire per-root lifecycle locks.

The operation SHALL acquire the profile lock before classifying previous state,
inspecting an unfinished journal, writing a new journal, or mutating a product
authority. It SHALL hold the lock through a durable `committed`, `rolled-back`, or
`partial` terminal record and immediate read-only completion observation.
Marketplace generation is guarded data under this lock, not another lock.
Contention SHALL use one bounded documented wait policy or return `busy` before
journal creation or product mutation.

An abnormal process exit MAY release the process lock, but the next lifecycle
operation SHALL acquire the same profile lock and resolve any durable unfinished
journal before starting another transaction. Compensation SHALL act only on
identities owned by that journal and SHALL NOT undo another transaction's observed
state or effects.

#### Scenario: One profile resolves multiple lifecycle roots

- **WHEN** one profile resolves source, runtime, launcher, marketplace, and
  active-record authorities on different roots
- **THEN** every lifecycle entry point uses the same single profile lock before
  observation and holds it to a durable terminal result without a multi-lock order

#### Scenario: Two installs compete

- **WHEN** two install operations for overlapping lifecycle authorities start
  concurrently
- **THEN** only the lock holder may classify previous state or create a journal, and
  the other waits or returns busy without a second candidate or previous authority

#### Scenario: Repair competes with install

- **WHEN** repair and install target any overlapping lifecycle authority
- **THEN** only one enters transaction observation or mutation, and the later
  operation re-observes authority after acquiring the profile lock

#### Scenario: Install competes with uninstall

- **WHEN** install and uninstall target any overlapping lifecycle authority
- **THEN** they cannot classify, mutate, remove, or compensate concurrently, and the
  later operation begins from the first operation's durable terminal record

#### Scenario: Repair competes with uninstall

- **WHEN** repair and uninstall target any overlapping lifecycle authority
- **THEN** they use the same profile lock and neither operation removes or restores
  entries owned by the other's transaction

#### Scenario: A lock holder exits abnormally

- **WHEN** a lifecycle process exits after writing a journal but before a durable
  terminal record
- **THEN** the next operation first acquires the same profile lock and resolves that
  journal without beginning a second blind transaction

### Requirement: The active installation record replace is the commit point

The transaction SHALL prepare and verify the candidate runtime, applicable
launchers, exact marketplace member, Codex plugin visibility, bundled MCP
registration, installed health, and applicable final CLI/MCP smoke before atomically
replacing the active installation record. The published `committed` active record
SHALL be the authoritative terminal transaction record; recovery SHALL read it
before treating a matching pre-commit journal as unfinished. No second journal
transition is required. That replace SHALL be the only commit point. Success output
SHALL occur only after it. No product mutation SHALL follow the commit point.

Filesystem entries on one filesystem MAY use atomic promotion. The product SHALL
model shared marketplace edits and Codex plugin remove/add as provisional effects
with compensation and SHALL NOT claim that these effects form a globally atomic
transaction.

Pre-commit candidate health SHALL use a sealed activation descriptor whose digest is
bound by the same `activated` journal. The verifier SHALL resolve the activation ID
through that descriptor to the candidate receipt and promoted runtime while the
previous active record remains authoritative. Ordinary installed startup SHALL NOT
accept this transaction-scoped mode.

#### Scenario: Candidate staging fails

- **WHEN** candidate export, validation, wheel build, or staging fails
- **THEN** the active record and previous release remain unchanged and the candidate
  is absent or explicitly retained as unreferenced staging

#### Scenario: Runtime promotion fails

- **WHEN** the staged runtime cannot be atomically promoted or its promoted identity
  cannot be revalidated
- **THEN** activation does not begin and the journal records whether any
  unreferenced candidate path remains

#### Scenario: Launcher or marketplace write fails

- **WHEN** an applicable launcher cannot be installed with exact compare-and-replace
  semantics or a lifecycle-coordinated marketplace publication cannot complete
- **THEN** the active record is not committed and all provisional effects are
  compensated or described by a durable partial result

#### Scenario: Codex command has uncertain side effects

- **WHEN** plugin remove or add returns success or failure
- **THEN** the installer observes actual plugin and MCP state instead of inferring
  side effects from the return code, and chooses the next transaction state from
  that observation

#### Scenario: Candidate health or final smoke fails

- **WHEN** visibility, MCP registration, installed health, or applicable final
  CLI/MCP smoke fails before commit
- **THEN** the previous release is compensated and verified or the transaction
  becomes truthful partial

#### Scenario: Candidate health targets the uncommitted release

- **WHEN** previous A remains in the active record while same-version candidate B is
  provisionally activated
- **THEN** journal-bound pre-commit health executes B, records B's activation,
  candidate, release, and runtime marker, and cannot pass by executing A

#### Scenario: Active record replacement fails

- **WHEN** all candidate gates passed but the final active record cannot be
  atomically replaced and fsynced
- **THEN** the transaction remains uncommitted and performs the same compensation
  and partial-state rules as any other provisional failure

#### Scenario: Active record replacement succeeds

- **WHEN** the final active record is atomically replaced after all gates pass
- **THEN** the transaction is committed, later response loss requires reading that
  record, and blind retry is not assumed safe

#### Scenario: Marketplace changes after commit

- **WHEN** read-only observation after active-record replacement finds marketplace
  drift or cannot read current marketplace state
- **THEN** the result remains committed, reports marketplace freshness as `false` or
  `unknown`, performs no compensation, and forbids blind retry

### Requirement: Rollback restores the immutable previous release

Compensation for an upgrade or repair SHALL restore local assets and plugin
activation from the sealed previous release, not from the mutable source checkout or
candidate. It SHALL re-observe the active plugin and SHALL run previous-release
visibility, bundled MCP, runtime attestation, installed health, and applicable CLI
smoke checks. Only a complete successful revalidation MAY be reported as
`rolled-back` or “restored”.

When the previous authority is `legacy-observed`, the lifecycle MAY conservatively
restore captured local bytes and re-observe the logical plugin after a failure, but
SHALL return `partial` after any external mutation and SHALL NOT claim
`rolled-back`, “restored”, exact previous identity, or ownership. A successful
candidate transaction MAY commit a new conforming release beside the retained
legacy runtime.

#### Scenario: Candidate plugin add fails

- **WHEN** candidate activation fails after the previous plugin was removed
- **THEN** compensation re-adds the sealed previous artifact and proves its previous
  source root, activation ID, bundled transport, release identity, attestation, and
  health before claiming restoration

#### Scenario: Failure follows candidate activation

- **WHEN** candidate activation succeeded but a later health, launcher, smoke, or
  active-record step fails
- **THEN** candidate state is removed only when its identity matches, previous state
  is restored from its immutable release, and no undeclared mixed state remains

#### Scenario: Fresh-install rollback is required

- **WHEN** a fresh install fails after provisional effects
- **THEN** compensation removes only exact transaction-created non-source entries,
  verifies no candidate plugin is active, retains source under DFO-AUDIT-002, and
  preserves all pre-existing unknown content

#### Scenario: Source changed during rollback

- **WHEN** source has changed since transaction preparation
- **THEN** rollback does not reset, clean, or overwrite source, uses sealed release
  artifacts for product recovery, and records a partial outcome when source differs
  from the operation-start identity

#### Scenario: Legacy transition fails after external mutation

- **WHEN** activation of a conforming candidate from a `legacy-observed` previous
  installation fails after a marketplace or Codex effect
- **THEN** the legacy runtime is retained, observed component state is durably
  reported as `partial`, and no restoration or immutable-previous claim is emitted

### Requirement: Rollback failure is a truthful partial outcome

When any compensation or restoration verification is unsuccessful or unavailable,
the lifecycle SHALL persist and return `partial`. The result SHALL identify the
observed active release as previous, candidate, none, or unknown; list every asset
as restored, candidate, absent, retained, or unknown; name retained release paths;
provide precise recovery actions bound to sealed identities; and state whether
blind retry is safe with its prerequisites. The default SHALL be
`blind_retry_safe=false`.

#### Scenario: Previous plugin reactivation fails

- **WHEN** the previous sealed plugin cannot be reactivated or observed
- **THEN** the result does not claim restoration, records active identity as none or
  unknown as observed, and gives recovery steps that name the previous release

#### Scenario: Local and external assets are mixed

- **WHEN** only some launchers, marketplace, runtime, plugin, or active-record assets
  were restored
- **THEN** each component is reported separately, the mixed state is durable, and
  no success receipt is emitted

#### Scenario: Blind retry cannot be proven safe

- **WHEN** an external Codex side effect or commit occurrence is uncertain
- **THEN** the partial result forbids blind retry and requires re-observation of the
  transaction and active authorities

### Requirement: Mutation boundaries have deterministic fault evidence

The implementation SHALL expose test-only failure seams for candidate staging,
runtime build, runtime promotion, applicable launcher write, marketplace write,
plugin remove, plugin add, health, active receipt replace, and final CLI/MCP smoke.
Production behavior SHALL NOT depend on enabling those seams.

#### Scenario: A mutation boundary fails under test

- **WHEN** a deterministic fault is injected at any named boundary
- **THEN** the test proves either the exact previous release is active and healthy or
  a durable truthful partial result exists, and proves the candidate is not called
  restored previous state

#### Scenario: Rollback also fails under test

- **WHEN** a boundary failure is followed by a deterministic compensation failure
- **THEN** the test proves the component matrix, active identity, retained paths,
  recovery actions, and retry-safety fields are complete
