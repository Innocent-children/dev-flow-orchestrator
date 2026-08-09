## ADDED Requirements

### Requirement: Install upgrade and repair use one bounded transaction record

Each install, upgrade, or repair attempt SHALL use a small versioned record containing
optional `transaction_id`, operation, previous release, candidate release, current
step, actual observed state for runtime selection, plugin, marketplace, MCP launcher,
and CLI launcher, and terminal outcome `committed`, `rolled_back`, or `partial`.
The record SHALL be atomically replaced as observations change.

Before the real plugin, Dev Flow marketplace member, launcher, or selected runtime
is changed, the candidate plugin/runtime/launcher assets SHALL be fully staged and
verified and the previous sealed release SHALL remain available.

#### Scenario: Fresh install is staged

- **WHEN** no previous Dev Flow release is installed
- **THEN** the record identifies previous release as `none`, and external mutation
  begins only after the candidate release is complete

#### Scenario: Conforming previous release is staged

- **WHEN** install, upgrade, or repair replaces a release that already has sealed
  plugin and runtime assets
- **THEN** the record captures that previous `release_id` and retains its artifacts
  until commit or verified rollback

#### Scenario: Source-based previous installation is upgraded

- **WHEN** the previous plugin still resolves to the authoritative source checkout
- **THEN** the installer exports and verifies a runnable sealed previous release
  from the current verified commit before source fast-forward or external mutation,
  or fails with the previous installation unchanged

#### Scenario: Candidate staging or runtime build fails

- **WHEN** release staging, runtime build, or runtime promotion fails before external
  activation changes
- **THEN** the previous release remains selected and the result does not claim that
  the candidate committed

### Requirement: External effects are observed and success is published last

The transaction SHALL treat marketplace and Codex operations as observable external
effects. Marketplace update SHALL re-read a valid current document, change only the
Dev Flow member, preserve unrelated members, atomically replace the document, and
retain the transaction's previous bytes. Rollback SHALL restore only the Dev Flow
member and only when current state still permits safe restoration; otherwise it
SHALL preserve current state and report `partial`.

After every `codex plugin remove` and `codex plugin add` return, whether successful
or unsuccessful, the installer SHALL query currently visible plugin and MCP state
and SHALL NOT infer absence of side effects from the return code.

Candidate plugin visibility, MCP registration, installed health, and applicable
final CLI/MCP smoke SHALL pass before the active selection receipt is atomically
published. That publication SHALL name the selected `release_id`, SHALL be the last
product mutation on the success path, and SHALL carry the committed outcome.

#### Scenario: Marketplace write fails

- **WHEN** the Dev Flow marketplace member cannot be published safely
- **THEN** plugin commit is refused and previous state is restored or the actual
  retained marketplace state is reported as partial without overwriting unrelated
  members

#### Scenario: Codex command reports failure after a side effect

- **WHEN** remove or add returns non-zero after changing visible state
- **THEN** the next action is selected from the observed plugin and MCP state rather
  than the command return code alone

#### Scenario: Candidate health or final smoke fails

- **WHEN** candidate health or applicable CLI/MCP smoke fails after provisional
  activation
- **THEN** the active selection receipt is not published and bounded rollback begins

#### Scenario: Candidate passes every gate

- **WHEN** staged assets, marketplace member, launchers, plugin/MCP visibility,
  health, and final smoke all match the candidate release
- **THEN** the active selection receipt is published last and subsequent work is
  limited to output and read-only observation

### Requirement: Rollback restores the sealed previous release

On any late failure, rollback SHALL use the retained sealed previous release rather
than the mutable checkout or candidate. It SHALL restore the previous plugin,
Dev Flow marketplace member, MCP launcher, CLI launcher, and runtime selection, then
re-observe plugin and MCP state and run previous MCP health plus applicable CLI
smoke. Only an actually running, healthy previous release MAY be reported as
`rolled_back` or "previous restored".

Fresh-install rollback SHALL remove only transaction-created non-source entries that
still match exact ownership. Source and all pre-existing unknown content SHALL be
retained.

#### Scenario: Candidate plugin add fails

- **WHEN** the previous plugin was removed and candidate add fails
- **THEN** rollback re-adds the sealed previous plugin path and proves the previous
  release is visible and healthy before claiming restoration

#### Scenario: Failure occurs after candidate activation

- **WHEN** launcher, health, smoke, or final selection publication fails after the
  candidate becomes visible
- **THEN** rollback restores each previous component from retained evidence and
  either verifies the actual previous release or reports partial

#### Scenario: Fresh install requires rollback

- **WHEN** a fresh install fails after creating provisional entries
- **THEN** only matching transaction-owned runtime, plugin-release, marketplace,
  and launcher entries are eligible for removal, while source and unknown entries
  remain

#### Scenario: Source changes during rollback

- **WHEN** an external writer changes source during failure handling
- **THEN** rollback neither resets nor cleans source and uses the sealed previous
  release, or reports partial if restoration cannot be proved

### Requirement: Incomplete rollback is reported as partial

If any restoration or post-restoration verification is unsuccessful or uncertain,
the command SHALL return non-zero and persist `partial`. The record SHALL list the
current plugin, marketplace, launcher, and runtime states, retained paths, previous
and candidate `release_id` values when known, and `blind_retry_safe=false`.
Candidate B SHALL NOT be described as restored previous A.

Deterministic permanent tests SHALL inject failures at candidate staging, runtime
build, runtime promotion, marketplace write, MCP launcher write, CLI launcher write,
plugin remove, plugin add, health, final CLI/MCP smoke, and rollback itself.

#### Scenario: Previous plugin reactivation fails

- **WHEN** rollback cannot re-add or observe the sealed previous plugin
- **THEN** the result records plugin state as absent or unknown as observed, keeps
  recovery paths, and makes no restoration claim

#### Scenario: Local and external components remain mixed

- **WHEN** only some marketplace, launcher, plugin, or runtime components restore
- **THEN** every component is reported separately with terminal outcome `partial`
  and no success receipt is emitted

#### Scenario: A forward mutation boundary fails under test

- **WHEN** a deterministic failure is injected at any named forward boundary
- **THEN** the test proves candidate B committed and is healthy, previous A was
  actually restored and is healthy, or a declared partial result describes the
  mixed state

#### Scenario: Rollback also fails under test

- **WHEN** a forward failure is followed by deterministic rollback failure
- **THEN** the record contains actual component state, retained paths, known release
  identities, and `blind_retry_safe=false`
