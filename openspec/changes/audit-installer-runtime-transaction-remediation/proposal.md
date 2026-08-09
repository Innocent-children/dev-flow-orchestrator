## Why

Current-head evidence in `REPRODUCTION.md` shows five concrete lifecycle defects:

- `DFO-AUDIT-006`: verification selects a Git commit, but later install steps read
  the mutable checkout and can activate different bytes while retaining the old
  commit in the receipt.
- `DFO-AUDIT-007`: late failure can leave mixed plugin, marketplace, launcher, and
  runtime state; rollback may re-add the updated source while claiming the previous
  release was restored.
- `DFO-AUDIT-008`: startup does not consult the runtime receipt, and repair reuses
  runtimes whose package, metadata, RECORD, or dependency content has drifted.
- `DFO-AUDIT-009`: source-side Python execution creates ignored bytecode during
  install and repair.
- `DFO-AUDIT-010`: uninstall shallowly checks a runtime and then recursively removes
  its root, including unknown and concurrently created content.

This change closes those reproduced paths with focused additions to the existing
install, repair, upgrade, launcher, runtime-management, and uninstall flows.

## What Changes

- Run every Python command sourced from the authoritative checkout with `-B` and
  command-scoped `PYTHONDONTWRITEBYTECODE=1`. Prefer the staged release for package
  validation, runtime build, health, and launcher generation. Compare final HEAD
  and complete tracked, untracked, and ignored Git inventories with the selected
  source baseline after success and failure without deleting source residue.
- Remove every whole-tree runtime or release deletion. New installations write a
  small versioned ownership manifest containing relative path, entry type, file
  digest, executable/mode, symlink target, and release ownership. Uninstall uses
  per-entry `lstat`, `unlink`, and empty-directory `rmdir`; unknown, changed,
  concurrent, and special entries are retained. A legacy runtime without the exact
  manifest is retained and reported as partial.
- Export the verified Git commit/tree into transaction-owned staging with safe
  archive extraction, then build the plugin release, wheel, runtime, launchers, and
  health inputs from that staging. The personal marketplace and `codex plugin add`
  target the installer-owned release-specific plugin path. One `release_id` binds
  every installed consumer and its receipt evidence.
- Upgrade the existing runtime receipt to v2 and add one shared standard-library
  verifier used by POSIX and PowerShell launchers before importing Dev Flow. The
  receipt records installed package, metadata, RECORD, dependency, Python,
  launcher, release, and ownership evidence. Repair reuses only a complete match
  and otherwise rebuilds a new staged release.
- Add one small bounded record for the current install, upgrade, or repair attempt.
  It records optional `transaction_id`, operation, previous and candidate releases,
  current step, observed component state, and terminal outcome. Previous and
  candidate releases are staged before real activation changes. Every Codex command
  is followed by observation of actual state. Late failure restores the sealed
  previous release and verifies it, or returns a durable `partial` result with
  retained paths and `blind_retry_safe=false`.
- Convert the current-head reproductions into permanent isolated regression tests
  for DFO-AUDIT-006 through DFO-AUDIT-010.

## Capabilities

### New Capabilities

- `immutable-install-candidate`: verified Git-tree export, sealed release creation,
  shared `release_id`, and authoritative-source preservation.
- `installer-runtime-transaction`: bounded attempt record, concrete activation
  order, previous-release rollback, actual Codex observation, and truthful partial
  outcomes.
- `runtime-startup-attestation`: receipt v2, pre-import verification, and
  rebuild-on-mismatch repair.
- `exact-runtime-ownership`: simple per-entry ownership, contained uninstall, and
  legacy-runtime retention.

### Modified Capabilities

- `authoritative-plugin-installation`: the personal marketplace keeps unrelated
  entries and points Dev Flow at the sealed plugin release.
- `authoritative-plugin-installation`: Windows source retention continues to apply
  while managed runtime removal follows exact per-entry ownership.

## Scope and Compatibility

This change covers only DFO-AUDIT-006 through DFO-AUDIT-010. It keeps the public
install commands, plugin ID, personal-marketplace mode, bundled MCP mode, source
checkout workflow, and task-data namespace unchanged. It reuses the existing shell
and PowerShell lifecycle scripts, `scripts/manage_runtime.py`, launchers, receipts,
and test fixtures; a shared standard-library helper may be added where POSIX and
PowerShell need the same validation logic.

The only internal identities are `release_id` and, when needed to identify one
attempt, `transaction_id`. DFO-AUDIT-002 remains
`CONTAINED — destructive source removal disabled`: runtime ownership never grants
source-deletion authority, and no source checkout is automatically removed.

Other audit findings and migration or adoption of legacy runtime content are outside
this change. Verification and recovery claims are limited to the deterministic
DFO-AUDIT-006 through DFO-AUDIT-010 paths specified here.

## Platform Evidence Boundary

All lifecycle tests use isolated temporary authorities and fake Codex/Git services.
POSIX behavior may be exercised dynamically on this host. PowerShell receives the
same product semantics, but this host runs only parser, static, host-neutral, and
safe simulation checks. Native Windows status remains
`NOT RUN — native Windows host unavailable`.
