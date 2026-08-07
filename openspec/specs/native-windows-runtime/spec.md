# native-windows-runtime Specification

## Purpose
TBD - created by archiving change add-native-windows-runtime. Update Purpose after archive.
## Requirements
### Requirement: The core runtime operates natively on common Windows x64 clients

The core controller and CLI SHALL operate without WSL, Git Bash, or Cygwin on Windows 10 22H2 x64 and Windows 11 x64 client systems using supported 64-bit CPython and Git for Windows. Runtime production code SHALL remain Python standard-library-only.

The documented support boundary SHALL exclude Windows Server, Windows ARM64, 32-bit Python, WSL execution, UNC/SMB/NAS repositories, `\\wsl$`, and mapped network storage. The runtime is not required to detect every unsupported Windows edition or storage technology merely to enforce that support statement.

#### Scenario: Supported Windows core lifecycle executes

- **WHEN** a user runs the core CLI against an ordinary local Git worktree on a documented Windows x64 client
- **THEN** task start, repository capture, next-action projection, action application, stored inspection, repository-path discovery, and cancellation execute without a POSIX compatibility layer

#### Scenario: Package imports on Windows

- **WHEN** the controller, store, Git client, and CLI modules are imported on Windows
- **THEN** no unavailable `fcntl`, POSIX process-group operation, or POSIX-only descriptor traversal is executed during import

#### Scenario: Unsupported environment is used

- **WHEN** the runtime is used on an environment outside the documented Windows client support boundary
- **THEN** the product makes no compatibility claim and does not require a broad SKU or filesystem-detection subsystem for this change

### Requirement: Host-specific mechanisms remain behind a minimal internal boundary

Platform-specific path, controller-storage, and subprocess behavior SHALL be contained within the private `_platform` package, except for one private Windows worktree-file observation branch in `git_client.py`. Workflow, contract, assurance, delivery, Dossier, and persisted-model code SHALL NOT gain separate Windows implementations.

The POSIX storage and process behavior SHALL be moved behind the boundary before its Windows counterpart is enabled, and that move SHALL preserve existing macOS observable behavior.

#### Scenario: POSIX behavior is extracted

- **WHEN** the current POSIX storage and process code is moved behind `_platform`
- **THEN** existing macOS error codes, state mutation behavior, Git bounds, snapshot validation, and focused product tests remain valid

#### Scenario: A new Windows mechanism is needed

- **WHEN** Windows requires a different lock, pipe-draining, termination, or file-observation mechanism
- **THEN** the difference is implemented at the private host seam rather than copied into the controller or workflow engine

### Requirement: Windows controller storage preserves ordinary mutation integrity

The Windows storage implementation SHALL prepare product directories with inherited access control, SHALL read regular state files, SHALL enumerate task directories, SHALL serialize task and membership mutations through exclusive inter-process lock files, and SHALL atomically replace state with a same-directory temporary file followed by `os.replace`.

Lock ownership SHALL remain tied to one open file descriptor and SHALL wait through ordinary contention until acquired or until a non-contention error occurs. A successful state read SHALL observe a complete old or new value. A failed replacement SHALL leave the previous committed state authoritative.

This requirement SHALL NOT claim custom DACL enforcement, parent-directory replacement protection, or sudden-power-loss durability.

#### Scenario: Two Windows writers contend

- **WHEN** two Windows processes attempt to mutate the same task or compete for the membership lock
- **THEN** exactly one process owns the lock region at a time and persisted task JSON remains valid

#### Scenario: State replacement succeeds

- **WHEN** a complete temporary state payload is flushed and `os.replace` succeeds
- **THEN** subsequent authoritative reads return the complete new state

#### Scenario: State replacement fails

- **WHEN** temporary writing or final replacement raises an operating-system error
- **THEN** the mutation returns the existing structured write failure and the previous committed target remains authoritative

### Requirement: Windows Git commands retain current bounds and structured failures

Every Windows Git command SHALL be started from an argument sequence with `shell=False`, binary stdout and stderr pipes, the current Git isolation environment, one monotonic timeout, one combined output limit, and optional cooperative cancellation. Stdout and stderr SHALL be drained concurrently so output on either pipe cannot deadlock the command.

When execution is cancelled, times out, exceeds its output limit, or encounters a reader failure, the runtime SHALL attempt to terminate the direct command and ordinary child processes, SHALL wait for direct-process cleanup, and SHALL accept no partial Git evidence as success.

