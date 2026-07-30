## ADDED Requirements

### Requirement: Capability-aware Git evidence profile
Before inspecting status, diffs, tracked files, or worktrees, the controller SHALL determine and record the effective filesystem and Git capabilities that affect `core.fileMode`, `core.symlinks`, and `core.ignoreCase`. Evidence commands MUST respect verified host capabilities instead of forcing incompatible values. The capability profile MUST be bound into the resulting evidence or fingerprint, and an unavailable or contradictory capability result MUST block a complete-evidence claim with a structured diagnostic.

#### Scenario: Inspect a typical Windows checkout
- **WHEN** Git reports `core.fileMode=false`, `core.symlinks=false`, and `core.ignoreCase=true` on a compatible Windows filesystem
- **THEN** a clean checkout remains clean, the evidence records those effective capabilities, and the controller does not pretend that POSIX mode, native symlink, or case-sensitive behavior was observed

#### Scenario: Inspect a POSIX-capable checkout
- **WHEN** a filesystem and Git configuration support executable modes, native symlinks, and case-sensitive names
- **THEN** the evidence profile enables and records those capabilities and subsequent evidence detects changes to the supported types and modes

#### Scenario: Encounter contradictory capability evidence
- **WHEN** Git configuration claims a capability that a deterministic filesystem probe disproves
- **THEN** the controller returns a structured capability blocker and does not certify the repository snapshot

### Requirement: Evidence contracts are versioned and downgrade-safe
Every capability-aware fingerprint, baseline, workspace proof, test record, and review snapshot SHALL bind an explicit evidence-contract version and capability-profile digest. Schema-v1 task state that predates this field MUST remain readable, but its legacy evidence MUST NOT satisfy a current downstream evidence gate until the current controller regenerates and records equivalent evidence. A controller encountering an evidence-contract version newer than it supports MUST return a structured compatibility blocker. The supported plugin update/rollback flow MUST NOT direct a pre-capability-profile build to resume or mutate a data directory containing current-contract evidence.

#### Scenario: Regenerate legacy evidence
- **WHEN** the current controller loads a readable schema-v1 task whose applicable baseline, workspace, test, or review evidence lacks the current evidence-contract version
- **THEN** it preserves the task state, marks that evidence stale for downstream gates, and requires phase-appropriate regeneration before the task advances

#### Scenario: Reject evidence from a newer contract
- **WHEN** a task or evidence record declares a contract version greater than the running controller supports
- **THEN** the controller returns `EVIDENCE_CONTRACT_UNSUPPORTED` and performs no state or Git mutation

#### Scenario: Refuse an incompatible rollback path
- **WHEN** rollback guidance or tooling evaluates a task data directory containing capability-aware evidence against a pre-profile plugin build
- **THEN** it refuses to describe that build as resumable, preserves task data and worktrees untouched, and directs recovery to a build supporting the recorded evidence contract

### Requirement: Capability limitations never become silent equivalence
The controller SHALL model each tracked entry using both its index semantics and its actual worktree representation. When a host cannot express an indexed mode, symlink, or set of case-distinct names, the controller MUST either bind the exact substitute representation and its limitation into evidence or fail closed when the representation is ambiguous or the requested safety claim depends on the unavailable semantic. It MUST NOT silently classify an unrepresentable tree as fully equivalent to a native checkout.

#### Scenario: Evidence a symlink placeholder
- **WHEN** a tracked symlink is checked out as a regular-file placeholder because native symlinks are disabled
- **THEN** the evidence records the index entry as a symlink, the worktree entry as a regular file, its raw bytes, and the lack of native symlink semantics

#### Scenario: Reject case-colliding tracked paths
- **WHEN** a tree contains case-distinct tracked paths that alias on the destination filesystem
- **THEN** worktree materialization or complete-evidence capture fails with a structured case-collision error before the controller marks the workspace or snapshot ready

#### Scenario: Retain executable-bit evidence when supported
- **WHEN** `core.fileMode` and the filesystem reliably expose executable-bit changes
- **THEN** the evidence detects and binds a tracked executable-bit change rather than ignoring it

### Requirement: Byte-accurate tracked worktree manifest
Every complete repository fingerprint and review snapshot SHALL retain an explicit, deterministically ordered manifest of cached tracked entries. For each entry the manifest MUST bind the raw path identity, index mode, object ID, stage, actual worktree type, size where applicable, and a SHA-256 digest of regular-file bytes or symlink-target bytes. Raw path bytes or an equivalent lossless platform representation MUST remain authoritative when a display string cannot represent the path, and initialized submodules MUST be covered recursively.

