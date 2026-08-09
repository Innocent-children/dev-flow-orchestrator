## MODIFIED Requirements

### Requirement: Marketplace registration remains isolated and deterministic

After source and sealed-candidate validation succeed, the installer SHALL acquire
its lifecycle marketplace authority, re-read a valid personal marketplace, replace
only the `dev-flow-orchestrator` member in that current document, and atomically
publish the merged bytes. It SHALL preserve every unrelated entry observed under
that authority and SHALL leave exactly one entry that resolves to the
release-specific sealed candidate plugin artifact. That artifact's activation
descriptor SHALL bind the transaction, release, and candidate identities used by
runtime, activation, health, launchers, and the active record; the marketplace entry
need only resolve to that artifact through its supported local-source fields. It
SHALL NOT point to the mutable authoritative source checkout.

Marketplace replacement is a shared-file provisional effect, not a globally atomic
Codex transaction. Transaction-aware lifecycle writers SHALL share a versioned
lock/generation authority, so a changed generation fails before publish and
preserves the newer document. For an existing file, publication SHALL use a
platform-proven atomic exchange or replacement-with-displaced-file backup; for an
absent file it SHALL use atomic no-clobber creation. If those primitives are
unavailable, installation SHALL fail before marketplace or Codex mutation.

After publication, the installer SHALL compare the displaced bytes to its captured
generation and re-observe the canonical path. A mismatched displaced generation or
post-publish observation SHALL prevent commit; every displaced/candidate/current
version under installer control SHALL be retained or conditionally restored, and
the result SHALL be truthful `partial` with exact digests and recovery guidance. A
writer that does not participate in the lifecycle authority cannot be given a
linearizable file CAS guarantee, so the specification does not claim that the
candidate was never briefly visible or that later external writers were serialized.
Compensation SHALL merge only the Dev Flow member into the latest valid document and
SHALL NOT blindly restore a complete old marketplace snapshot.

#### Scenario: Existing valid marketplace contains unrelated entries

- **WHEN** installation succeeds with a marketplace containing unrelated plugin
  entries and an older Dev Flow entry
- **THEN** unrelated entries remain unchanged and exactly one Dev Flow entry points
  to the sealed candidate plugin release that matches the committed active record

#### Scenario: Marketplace JSON is malformed

- **WHEN** the marketplace cannot be parsed as an object containing a plugins array
- **THEN** installation fails without replacing the malformed file or invoking
  plugin activation

#### Scenario: Coordinated marketplace writer changes concurrently

- **WHEN** another transaction-aware lifecycle writer changes the marketplace
  generation after capture and before replacement
- **THEN** replacement fails closed, preserves the newly observed content, and the
  transaction restores the previous release or records a truthful partial outcome

#### Scenario: Displaced-file preservation is unavailable

- **WHEN** the platform cannot atomically exchange an existing marketplace or retain
  the exact displaced file during replacement
- **THEN** installation fails before marketplace or Codex mutation and does not use
  unconditional replacement as a fallback

#### Scenario: Uncoordinated marketplace writer races replacement

- **WHEN** a writer outside the lifecycle authority changes the marketplace during
  the final read-to-replace interval
- **THEN** the atomic exchange/backup retains the displaced document, any observed
  conflict prevents commit and is reported as partial, no complete old snapshot is
  blindly restored, and no global-CAS or serialization claim is emitted

### Requirement: Windows uninstallation removes only validated installation assets

The product SHALL provide `scripts/uninstall.ps1` for supported Windows x64 clients.
It SHALL remove the installed plugin when present, atomically remove only the Dev
Flow entry from a valid personal marketplace, and report launcher and runtime
outcomes without treating them as proof of source ownership. It SHALL preserve
external Controller task data in all cases, preserve unrelated marketplace entries,
and preserve unrelated bundled or standalone MCP registrations.

Every source checkout SHALL be retained until installation has produced a versioned,
receipt-bound exact-ownership manifest and the separately specified quarantine and
per-entry removal protocol is implemented and validated. Default uninstall,
keep-source, and any explicit source-removal option SHALL therefore preserve source
in this phase. No option SHALL bypass containment with `Remove-Item -Recurse` or any
equivalent whole-tree deletion. Path, origin, branch, clean status, ancestry, and
checkout location SHALL NOT substitute for exact ownership.

Managed-runtime handling SHALL follow the separate `exact-runtime-ownership`
Requirements in this change: only revalidated entries of a conforming manifest may
be removed per entry, while legacy, missing, mismatched, changed, or unverifiable
runtime ownership SHALL be retained and reported truthfully as partial. Runtime
ownership SHALL NOT authorize source deletion. Uninstallation SHALL report plugin,
marketplace, MCP registration, runtime, source, and task-data outcomes separately.
Its human and machine-observable result SHALL name the exact retained source path,
identify the missing verifiable source-ownership manifest or disabled destructive
source removal, report an explicit partial outcome, and direct the operator to
inspect and back up the checkout and independently confirm source ownership. It
SHALL NOT claim complete source removal or recommend unconditional recursive manual
deletion.

#### Scenario: Ordinary Windows source removal is safety-contained

- **WHEN** plugin, marketplace entry, launchers, runtime, and source are present
- **THEN** source is retained, conforming runtime entries follow exact per-entry
  ownership while unverifiable runtime is retained, and the receipt reports each
  component, a partial source outcome, and preserved Controller task data

#### Scenario: Windows source contains user work

- **WHEN** source has local changes, ignored content, local-only commits, unexpected
  origin, a symlink or reparse mismatch, or another unsafe identity
- **THEN** source and all user work remain unchanged and the result reports retained
  path and exact-ownership containment without deleting task data or unrelated MCP
  configuration

#### Scenario: Keep source is requested

- **WHEN** the operator supplies the documented keep-source option
- **THEN** other component operations may proceed and are reported separately while
  source and task data remain unchanged and source retention is reported explicitly

#### Scenario: Explicit source removal is requested

- **WHEN** the operator requests source removal without a conforming exact-ownership
  manifest and implemented removal protocol
- **THEN** the request fails closed to source retention and the partial result states
  that destructive source removal is disabled

#### Scenario: Manual source recovery is described

- **WHEN** source is retained by any Windows uninstall mode
- **THEN** guidance names the path and requires inspection, backup, and independent
  ownership confirmation without giving an unconditional recursive deletion command
