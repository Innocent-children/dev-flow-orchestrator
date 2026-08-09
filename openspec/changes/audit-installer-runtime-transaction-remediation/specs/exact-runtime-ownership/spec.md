## ADDED Requirements

### Requirement: Installation records exact ownership per entry

Before a release can be committed active, the installer SHALL complete a closed,
canonical, versioned exact-ownership record set. Its ownership body SHALL bind the
transaction, release, candidate, launcher identities, expected receipt path/schema,
and expected active-record path/schema/generation. Every release-asset path SHALL be
relative to a declared root and SHALL record entry type, file digest and size,
executable or mode information, symlink target, release ID, and necessary
parent-directory ownership.

The ownership body SHALL exclude its own bytes and the later receipt, activation
descriptor, terminal pre-commit journal, and active record bytes. The receipt SHALL
bind the ownership-body digest. The committed active record SHALL bind the receipt
and ownership-body digests and SHALL contain the ownership envelope for those
control files, the activation descriptor, terminal pre-commit journal, and its own
fixed path/schema/generation.
Its self digest SHALL be computed over canonical active-record bytes with the
self-digest field omitted. This one-way construction SHALL NOT contain a manifest,
receipt, or active-record digest cycle. Shared marketplace ownership SHALL identify
only the exact logical Dev Flow member and SHALL NOT claim the complete marketplace
file.

Current directory contents, a root marker, shallow receipt validity, package
version, location, or successful smoke SHALL NOT establish ownership.

#### Scenario: Runtime release ownership is recorded

- **WHEN** candidate and runtime staging completes
- **THEN** every installer-created runtime, plugin, metadata, verifier, launcher, and
  owned parent entry is in the ownership body, while its manifest file, receipt,
  activation descriptor, terminal journal, and active pointer are completed by the
  downstream committed ownership envelope

#### Scenario: Active release retains its terminal journal

- **WHEN** a committed release remains active and startup attestation validates its
  exact-ownership envelope
- **THEN** routine cleanup does not delete or rewrite the bound terminal journal;
  uninstall may remove it only after active attestation is no longer required

#### Scenario: Symlink ownership is recorded

- **WHEN** an installer-owned entry is a symbolic link
- **THEN** the manifest records the link itself and exact target text without
  treating the target as transitively owned

#### Scenario: Shared marketplace state is recorded

- **WHEN** the transaction replaces the Dev Flow marketplace member
- **THEN** ownership covers that canonical member value and comparison authority,
  while unrelated members and the containing file remain user/shared state

### Requirement: Uninstall removes only revalidated owned entries

Uninstall SHALL acquire the lifecycle authority, validate the receipt and ownership
manifest, and operate on entries without following symlinks or reparse points. It
SHALL remove a file or link only when its last-use type, digest, mode, target, root,
transaction, and release identity match. It SHALL remove an owned directory only
after all eligible children have been handled, the directory is empty at removal
time, and directory ownership matches. It SHALL NOT recursively delete a runtime or
release root.

Same-filesystem quarantine MAY contain races by atomically renaming an exact-owned
entry or release before per-entry deletion. Any unknown or changed entry found in
place or quarantine SHALL be retained and reported.

#### Scenario: All entries match ownership

- **WHEN** every selected installer-owned entry still matches its manifest and every
  owned directory becomes empty
- **THEN** those entries are removed individually, task data is unchanged, and the
  receipt reports exactly which roots became empty

#### Scenario: Unknown runtime-root content exists

- **WHEN** a file, directory, symlink, or special entry not present in the manifest
  exists directly under the runtime root
- **THEN** that entry and required ancestors remain and the uninstall result is
  truthful partial with its retained path

#### Scenario: Unknown release or venv content exists

- **WHEN** unknown content exists under an active or inactive release, venv,
  site-packages, scripts/bin, or distribution metadata directory
- **THEN** that content is retained in place or quarantine, no ancestor is removed
  recursively, and other component outcomes are reported separately

#### Scenario: Symlink or reparse content is unknown

- **WHEN** an unknown symlink, Windows reparse point, or changed owned link is found
- **THEN** uninstall neither follows nor deletes it and preserves its external
  target

#### Scenario: Special entry is unknown

- **WHEN** a socket, FIFO, device, or other unsupported special entry is present
- **THEN** it is retained and reported without using a whole-tree deletion fallback

#### Scenario: Content appears concurrently

- **WHEN** an entry appears or changes after initial enumeration but before its
  parent could be removed
- **THEN** last-use revalidation or quarantine enumeration preserves it and the
  result becomes partial rather than deleting the parent recursively

### Requirement: Legacy runtime content is preserved without adoption

A runtime or release lacking a conforming exact ownership manifest, or having a
missing, malformed, incompatible, or mismatched receipt, SHALL be retained. The
uninstaller SHALL name the retained path and explain that ownership is unavailable.
It SHALL NOT enumerate current contents and silently mark them owned. Repair MAY
install a new conforming release beside legacy content but SHALL NOT delete the
legacy path.

#### Scenario: Old runtime has only a shallow receipt

- **WHEN** uninstall finds a legacy marker and receipt but no exact manifest
- **THEN** it preserves the runtime, reports a partial outcome, and gives manual
  inspection guidance

#### Scenario: Successful repair replaces a legacy active runtime

- **WHEN** repair successfully commits a conforming new release while legacy content
  remains
- **THEN** the active record points only to the new release and separately records
  the retained legacy path without ownership adoption

#### Scenario: Adoption is requested

- **WHEN** an operator wants existing unknown runtime content treated as owned
- **THEN** the product requires a separately specified auditable adoption workflow
  and does not infer ownership in this lifecycle

### Requirement: Runtime ownership does not authorize source deletion

Runtime/plugin artifact manifests and source checkout ownership SHALL remain
separate authorities. This change SHALL NOT add or enable a source removal option.
Default uninstall, keep-source, and any unsupported explicit request SHALL preserve
the source checkout under DFO-AUDIT-002 containment, even for installations that
have conforming runtime ownership.

#### Scenario: New installation is uninstalled

- **WHEN** a Phase 1-conforming runtime has exact ownership but source lacks the
  separately accepted source ownership protocol
- **THEN** exact runtime entries may be handled per manifest while source is retained
  with its exact path and containment reason

#### Scenario: Task and unrelated marketplace data coexist

- **WHEN** uninstall handles exact-owned runtime entries
- **THEN** Controller task data and unrelated marketplace members remain
  byte-identical regardless of complete or partial runtime outcome

### Requirement: Platform evidence is reported without extrapolation

POSIX and PowerShell implementations SHALL preserve the same no-recursive-root,
per-entry ownership, unknown-content, legacy-preservation, and source-retention
invariants. A platform SHALL be claimed dynamically verified only after its native
lifecycle runs against isolated mutation authorities and external sentinels.

#### Scenario: Host-neutral PowerShell validation runs

- **WHEN** parser, static, receipt-contract, or non-native simulation checks pass on
  a non-Windows host
- **THEN** the evidence is labeled host-neutral/static and native Windows remains
  `NOT RUN — native Windows host unavailable`

#### Scenario: Native Windows evidence is later collected

- **WHEN** a supported isolated Windows host runs the destructive-boundary matrix
- **THEN** the report records native outcomes separately and does not rewrite prior
  static evidence as a native run
