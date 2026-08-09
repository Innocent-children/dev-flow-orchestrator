## ADDED Requirements

### Requirement: Source deletion requires a versioned exact ownership manifest

The installer SHALL NOT authorize source deletion unless installation produced a
versioned exact ownership manifest bound cryptographically to the installation
receipt and authoritative source identity. The manifest SHALL enumerate each
installer-created relative path, expected filesystem type, content identity or
Git/tree identity, and symlink or other special-entry identity. It SHALL identify
its source root without accepting a caller-controlled replacement path.

Origin, branch, clean status, commit ancestry, root location, or a receipt that does
not enumerate exact entries SHALL NOT substitute for the manifest. Existing or new
installations without a conforming manifest SHALL preserve source and provide manual
recovery guidance that requires inspection, backup, and independent ownership
confirmation; they SHALL NOT be silently adopted, migrated, or directed to an
unconditional recursive deletion command.

#### Scenario: Legacy installation has no exact manifest

- **WHEN** uninstall examines a source checkout created before exact ownership was
  recorded
- **THEN** it preserves the checkout, identifies missing exact ownership as the
  reason, and performs no recursive source-root deletion

#### Scenario: An entry differs from the manifest

- **WHEN** a tracked, untracked, ignored, committed, linked, or special entry differs
  in path, type, or identity from the bound manifest
- **THEN** source removal fails closed and preserves every unknown or changed entry

### Requirement: Proven source removal uses containment and per-entry deletion

If source deletion is re-enabled in a later phase, the uninstaller SHALL first
atomically rename the proven source root to a unique same-filesystem quarantine. It
SHALL preserve any new content subsequently created at the original source path,
revalidate the quarantined tree against the exact manifest, and delete only entries
proved to be installer-owned. It SHALL never recursively delete the source or
quarantine root with `rm -rf`, `Remove-Item -Recurse`, or equivalent whole-tree
semantics.

Unknown content, a changed Git tree or branch, local-only commit, symlink or reparse
point mismatch, rename failure, or an entry appearing during deletion SHALL stop the
operation. The uninstaller SHALL restore the quarantine when safe or retain it for
manual recovery, return non-success or an explicit partial state, preserve task data,
and avoid a complete-uninstall claim.

#### Scenario: User work appears before quarantine

- **WHEN** a new file, ignored entry, tracked modification, symlink, or local commit
  appears after preflight but before source quarantine
- **THEN** exact validation fails and the user work remains present

#### Scenario: User work appears after quarantine

- **WHEN** a process creates new work at the original source path after the owned
  tree was quarantined
- **THEN** the new original-path work is not part of the quarantine and is preserved

#### Scenario: Unknown content is found in quarantine

- **WHEN** quarantine validation or per-entry removal encounters content outside the
  exact manifest
- **THEN** removal stops, preserves that content, and does not report complete source
  removal