`GitClient` SHALL preserve the current structured errors `GIT_UNAVAILABLE`, `GIT_COMMAND_TIMEOUT`, `GIT_COMMAND_CANCELLED`, `GIT_OUTPUT_TOO_LARGE`, and `GIT_COMMAND_FAILED`.

#### Scenario: Git succeeds with output on both streams

- **WHEN** Git exits zero before its deadline while producing bounded stdout and stderr
- **THEN** the runner returns the complete binary streams without shell interpretation or deadlock

#### Scenario: Git is cancelled or times out

- **WHEN** cancellation becomes set or the monotonic deadline expires before Git exits
- **THEN** process-tree cleanup is attempted, the corresponding current error code is returned, and no controller mutation records partial evidence

#### Scenario: Git output exceeds its budget

- **WHEN** combined stdout and stderr exceed the configured command limit
- **THEN** the command is aborted and `GIT_OUTPUT_TOO_LARGE` reports the limit and observed stream counts without treating truncated data as valid output

### Requirement: Windows repository paths use one practical canonical spelling

An admitted Windows repository root SHALL resolve to the exact top-level root of an existing local non-bare Git worktree. The runtime SHALL normalize its persisted spelling and comparison key for drive-letter case, separator style, redundant components, and trailing separators. The same rule SHALL apply to controller-data separation, repository IDs, task discovery, and Git-reported worktree and administration directories.

UNC, `\\wsl$`, and extended namespace roots SHALL be rejected before task state is created. This requirement SHALL NOT claim detection of every hard-link, short-name, mapped-drive, junction, or case-sensitive-directory alias.

#### Scenario: Equivalent Windows spellings are supplied

- **WHEN** two repository inputs identify the same local worktree but differ only by drive-letter case, separators, redundant components, or trailing separators
- **THEN** admission treats them as one canonical root and rejects duplicate membership

#### Scenario: Ordinary Unicode local path is supplied

- **WHEN** a local worktree path contains spaces or valid Unicode characters
- **THEN** the controller can persist the canonical root, run Git, capture it, and discover the task from a contained path

#### Scenario: Network namespace root is supplied

- **WHEN** a repository or controller data root uses UNC, `\\wsl$`, or a `\\?\` namespace spelling
- **THEN** the operation fails before revision-zero task state is written

### Requirement: Windows worktree observation produces the current snapshot model

For ordinary Windows worktrees, the runtime SHALL retain the current Git enumeration, index-aware evidence, bounded content, resource normalization, canonical ordering, digest validation, and repository-set wrapper. The Windows file observer SHALL handle missing paths, regular files, the filesystem's visible symbolic-link representation, and initialized Gitlinks, and SHALL reject unsupported ordinary directories or special entries selected for bounded evidence.

The observer SHALL compare lightweight before/opened/after file observations and the existing initial/final Git evidence. A detected change SHALL fail with the current instability behavior and SHALL NOT append a partial controller record.

The Windows observer is not required to provide handle-relative traversal, persisted physical identity, or cross-operating-system digest equality.

#### Scenario: Ordinary Windows changes are captured

- **WHEN** a worktree contains clean, staged, unstaged, untracked, or deleted paths within current bounds and remains stable during collection
- **THEN** the runtime emits one validated current workspace snapshot and the controller includes it in the current repository-set wrapper

#### Scenario: File or Git evidence changes during collection

- **WHEN** a bounded file observation or Git metadata differs before the snapshot is sealed
- **THEN** capture fails as unstable and the enclosing controller operation commits no record

#### Scenario: Git for Windows represents a symlink as a regular file

- **WHEN** repository configuration causes a symlink entry to be checked out as an ordinary file
- **THEN** the snapshot records the actual regular-file bytes rather than fabricating a filesystem symlink

### Requirement: Windows runtime support does not expand persisted compatibility scope

This change SHALL NOT alter current persisted task fields, Schema identifiers, `MODEL_VERSION`, workflow definitions, or replay rules solely to add the Windows host backend. It SHALL NOT introduce migration, translation, or cross-platform task-transfer code.

Existing current-version data may remain readable because its shape is unchanged, but that incidental behavior SHALL NOT be represented as a new historical compatibility guarantee or tested as a cross-version promise.

#### Scenario: Platform implementation changes without a Schema change

- **WHEN** the Windows backend is added and the persisted model remains structurally unchanged
- **THEN** product identity inputs and current Schema declarations remain governed by the existing product authority

#### Scenario: Historical migration is requested during implementation

- **WHEN** implementation proposes new migration or multi-version compatibility code solely to support this Windows runtime change
- **THEN** that work is rejected or moved to a separate explicitly authorized change
