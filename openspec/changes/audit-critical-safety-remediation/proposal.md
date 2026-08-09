## Why

The comprehensive audit of commit
`e8ca09bebfadb1a90eb84767b0c5303163da4179` demonstrated two critical safety
failures and one test-authority failure. A repository can change after the
Controller's last complete capture but before `TaskStore` commits the mutation,
allowing an already-stale snapshot to become a durable `DONE` record. The default
uninstaller can likewise validate a clean source checkout and later recursively
delete user work created while external removal steps are running. In addition,
canonical subprocess tests inherit higher-priority data-root variables and can read
state outside their temporary profile, so the existing baseline and historical
Validation Report are not trustworthy release evidence for these paths.

Until these boundaries are repaired, the product must not claim that a default
uninstall removes source safely or that a terminal Dossier is current merely because
the terminal record was committed. The first remediation phase restores a hermetic
test baseline, contains the demonstrated Controller commit window with pre-write
revalidation plus post-write live freshness, and disables destructive source removal
until exact ownership can be proved.

## What Changes

- Make all repository-dependent mutations acquire membership, canonically sorted
  repository, and task locks in one order; derive a pure candidate from one complete
  snapshot and revalidate the same authority before replacement.
- Fail atomically when pre-write revalidation observes drift. Explicitly contain,
  rather than claim to eliminate, the residual interval from the last revalidation
  to atomic replacement.
- Separate immutable terminal evidence, atomic task commit, response-time live
  observation, and stored-only unknown freshness. A committed mutation remains a
  committed success when its post-write freshness is false or unknown, with blind
  retry forbidden and read-after-write required.
- Make default POSIX and PowerShell uninstall preserve source and report that source
  removal is safety-contained rather than successfully removed.
- Define a versioned exact-ownership manifest and quarantine protocol as the
  mandatory gate for any future re-enablement of source deletion; this phase does
  not infer ownership for existing installations.
- Make CLI, installer, uninstaller, managed-runtime, installed-journey, Web runtime,
  MCP runtime, and Windows lifecycle subprocess fixtures scrub every supported data
  authority, prove their resolved roots are temporary, and protect hostile-parent
  sentinels.

The finding dispositions for this phase are fixed: DFO-AUDIT-017 may become
`RESOLVED` only after the full authority matrix and trustworthy baseline pass;
DFO-AUDIT-001 is `CONTAINED — pre-write revalidation plus post-write live
freshness`; and DFO-AUDIT-002 is `CONTAINED — destructive source removal disabled`.

## Capabilities

### New Capabilities

- `capture-to-commit-authority`: lock ordering, commit-critical repository authority,
  and atomic failure semantics for repository-dependent mutations.
- `terminal-delivery-freshness`: immutable terminal evidence and dynamically observed
  workspace freshness.
- `exact-source-ownership`: the proof required before installer-owned source entries
  may ever be removed.
- `safe-uninstall-containment`: non-destructive default source handling while exact
  ownership is unavailable.
- `test-environment-isolation`: hermetic subprocess data, runtime, source, profile,
  marketplace, and executable authorities.

### Modified Capabilities

- `authoritative-plugin-installation`: supersede the historical default source
  deletion requirement so that every POSIX and PowerShell uninstall path preserves
  source until a versioned exact-ownership manifest exists.

The historical base and active OpenSpec material was removed by the current
documentation-only commit. This change restores only the canonical base needed for
the superseding delta and the validator-required historical traceability closure;
it does not restore archived changes, historical proposals, designs, or task plans.

## Impact

- `src/dev_flow_orchestrator/controller.py`, `store.py`, mutation receipt/freshness
  projection code, and Controller/MCP/CLI output contracts
- Controller, Store, Delivery, stale-mutation, and multi-repository tests
- POSIX and PowerShell uninstallers and host-neutral lifecycle tests
- shared subprocess test-environment fixtures
- English and Simplified Chinese uninstall guidance

Out of scope are DFO-AUDIT-003 through DFO-AUDIT-016 and DFO-AUDIT-018 through
DFO-AUDIT-024 except for the minimum Windows fixture isolation needed to prevent a
test from escaping its temporary roots. In particular, this phase does not repair
installer artifact transactions, runtime attestation, runtime ownership, Windows
product parity, or the public-document semantic validator.
