## MODIFIED Requirements

### Requirement: Marketplace registration remains isolated and deterministic

After source verification, sealed-release validation, and package validation
succeed, the installer SHALL re-read a valid personal marketplace, replace only the
`dev-flow-orchestrator` member in that current document, and atomically publish the
merged bytes. It SHALL preserve every unrelated member and leave exactly one Dev
Flow entry that resolves to the installer-owned release-specific plugin directory.
It SHALL NOT point that entry to the mutable authoritative checkout.

The bounded transaction SHALL retain the previous marketplace bytes. Rollback SHALL
re-read the current document and restore only the Dev Flow member when current state
still matches the candidate value written by that transaction. If safe member-only
restoration cannot be proved, it SHALL preserve the current document and report
`partial`; it SHALL NOT overwrite unrelated changes with an old whole-file snapshot.

#### Scenario: Existing valid marketplace contains unrelated entries

- **WHEN** installation succeeds with unrelated plugin entries and an older Dev Flow
  member
- **THEN** unrelated entries remain unchanged and exactly one Dev Flow member points
  to the sealed plugin release named by the committed selection receipt

#### Scenario: Marketplace JSON is malformed

- **WHEN** the marketplace cannot be parsed as an object containing a plugins array
- **THEN** installation fails without replacing the malformed file or invoking
  plugin activation

#### Scenario: Marketplace changes before rollback

- **WHEN** rollback observes that the marketplace no longer contains the exact
  candidate member written by the transaction
- **THEN** it preserves the current file, reports the observed state as partial,
  and does not overwrite unrelated members

### Requirement: Windows uninstallation removes only validated installation assets

The product SHALL provide `scripts/uninstall.ps1` for supported Windows x64 clients.
It SHALL remove the installed plugin when present, atomically remove only the Dev
Flow member from a valid personal marketplace, preserve unrelated marketplace and
MCP entries, and report plugin, marketplace, launchers, runtime, source, and task
data separately.

Managed-runtime removal SHALL follow the exact per-entry ownership Requirements in
this change. It SHALL retain legacy, missing, mismatched, changed, unknown, or
unverifiable runtime content and SHALL NOT use `Remove-Item -Recurse` or an
equivalent whole-tree runtime/release deletion.

Every source checkout SHALL be retained. Default uninstall, keep-source, and any
explicit source-removal request SHALL preserve source because destructive source
removal remains disabled under DFO-AUDIT-002 containment. Runtime ownership SHALL
NOT authorize source removal. Controller task data SHALL remain unchanged.

When source or runtime is retained, the human and machine-observable result SHALL
name each retained path, report a partial component outcome where applicable, and
provide inspection and backup guidance without an unconditional recursive deletion
command.

#### Scenario: Ordinary Windows uninstall runs

- **WHEN** plugin, marketplace member, launchers, managed runtime, and source are
  present
- **THEN** only exact-owned runtime entries are eligible for per-entry removal,
  source and task data are retained, and all component outcomes are reported

#### Scenario: Windows source contains user work

- **WHEN** source has local changes, ignored content, local-only commits, unexpected
  origin, or another identity mismatch
- **THEN** source and user work remain unchanged and the result names the retained
  path without deleting task data or unrelated configuration

#### Scenario: Keep source is requested

- **WHEN** the operator supplies the documented keep-source option
- **THEN** other component operations may proceed and are reported separately while
  source and task data remain unchanged

#### Scenario: Explicit source removal is requested

- **WHEN** the operator requests source removal
- **THEN** the request fails closed to source retention and reports that destructive
  source removal is disabled

#### Scenario: Manual source recovery is described

- **WHEN** source is retained by any Windows uninstall mode
- **THEN** guidance names the path and requires inspection, backup, and independent
  ownership confirmation without giving an unconditional recursive deletion command