#### Scenario: Hash a tracked file without text conversion
- **WHEN** a tracked regular file contains CRLF, LF, non-UTF-8, or binary content
- **THEN** the manifest hashes the exact bytes present in the worktree without newline, encoding, clean-filter, or textconv normalization

#### Scenario: Preserve a non-displayable path identity
- **WHEN** the host permits a tracked path whose bytes cannot be decoded losslessly for display
- **THEN** the manifest retains a lossless path identity for hashing and sorting and uses any replacement-character rendering only as non-authoritative diagnostic text

#### Scenario: Capture an initialized submodule
- **WHEN** an initialized submodule has clean tracked content
- **THEN** the parent evidence binds the gitlink and recursively includes the submodule's tracked-byte manifest

#### Scenario: Detect a byte-only worktree change
- **WHEN** tracked worktree bytes change without a reliable mode or timestamp signal
- **THEN** the manifest digest changes and the snapshot cannot compare equal to the previous evidence

### Requirement: Complete evidence fails closed on hidden or executable transformations
Evidence commands SHALL neutralize external diff, textconv, replacement objects, lazy fetch, repository redirection, and other caller-controlled mechanisms that could alter the inspected repository or output. Repositories with hidden index flags, executable clean or process filters, unrepresentable dirty submodule content, or another condition that prevents complete byte evidence MUST be rejected with a structured blocker. Capability-aware behavior MUST NOT remove or weaken any of these checks.

#### Scenario: Reject a hidden tracked entry
- **WHEN** a tracked path is marked `assume-unchanged` or `skip-worktree`
- **THEN** the controller identifies the path and blocks complete evidence until the hidden index flag is cleared

#### Scenario: Reject an executable content filter
- **WHEN** a tracked path selects a Git clean or process filter
- **THEN** the controller blocks evidence or materialization before executing the filter and reports the affected path and filter

#### Scenario: Ignore hostile Git redirection
- **WHEN** the caller supplies repository, index, object, replacement-ref, external-diff, or textconv environment overrides
- **THEN** evidence remains bound to the approved repository and does not execute or trust the hostile override

#### Scenario: Reject dirty initialized submodule content
- **WHEN** an initialized submodule contains tracked or untracked worktree content not representable by its parent gitlink and snapshot
- **THEN** the controller blocks the complete-evidence claim and identifies the dirty submodule

### Requirement: Line-ending settings remain evidenced, not normalized
Git status and cleanliness checks SHALL use the repository's verified effective line-ending behavior rather than forcing a cross-platform checkout policy. The tracked worktree manifest MUST continue to hash on-disk bytes, including CRLF introduced by a legitimate checkout, while tree and index object IDs bind repository content. Evidence comparison MUST NOT rewrite files or hide byte changes in order to make Windows, macOS, and Linux fingerprints appear equal.

#### Scenario: Inspect a clean autocrlf checkout
- **WHEN** Git has legitimately produced CRLF worktree bytes under the repository's effective line-ending settings and reports the checkout clean
- **THEN** the controller records a clean status, hashes the actual CRLF bytes, and binds the relevant Git objects and capability profile

#### Scenario: Change only line-ending bytes
- **WHEN** the worktree bytes change from the previously evidenced line endings
- **THEN** the tracked manifest changes even if a text-oriented diff would normalize the content

### Requirement: Canonical worktree ownership identity
Workspace plans, durable claims, materialization checks, and later integrity checks SHALL compare source repositories, analysis worktrees, implementation worktrees, Git common directories, and destination paths by canonical filesystem identity. Equivalent drive-letter, slash, case-insensitive, Unicode-normalized, symlink, junction, and UNC spellings MUST map to one claim on filesystems where they alias. A workspace MUST remain independent from every source and analysis tree, and ambiguous or overlapping identities MUST be rejected before `git worktree add`.

#### Scenario: Reject an aliased destination
- **WHEN** a proposed destination reaches a source or analysis worktree through a different case, separator, drive, junction, symlink, or UNC spelling
- **THEN** workspace preparation rejects the plan before any Git mutation

#### Scenario: Reject a duplicate durable claim
- **WHEN** two tasks propose paths that resolve to the same filesystem identity
- **THEN** the workspace registry permits at most one live claim and the losing task receives a structured ownership conflict

#### Scenario: Preserve a distinct case-sensitive destination
- **WHEN** two paths differ only by case but the host proves they are distinct filesystem objects
- **THEN** the identity check keeps them distinct while still enforcing source, analysis, and workspace non-overlap

