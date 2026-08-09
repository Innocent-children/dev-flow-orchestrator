## ADDED Requirements

### Requirement: Runtime receipt attests exact release content

Every managed release SHALL contain a closed, bounded, canonical, versioned receipt
that binds receipt schema, transaction, release, candidate, and activation IDs,
source commit and tree,
candidate manifest and artifact digest, wheel and distribution identity, installed
distribution metadata, wheel `RECORD` or equivalent installed-file inventory, exact
dependency inventory and lock digest, Python identity, startup verifier, launchers,
runtime and ownership identities, expected active release, and creation platform and
Python version. The active installation record SHALL bind the receipt digest.
The receipt SHALL record only the expected activation-descriptor path/schema,
`activation_id`, and expected transaction-journal path/schema for those downstream
records; it SHALL NOT contain an activation-descriptor or transaction-journal
digest. The descriptor SHALL bind the receipt digest, and the journal SHALL bind the
descriptor digest.

The exact dependency inventory SHALL include normalized name and version plus the
installed metadata/record identity and selected locked artifact hash for every
distribution. Extra, duplicate, missing, or changed package content SHALL be a
mismatch.

#### Scenario: A new runtime receipt is created

- **WHEN** a staged runtime has installed the sealed wheel and exact locked
  dependencies
- **THEN** the receipt inventories their actual installed bytes and metadata and is
  bound to the same candidate, transaction, release, launchers, ownership manifest,
  and active-record generation without a downstream descriptor or journal digest

#### Scenario: Installed package bytes or metadata differ

- **WHEN** a package file, wheel record, distribution metadata, or installed-file
  inventory differs from the receipt
- **THEN** attestation fails even if product version constants and behavioral smoke
  still pass

#### Scenario: Dependency inventory differs

- **WHEN** a dependency is missing, extra, duplicated, or has a different version,
  metadata, record, or locked artifact identity
- **THEN** attestation fails and the runtime is not considered reusable

#### Scenario: Python or launcher identity differs

- **WHEN** complete attestation is invoked and Python executable, ABI, venv
  configuration, verifier, presented launcher bytes, launcher mode, or configured
  active identity differs
- **THEN** attestation fails before candidate application code is imported

### Requirement: Startup fails closed before candidate import

A conforming installed CLI or MCP launcher SHALL invoke an installer-managed
verifier outside the candidate runtime with isolated, no-bytecode host Python. The
unmodified conforming launcher is the bootstrap precondition for this startup
guarantee. The verifier SHALL validate its presented launcher/verifier descriptor,
active record, runtime receipt, path containment, Python, package, metadata,
dependency, ownership, and release identities before executing the candidate
runtime. Startup SHALL NOT rebuild, repair, or mutate state.

The verifier SHALL have two closed authority modes. Ordinary startup SHALL resolve
only the committed active record and SHALL ignore transaction descriptors.
Installer-controlled `precommit-health` SHALL require the held lifecycle authority,
an exact journal path in `activated` state, and the journal-bound sealed activation
descriptor before it may resolve and execute an uncommitted candidate runtime.

#### Scenario: Runtime receipt is missing

- **WHEN** the active release has no runtime receipt
- **THEN** startup exits non-successfully before importing Dev Flow and directs the
  operator to a staging repair

#### Scenario: Runtime receipt is malformed or incompatible

- **WHEN** receipt JSON is malformed, exceeds its bound, has unknown or missing
  fields, or uses an unsupported schema
- **THEN** startup fails closed with a bounded incompatibility reason

#### Scenario: Active release does not match receipt

- **WHEN** launcher, active record, receipt, runtime path, or release ID points to a
  different release
- **THEN** startup fails closed instead of executing either release

#### Scenario: Runtime content drift is observed

- **WHEN** package bytes, distribution metadata, dependency inventory, Python, or
  ownership content differs from attested values
- **THEN** startup fails closed even if the runtime could otherwise answer a smoke
  request

#### Scenario: Conforming launcher presents changed identity

- **WHEN** a launcher still invokes the verifier but its presented identity no longer
  matches the active record and ownership identity
- **THEN** the verifier rejects startup and later repair replaces the launcher
  through the transaction

#### Scenario: Ordinary startup is given a transaction descriptor

- **WHEN** a normal installed launch is supplied an uncommitted transaction
  descriptor or pre-commit activation ID
- **THEN** the verifier ignores that authority, resolves only the committed active
  record, and never executes the uncommitted runtime

### Requirement: Repair rebuilds every attestation mismatch

Repair SHALL run the same complete attestation before reuse. It MAY return
`reused=true` only when all receipt, active, package, metadata, dependency, Python,
launcher, verifier, and ownership evidence matches. Any mismatch SHALL produce a
new staged release and SHALL NOT modify or bless the suspect runtime in place.

#### Scenario: Clean runtime is repaired

- **WHEN** the complete attestation matches the sealed candidate and active record
- **THEN** repair may reuse the release and records the verified receipt digest

#### Scenario: Package or dependency drift is repaired

- **WHEN** any installed package, metadata, record, dependency, or launcher evidence
  differs
- **THEN** repair stages and verifies a new release and activates it through the
  install transaction rather than returning reuse

#### Scenario: Legacy receipt is repaired

- **WHEN** the active runtime has a missing or legacy receipt or no exact ownership
  manifest
- **THEN** repair builds a new conforming release, retains the legacy runtime for
  inspection, and does not silently adopt its contents

### Requirement: Verifier trust boundary is explicit

The verifier SHALL be installer-managed outside the candidate runtime, SHALL use a
recorded supported host interpreter, and SHALL be content-bound to the launchers and
active record. Installer and repair SHALL validate launcher bytes independently
before commit or reuse. Product claims SHALL be limited to accidental corruption
and content drift detection when a conforming launcher invokes the verifier. The
design SHALL NOT claim an independent trust root or claim that a replacement
launcher which bypasses the verifier will reject its own execution.

#### Scenario: Launcher bootstrap is replaced

- **WHEN** a same-privilege actor or accidental replacement installs a launcher that
  does not invoke the verifier
- **THEN** installer or repair integrity validation rejects that launcher, while the
  startup guarantee explicitly makes no claim about execution through the replaced
  file

#### Scenario: Candidate runtime is corrupt

- **WHEN** candidate runtime code cannot be trusted to attest itself
- **THEN** the external verifier completes receipt and content checks before any
  candidate module import

#### Scenario: Same-privilege actor controls local attestation assets

- **WHEN** the threat model grants write access to the launcher or coherent write
  access to verifier, receipt, active record, and runtime
- **THEN** documentation and receipts do not claim that this local attestation can
  resist that actor
