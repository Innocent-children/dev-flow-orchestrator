## ADDED Requirements

### Requirement: Activation uses one sealed Git-tree candidate

After resolving the expected origin, authoritative `main` commit, and tree object,
the installer SHALL derive the candidate plugin artifact from that Git object tree
in transaction-owned staging. It SHALL validate the exported path, type, Git mode,
executable bit, blob identity, file digest, and symlink target inventory before
sealing the candidate. Build, marketplace, plugin activation, health, launcher, and
receipt operations SHALL NOT read activation content from the mutable authoritative
checkout after sealing.

Wheel construction SHALL use a disposable manifest-matching build copy and a
separate output directory; build backend residue SHALL NOT modify the sealed plugin
release or authoritative checkout.

The candidate SHALL include a stable content identity bound to source commit, source
tree, exported plugin inventory, plugin metadata, built wheel, distribution
identity, generated activation overlay, and dependency-lock digest. A detached
writable worktree or a repeated HEAD/status check SHALL NOT substitute for a sealed
artifact.

#### Scenario: Verified checkout changes after candidate sealing

- **WHEN** an external writer changes the checkout after the verified Git tree has
  been exported and sealed
- **THEN** the transaction either continues solely from the unchanged sealed
  candidate or fails closed, and no activated or receipted content is read from the
  changed checkout

#### Scenario: Source changes before candidate sealing completes

- **WHEN** the exported inventory or content no longer matches the verified Git tree
  before the candidate is sealed
- **THEN** installation fails before runtime promotion, marketplace replacement,
  plugin activation, launcher replacement, or active-record commit

#### Scenario: Git entry semantics are preserved

- **WHEN** the verified tree contains executable files or symbolic links
- **THEN** the staged candidate preserves and verifies their Git entry types, modes,
  executable bits, and link targets without following links outside staging

#### Scenario: Mutable candidate recheck is proposed

- **WHEN** an implementation rereads the checkout and compares only HEAD, status, or
  selected file digests before activation
- **THEN** validation rejects that implementation as insufficient candidate
  authority

### Requirement: Every release consumer binds the same candidate identity

The staged plugin tree and wheel SHALL be associated with their exact digests by an
external sealed candidate manifest whose digest is `candidate_id`; bytes that
contribute to that digest SHALL NOT be required to embed the digest. The managed
runtime, marketplace member, startup verifier, applicable launchers, health
evidence, ownership manifest, and active record SHALL bind that `candidate_id` and
the same `release_id`. External Codex
activation SHALL be bound by a non-secret `activation_id` in the candidate manifest
and a canonical release overlay. The marketplace source SHALL name the exact sealed
plugin root; bundled MCP metadata SHALL retain the public server name/command/args
and carry the activation ID in its internal environment. The installer SHALL require
host-owned read-back of both the normalized local source path and activation ID and
verify installed health through the reported command. Logical plugin ID, product
version, and enabled state alone SHALL NOT prove candidate identity. The installer
SHALL verify that this exact read-back capability exists before removing a previous
plugin or adding a candidate in the real profile. It SHALL perform that capability
probe only with the sealed candidate and disposable isolated CODEX_HOME,
marketplace, data, runtime, and temporary authorities. The probe SHALL include an
initially empty profile and SHALL NOT read or mutate the real profile.
If exact identity is unavailable or ambiguous after an external call, it SHALL NOT
commit or perform identity-specific removal and SHALL record truthful `partial`.
A mismatch at any boundary SHALL fail before the transaction commit point and invoke
the transaction's compensation rules when provisional effects already exist.

#### Scenario: Runtime build uses different candidate bytes

- **WHEN** the wheel or installed runtime does not match the sealed candidate
  manifest
- **THEN** runtime promotion and activation fail and no receipt claims the verified
  source identity for those bytes

#### Scenario: Marketplace or plugin target differs from the candidate