### Requirement: Portable repository path selectors
Every selector that is syntactically path-like SHALL be normalized as a path regardless of whether it uses `/`, `\`, drive syntax, UNC syntax, `.` segments, or the host's preferred separator. The controller MUST compare the normalized identity with both recorded source and canonical repository identities. A selector that matches zero or multiple repositories MUST fail deterministically and MUST NOT fall back to a basename guess.

#### Scenario: Select a Windows repository with forward slashes
- **WHEN** a configured repository is recorded with a native Windows path and the caller selects the same repository as `C:/path/to/repo`
- **THEN** the selector resolves to that repository exactly once

#### Scenario: Select a UNC repository
- **WHEN** a caller supplies an equivalent UNC path spelling for a configured repository
- **THEN** the selector uses canonical filesystem identity and resolves the configured repository without treating the server or share separator as an ordinary name

#### Scenario: Reject an ambiguous basename
- **WHEN** a non-path selector matches more than one configured repository basename
- **THEN** the controller returns `AMBIGUOUS_REPOSITORY` and performs no repository operation

### Requirement: Portable branch and ref identity
Workspace branch names SHALL pass Git's ref-format validation and MUST NOT be protected, symbolic, or path-equivalent to an incompatible existing ref on the host filesystem. Branch comparisons and durable claims SHALL bind the full Git ref and exact resolved object ID; case-folding MUST be used only to detect unsafe filesystem aliasing and MUST NOT change Git's logical ref spelling.

#### Scenario: Reject a case-colliding branch
- **WHEN** a planned branch differs only by case from an existing or protected branch on a ref storage filesystem where the names alias
- **THEN** the controller blocks workspace creation before creating or updating either ref

#### Scenario: Reject a symbolic workspace branch
- **WHEN** the planned workspace ref resolves through a symbolic ref
- **THEN** the controller rejects it and does not materialize the workspace

#### Scenario: Bind an existing safe branch
- **WHEN** an existing direct workspace branch has the approved base relationship and no ref-identity collision
- **THEN** the plan records its full ref and object ID and materialization verifies both before marking the workspace ready

### Requirement: Deterministic gated Git mutation
The controller SHALL execute Git with argument vectors and `shell=False`, sanitize repository-redirection and executable-hook inputs, and perform only the exact Git mutation authorized by the current expected revision and approved artifact. Before mutation it MUST hold the applicable task and workspace-registry locks and revalidate the base, branch, destination, ownership claim, and plan digest. It MUST NOT automatically stash, reset, clean, force-push, implicitly commit, fetch, or execute repository hooks.

#### Scenario: Attempt worktree creation without approval
- **WHEN** a caller requests worktree materialization without the matching approved workspace-plan digest and expected revision
- **THEN** the controller rejects the request before invoking a mutating Git command

#### Scenario: Materialize the approved plan
- **WHEN** the current revision, approved plan digest, base object, branch ref, destination identity, and ownership claim all match
- **THEN** the controller invokes only the recorded worktree operation with hooks disabled and without an implicit fetch, stash, reset, clean, commit, or push

#### Scenario: Change a precondition after approval
- **WHEN** the base ref, branch ref, destination identity, claim, or plan digest changes after approval
- **THEN** immediate pre-mutation validation fails and no Git mutation runs

### Requirement: Worktree readiness requires postcondition proof
The controller SHALL mark a managed workspace ready only after Git and filesystem postcondition checks prove that the destination is the canonical worktree root, shares the approved repository's common directory, is a linked worktree, has the exact approved branch and HEAD, is clean under the verified capability profile, and owns the matching durable claim. Any failed or ambiguous postcondition MUST leave the workspace unready and return structured recovery evidence.

#### Scenario: Verify a created worktree
- **WHEN** `git worktree add` completes for an approved plan
- **THEN** the controller independently verifies root, common directory, linked-worktree registration, branch, HEAD, cleanliness, capability profile, and durable claim before recording readiness

#### Scenario: Detect post-creation drift
- **WHEN** Git reports a different HEAD or branch, the destination aliases another tree, the worktree is dirty, or the claim no longer matches
- **THEN** the controller does not mark the workspace ready and reports the mismatched postconditions without performing a destructive cleanup

#### Scenario: Revalidate a ready workspace
- **WHEN** a later state transition depends on a previously ready workspace
- **THEN** the controller repeats ownership, Git identity, branch, HEAD, cleanliness, and claim-integrity checks before allowing the transition
