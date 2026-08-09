## ADDED Requirements

### Requirement: Terminal evidence is immutable and freshness is tri-state

A non-cancelled terminal record SHALL bind the exact repository-set snapshot `S`
used to derive its committed transition. That record is immutable historical
delivery evidence. Whether it is current relative to the workspace SHALL be derived
from a new complete observation and SHALL NOT be represented as a permanent
persisted truth.

Response and live-read freshness SHALL be tri-state. `true` means a complete live
observation equals the terminal snapshot as of an explicit observation time;
`false` means the observation succeeds and differs, with bounded reasons; `unknown`
means no valid live observation is available. `dossier.current` SHALL be true only
for freshness true, false for freshness false, and null or conservatively non-current
for unknown. A successful mutation response SHALL NOT derive currentness from
pre-write `S` or `S'`.

Every Controller, MCP, CLI, and Web live read SHALL observe again. A stored-only
projection SHALL expose the terminal record and bound snapshot with freshness
unknown. Historical persisted current observations SHALL not be trusted without a
new live observation.

#### Scenario: Finalization mismatch is detected by revalidation

- **WHEN** finalization captures `S` and pre-write revalidation returns a different
  `S'`
- **THEN** finalization fails before persistence and leaves no new `DONE` record or
  current Dossier claim

#### Scenario: Residual-window drift follows successful revalidation

- **WHEN** a repository changes after matching `S'` but before replacement
- **THEN** the immutable historical terminal record may commit, but post-write
  freshness is false or unknown and the response does not claim a current Dossier

#### Scenario: Workspace changes after a valid terminal record

- **WHEN** successful finalization commits and the workspace changes later
- **THEN** the terminal record remains immutable while the next live projection
  reports freshness false with bounded workspace-change reasons

#### Scenario: Live observation is unavailable

- **WHEN** a committed terminal record cannot be compared with a valid live snapshot
- **THEN** freshness is unknown, `dossier.current` is not true, and the committed
  receipt is not reclassified as a failed mutation

#### Scenario: Stored terminal inspection has no repository observation

- **WHEN** a read intentionally avoids live Git capture
- **THEN** it reports freshness unknown and does not reuse a historical current flag

#### Scenario: Point-in-time currentness is returned

- **WHEN** a post-write or later live observation equals the terminal snapshot
- **THEN** freshness and `dossier.current` may be true only as of that observation
  time and do not promise equality through response delivery

### Requirement: Response freshness is explicitly versioned

The tri-state workspace-freshness object carried by mutation receipts SHALL include
an explicit schema identity, status, observation time when available, and bounded
reasons. It is response-only in this phase. The persisted task, action binding, and
terminal artifact schemas SHALL remain unchanged, so older persisted tasks require
no silent migration and are read with fresh live observation or unknown stored-only
semantics.

If a later implementation persists a commit token or freshness field, it SHALL use
a new schema version and define explicit compatible reading or fail-closed behavior
for old records.

#### Scenario: Existing terminal task is read after upgrade

- **WHEN** a task created without the response freshness object is inspected
- **THEN** its persisted record is not rewritten and currentness comes only from a
  new live observation or remains unknown