- **WHEN** the marketplace locator or observed Codex plugin identity resolves to a
  mutable checkout or a different release
- **THEN** health and commit fail, with the previous release restored or a truthful
  partial transaction recorded

#### Scenario: Host exposes only logical plugin identity

- **WHEN** the host can report only fixed plugin ID, product version, or enabled
  state and cannot read back the normalized sealed source path and bundled
  activation ID
- **THEN** the installer fails closed before previous-plugin removal or candidate
  add, and does not claim that A and B are distinguishable

#### Scenario: Fresh profile capability is probed in isolation

- **WHEN** the real installation profile is empty and candidate activation has not
  begun
- **THEN** an isolated disposable profile proves exact source-path and activation-ID
  read-back before any real marketplace or Codex mutation, or installation fails
  with the real profile unchanged

#### Scenario: Same-version repair activates a distinct candidate

- **WHEN** conforming previous A and candidate B have the same public plugin version
- **THEN** their distinct sealed source roots and activation IDs distinguish them,
  and B is verified only when both host read-back channels name B and pre-commit
  health records B's runtime marker

#### Scenario: Activation identity becomes unobservable after an external call

- **WHEN** plugin add or remove may have occurred but exact source-path or activation
  read-back is missing, duplicated, mismatched, or unstable
- **THEN** active identity is `unknown`, identity-specific cleanup is forbidden,
  commit is forbidden, and the transaction persists truthful `partial`

#### Scenario: Launcher or receipt identity differs

- **WHEN** a launcher, ownership manifest, runtime receipt, or active record names a
  candidate other than the candidate that passed health
- **THEN** the active record is not committed and the mismatch is recorded as a
  bounded transaction failure

### Requirement: Installation preserves authoritative source state

The transaction SHALL record operation-start source authority and any planned
authoritative clone or fast-forward separately. After that selection and before
candidate sealing, install, repair, and upgrade SHALL capture a source immutability
baseline and SHALL compare final HEAD, tree, index, tracked, untracked, and ignored
state to that baseline after success, failure handling, and rollback.
All unavoidable Python commands executed from authoritative source SHALL use `-B`
and a command-scoped `PYTHONDONTWRITEBYTECODE=1`; build and health SHOULD execute
from the sealed candidate instead. The lifecycle SHALL NOT create `__pycache__`,
`.pyc`, build output, distribution output, egg-info, or other generated content in
the authoritative checkout.

Existing unrelated ignored content MAY remain only when allowed by the existing
authoritative-installation contract, excluded from the Git-tree candidate, and
byte-identical before and after. The installer SHALL NOT delete or rewrite such
content to manufacture cleanliness. DFO-AUDIT-002 source-retention containment
continues to apply after every outcome.

#### Scenario: Fresh install leaves source clean

- **WHEN** a fresh clean checkout is installed successfully
- **THEN** tracked, untracked, and ignored porcelain remains empty and no bytecode or
  build residue exists in source

#### Scenario: Repair leaves source clean

- **WHEN** a conforming installation is repaired or its runtime is reused
- **THEN** source identity and complete porcelain are unchanged and no new cache or
  build entry appears

#### Scenario: Failed install or rollback leaves source unchanged

- **WHEN** any staging, activation, health, commit, or compensation step fails
- **THEN** source is neither reset nor cleaned, operation-start, selected, and final
  identities are reported, final state matches the post-selection baseline unless
  external drift occurred, and installer-created source residue is absent

#### Scenario: Existing ignored user content is present

- **WHEN** an eligible checkout contains unrelated ignored content permitted by the
  authoritative installation contract
- **THEN** the candidate excludes that content, the content remains byte-identical,
  and any change to its before/after inventory fails before a success receipt

#### Scenario: Authorities contain spaces and Unicode

- **WHEN** source, staging, runtime, or marketplace paths contain spaces, Unicode,
  or apostrophes
- **THEN** sealing and source-immutability checks retain the same safety semantics
  without writing generated files into source
