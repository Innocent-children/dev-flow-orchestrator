## MODIFIED Requirements

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

This change does not strengthen or validate managed-runtime ownership or deletion;
DFO-AUDIT-010 remains open. Uninstallation SHALL report plugin, marketplace, MCP
registration, runtime, source, and task-data outcomes separately without describing
runtime removal as independently safe or exact-owned. Its human and
machine-observable result SHALL
name the exact retained source path, identify the missing verifiable ownership
manifest or disabled destructive removal, report an explicit partial outcome, and
direct the operator to inspect and back up the checkout and independently confirm
ownership. It SHALL NOT claim complete source removal or recommend unconditional
recursive manual deletion.

#### Scenario: Ordinary Windows source removal is safety-contained

- **WHEN** plugin, marketplace entry, launchers, runtime, and source are present
- **THEN** source is retained, each other component outcome is reported without a
  new ownership claim, and the receipt reports a partial outcome and preserved
  Controller task data

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
