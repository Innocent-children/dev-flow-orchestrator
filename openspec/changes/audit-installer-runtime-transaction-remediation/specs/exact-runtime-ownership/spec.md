## ADDED Requirements

### Requirement: New releases record simple exact ownership

Every new managed release SHALL have one closed, versioned ownership manifest. For
each owned entry it SHALL record a declared root, normalized relative path,
`release_id`, entry type, regular-file digest, executable bit or mode, and symlink
target text as applicable. The manifest SHALL contain only concrete deletion
evidence and SHALL NOT infer ownership from current directory enumeration, a root
marker, package version, location, or successful health.

The manifest SHALL cover installer-created plugin and runtime release payloads,
launchers, metadata, and owned parent directories. Shared marketplace ownership
SHALL cover only the Dev Flow member, not the entire marketplace file. Runtime
ownership SHALL NOT grant source-checkout ownership.

#### Scenario: Regular files and directories are installed

- **WHEN** a new plugin/runtime release and its launchers are promoted
- **THEN** every installer-created regular file and necessary owned directory has
  exact relative-path, type, digest or mode, and `release_id` evidence

#### Scenario: A symlink is installed

- **WHEN** an installer-owned release entry is a symbolic link
- **THEN** the manifest records the link itself and exact target text without
  treating the target as owned

#### Scenario: Pre-existing content shares a managed parent

- **WHEN** a selected runtime or launcher parent existed before installation
- **THEN** the manifest records only entries actually created or replaced by the
  installer and does not claim the pre-existing parent contents

### Requirement: Uninstall removes only matching owned entries

Uninstall SHALL validate the exact manifest and process each known entry without
following links or reparse points. It SHALL use `lstat` at last use and SHALL remove
a regular file or symlink only when type, digest, mode, target, root, and
`release_id` match. It MAY first rename a matching file or symlink to a
same-filesystem quarantine entry, then revalidate and unlink it. A mismatch SHALL be
restored when safe or retained and reported.

Owned directories SHALL be processed deepest first and removed only with
non-recursive `rmdir` after they are proven owned and empty at removal time. The
uninstaller SHALL NOT recursively delete a managed runtime root or release root with
shell, PowerShell, Python, or an equivalent helper.

Unknown, changed, concurrent, special, or unverifiable entries SHALL be retained,
along with required ancestor directories. A partial result SHALL name retained
paths. External symlink targets, Controller task data, source, and unrelated
marketplace members SHALL remain unchanged.

#### Scenario: Every selected entry still matches

- **WHEN** all selected owned files, links, and directories match the manifest and
  owned directories become empty
- **THEN** entries are removed individually and only empty owned directories are
  removed with non-recursive `rmdir`

#### Scenario: Unknown runtime-root content exists

- **WHEN** an unowned file or directory exists directly under the runtime root
- **THEN** it and its required ancestors remain and the runtime result is partial
  with the retained path

#### Scenario: Unknown active or inactive release content exists

- **WHEN** an extra entry exists under an active release, inactive release, venv,
  site-packages, bin/scripts, or distribution metadata directory
- **THEN** the entry remains in place or quarantine, no ancestor is recursively
  removed, and other component outcomes are reported separately

#### Scenario: A known owned file has changed

- **WHEN** an owned regular file's type, digest, or mode differs at last-use
  validation
- **THEN** the changed entry is retained, its ancestors remain, and the result names
  the mismatch instead of unlinking it

#### Scenario: An unknown link targets external data

- **WHEN** an unknown or changed symlink or reparse point resolves outside the
  managed root
- **THEN** uninstall neither follows nor removes the link and the external target
  remains byte-identical

#### Scenario: A special entry exists

- **WHEN** a FIFO, socket, device, or other unsupported special entry is found
- **THEN** it is retained and reported without invoking a recursive fallback

#### Scenario: Content appears during removal

- **WHEN** an entry is created or replaced after initial inventory but before its
  parent directory could be removed
- **THEN** last-use `lstat` or non-recursive `rmdir` preserves it and the result is
  partial

### Requirement: Legacy runtime content is retained without adoption

A runtime or release lacking the exact manifest, or having a missing, malformed,
incompatible, or mismatched manifest/receipt, SHALL be retained. The uninstaller
SHALL return partial, name the retained path, and provide manual inspection and
backup guidance. It SHALL NOT enumerate current contents and relabel them as owned.
Repair MAY select a new conforming release beside legacy content and SHALL report
the retained legacy path.

#### Scenario: Legacy runtime has only a shallow receipt

- **WHEN** uninstall finds a legacy marker or receipt but no conforming exact
  ownership manifest
- **THEN** the complete runtime is retained with a partial result and manual
  inspection guidance

#### Scenario: Repair replaces a legacy selected runtime

- **WHEN** repair successfully selects a new receipt-v2 release while legacy
  runtime content remains
- **THEN** only the new release is selected and the legacy path is reported as
  retained without ownership adoption

### Requirement: Runtime removal preserves source and unrelated data

Default uninstall, keep-source behavior, and any unsupported explicit source-removal
request SHALL retain the authoritative checkout under DFO-AUDIT-002 containment.
Exact runtime ownership SHALL NOT authorize source deletion. Controller task data
and unrelated marketplace members SHALL remain byte-identical for complete and
partial runtime outcomes.

#### Scenario: A new exact-owned runtime is uninstalled

- **WHEN** a conforming runtime is eligible for exact per-entry removal
- **THEN** only matching runtime entries are handled while source and Controller task
  data are retained

#### Scenario: Unrelated marketplace entries coexist

- **WHEN** uninstall removes the Dev Flow marketplace member
- **THEN** every unrelated member remains unchanged regardless of runtime outcome

### Requirement: Platform evidence is reported separately

POSIX and PowerShell SHALL implement the same prohibition on recursive managed-root
deletion, per-entry ownership checks, unknown-content retention, legacy retention,
and source retention. Dynamic platform success SHALL be claimed only after native
lifecycle execution in isolated temporary authorities.

#### Scenario: Host-neutral PowerShell checks run

- **WHEN** parser, static, or host-neutral PowerShell checks pass on a non-Windows
  host
- **THEN** the evidence is labeled host-neutral/static and native Windows remains
  `NOT RUN — native Windows host unavailable`

#### Scenario: Native Windows evidence is unavailable

- **WHEN** no supported isolated Windows host is available for lifecycle execution
- **THEN** the change does not report Windows dynamic PASS or infer it from POSIX
  results
