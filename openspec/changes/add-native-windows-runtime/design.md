## Context

The current runtime has a clear platform seam even though it is not yet expressed in code.

| Current area | Verified implementation | Windows consequence |
| --- | --- | --- |
| Controller storage | `filesystem.py` imports `fcntl` at module import and uses `flock`, `fchmod`, `O_NOFOLLOW`, `O_DIRECTORY`, `dir_fd`, and parent-directory `fsync` | Import fails immediately and the storage primitives cannot execute |
| Git process execution | `git_client.py` uses `selectors` for stdout/stderr pipes, `start_new_session=True`, `os.killpg`, `SIGTERM`, and `SIGKILL` | Windows selectors do not support pipe handles and Unix process-group cleanup is unavailable |
| Worktree file observation | `git_client.py` opens directories and files through POSIX descriptor-relative calls and verifies identities through `fstat` | Windows does not provide the same Python `dir_fd` behavior for these operations |
| Repository identity | `controller.py` and `git_client.py` resolve `Path` values and compare them directly | Drive-letter case, separators, and Git's forward-slash output need one Windows normalization rule |
| Validation | `.github/workflows/focused.yml` runs the full focused job only on macOS | Windows regressions are not detected before merge |

The workflow engine, model validation, delivery contracts, assurance rules, and Dossier logic do not require separate Windows variants. This change therefore extracts only the host mechanisms that have two real implementations.

## Goals / Non-Goals

### Goals

- Run the core controller and CLI on Windows 10 22H2 x64 and Windows 11 x64 client workstations.
- Use 64-bit CPython 3.9 through 3.14 and Git for Windows without third-party Python runtime dependencies.
- Keep platform-specific branches concentrated in a small internal package and the low-level snapshot observer.
- Preserve the existing controller state machine, error codes, product bounds, snapshot shapes, and all-or-none mutations.
- Keep macOS behavior operational while extracting the existing POSIX mechanisms.
- Validate ordinary developer workflows in enough detail to make implementation decisions testable.

### Non-Goals

- Windows Server certification or runtime SKU detection.
- Windows ARM64 or 32-bit Python support.
- WSL execution, UNC/SMB/NAS repositories, `\\wsl$`, or mapped network-drive support.
- ReFS, exFAT, removable media, cloud-sync directories, or case-sensitive Windows-directory guarantees.
- Historical task migration, cross-platform task transfer, or a new compatibility policy.
- Native Codex Hook launch, PowerShell installer/uninstaller, or Web UI release validation.
- Custom DACL/SID management, physical volume/file IDs, handle-relative Windows directory traversal, or complete reparse-point defense.
- A general-purpose subprocess library, filesystem framework, or platform capability hierarchy.
- Exhaustive boundary-plus-one, fuzz, soak, power-loss, antivirus, and filesystem-race testing.

## Validated Platform Inputs

The implementation choices below are based on documented platform behavior rather than assumptions:

1. Python selectors support sockets but not pipes on Windows, so the current selector loop cannot be reused for Git stdout/stderr pipes:
   - https://docs.python.org/3/library/selectors.html
2. `msvcrt.locking` locks a byte range from the current file position. `LK_LOCK` retries only ten times, while `LK_NBLCK` reports contention immediately. The Windows backend therefore uses a controlled `LK_NBLCK` retry loop rather than relying on the ten-second built-in retry:
   - https://docs.python.org/3/library/msvcrt.html
3. Python `subprocess.Popen` accepts an argument sequence on Windows and `shell=False` avoids shell interpretation. `Popen` remains the process-creation mechanism instead of a custom `CreateProcessW` wrapper:
   - https://docs.python.org/3/library/subprocess.html
4. Windows `taskkill /T` terminates a selected process and child processes started by it. It is available on Windows 10 and Windows 11 and is sufficient for the first practical process-tree cleanup implementation:
   - https://learn.microsoft.com/windows-server/administration/windows-commands/taskkill

These facts justify the selected first implementation. They do not create a promise that every descendant, filesystem alias, or hostile local race is controlled.

## Decision 1: Deliver extraction and Windows implementation in one change

There will be no independent cross-platform-refactor milestone. Work proceeds in this order inside the same change:

1. add regression coverage around the storage and Git behavior being moved;
2. move the current POSIX implementation behind a small private seam without changing its observable contract;
3. immediately add the Windows implementation for that same seam;
4. integrate it into one real Windows core journey; and
5. stop once the scoped acceptance criteria pass.

This prevents speculative interfaces from being designed before two real implementations exist.

A reviewable commit sequence is recommended:

```text
1. preserve POSIX storage behind the internal host seam
2. add Windows storage and path handling
3. preserve POSIX Git execution behind the process runner
4. add Windows Git execution and snapshot observation
5. complete the Windows core journey and CI gate
```

## Decision 2: Use a minimal internal platform package

Create only the following internal package initially:

```text
src/dev_flow_orchestrator/_platform/
├── __init__.py
├── paths.py
├── storage.py
└── process.py
```

The package uses small functions rather than service classes, factories, plugin registries, or capability objects.

### Responsibilities

`paths.py` owns:

- canonical repository roots;
- canonical controller data roots;
- Windows path comparison keys;
- equality and containment checks;
- normalization of Git-reported worktree and administration directories.

`storage.py` owns the current internal storage primitives:

- `ensure_private_directory`;
- `read_regular_file_at`;
- `list_directory_names_at`;
- `exclusive_file_lock`;
- `atomic_write_bytes`.

It conditionally imports `fcntl` only on POSIX and `msvcrt` only on Windows.

`process.py` owns one private bounded-process contract used by Git:

- start from an argument sequence with `shell=False`;
- capture binary stdout and stderr;
- enforce one deadline and one combined output budget;
- observe optional cancellation;
- terminate the process according to host behavior;
- return complete output or one typed internal failure.

`filesystem.py` remains as a compatibility façade so `store.py` does not need broad call-site changes. `git_client.py` delegates process execution to `_platform.process` but retains Git-specific commands, error messages, and output validation.

No other domain module imports `fcntl`, `msvcrt`, `selectors`, Windows commands, or OS-specific process termination.

### Complexity guard

Before implementation grows beyond these four private files, the change must show a second real caller or a confirmed defect that requires another seam. A directory tree of per-platform classes is not part of this design.

## Decision 3: Canonicalize ordinary Windows paths, not every physical alias

### Repository roots

Repository input continues to accept any user spelling that the current CLI accepts, including relative input. Admission resolves it to an existing directory and requires Git to confirm that it is the exact worktree root.

On Windows the canonical persisted spelling is:

```text
Path(value).expanduser().resolve(strict=True)
→ os.path.normpath(...)
→ os.path.normcase(...)
```

The normalized path is absolute, uses Windows separators, and is case-normalized. It is used both as the persisted root and as the comparison key. Persisting one spelling is important because repository IDs and repository-set identities currently include the path string.

The first implementation rejects paths whose Windows anchor begins with `\\`, including UNC, `\\wsl$`, and extended namespace spellings such as `\\?\`. It does not attempt to identify a mapped network drive.

### Controller data roots

The controller data root may not exist before first use. Its path is resolved non-strictly, normalized with the same Windows rule, and then created by the storage layer. Existing parent resolution follows Python's ordinary path semantics.

### Equality and containment

All admission, task discovery, overlap, and data-root separation checks use one helper over canonical keys. `os.path.commonpath` is used for containment; a different-drive `ValueError` means the paths do not contain one another.

### Git-reported paths

`git rev-parse --show-toplevel`, `--git-dir`, and `--git-common-dir` may use forward slashes and the administration directories may be relative. The runtime:

1. decodes the Git value as UTF-8;
2. joins a relative administration directory to the canonical repository root;
3. resolves it;
4. normalizes it through the host path helper; and
5. compares or persists only the normalized result.

### Intentionally unsupported aliases

The design does not promise to collapse:

- 8.3 short-name aliases;
- hard-link aliases;
- complex junction aliases;
- directories whose case-sensitive flag is enabled;
- a path replaced while an operation is in progress.

A confirmed user defect in one of these areas should produce a narrow follow-up fix and regression test.

## Decision 4: Preserve the storage API and implement ordinary Windows semantics

### POSIX behavior

The existing implementation is moved with minimal changes. Existing no-follow descriptor traversal, permission normalization, `flock`, file `fsync`, replacement, and parent-directory `fsync` remain the POSIX behavior.

### Windows directory preparation

`ensure_private_directory` on Windows:

1. rejects an existing final entry that is a symlink or not a directory;
2. calls `mkdir(parents=True, exist_ok=True)`;
3. verifies that the resulting final entry is a directory; and
4. preserves inherited ACLs without calling `chmod` or installing a DACL.

The word "private" remains the historical API name; on Windows it means product-owned location and valid access, not a newly authored ACL policy.

### Windows regular-file reads and directory listing

The backend builds the target from the trusted root plus validated relative components. It uses `lstat` on the final entry, rejects a final symlink and non-regular file for state reads, and rejects a final symlink and non-directory for listing.

The existing task-ID and fixed-component validation prevents `.` and `..` path selection. This change does not add a second path parser inside storage.

### Windows lock files

The lock implementation:

1. opens the lock file in binary update mode and keeps it open for the context lifetime;
2. creates one byte when the file is empty;
3. seeks to byte zero;
4. attempts `msvcrt.locking(fd, LK_NBLCK, 1)`;
5. retries recognized lock-contention errors after a short sleep until acquired;
6. raises `STATE_LOCK_FAILED` for non-contention failures;
7. yields to the caller while the descriptor remains open; and
8. seeks to zero and calls `LK_UNLCK` in `finally`.

A nonblocking retry loop is chosen because `LK_LOCK` has a fixed ten-attempt behavior that does not match the existing indefinite POSIX lock wait.

The same implementation protects task locks and the membership lock. It does not add lock timeouts or cancellation because current controller mutations have neither.

### Windows atomic state replacement

`atomic_write_bytes` on Windows:

1. creates a temporary file in the target directory;
2. writes the complete byte payload;
3. flushes Python buffers;
4. calls `os.fsync` on the temporary file descriptor;
5. closes the temporary file;
6. calls `os.replace(temp, target)`; and
7. removes a leftover temporary file after failure.

A successful authoritative read sees a complete old or new JSON value. A replacement failure maps to `STATE_WRITE_FAILED` and leaves the previously committed target authoritative.

The Windows backend does not attempt parent-directory `fsync`, custom write-through flags, or sudden-power-loss certification.

### Storage error compatibility

The existing public `DevFlowError` families remain:

| Operation | Existing error family |
| --- | --- |
| prepare data directory | `DATA_PATH_FAILED` / `DATA_PATH_UNSAFE` |
| acquire lock | `STATE_LOCK_FAILED` |
| read state | caller maps to `STATE_READ_FAILED` or task-specific errors |
| replace state | `STATE_WRITE_FAILED` |

Raw Windows exception text may remain in bounded internal `details` where the current API already reports operating-system errors. No new persisted error shape is introduced.

## Decision 5: Use a private bounded process runner with two host implementations

### Common contract

The runner accepts:

```text
command: sequence[str]
environment: mapping[str, str]
timeout_seconds: float
output_limit_bytes: int
cancel_event: optional Event-like object
```

It returns:

```text
returncode
stdout bytes
stderr bytes
```

or raises one private failure category that `GitClient` maps to the current `DevFlowError` codes:

```text
unavailable
cancelled
timeout
output-too-large
io-failed
```

Git command arguments and Git-specific messages remain in `git_client.py`; the runner does not know about repositories, snapshots, or Git error codes.

### POSIX runner

The existing selector loop, `start_new_session=True`, and TERM-to-KILL process-group cleanup are moved substantially unchanged. This preserves the mature path rather than replacing it with the Windows strategy.

### Windows runner

The Windows runner uses `subprocess.Popen` with:

```text
shell=False
stdin=DEVNULL
stdout=PIPE
stderr=PIPE
creationflags=CREATE_NEW_PROCESS_GROUP
```

Two reader threads drain stdout and stderr in binary chunks because Windows selectors do not support pipe objects. The threads:

- append only up to the configured combined limit;
- update exact stdout/stderr byte counts;
- signal overflow or an I/O error to the coordinator; and
- exit when the pipe closes.

The coordinator polls at the existing cancellation interval and evaluates, in order:

1. cooperative cancellation;
2. output overflow or reader failure;
3. monotonic deadline expiry;
4. child exit.

On any abort path, it terminates the process tree, waits for the direct process, closes pipes, and joins both reader threads before returning an error. On normal exit, it drains both pipes completely before evaluating the return code.

### Windows process-tree termination

The first implementation locates `taskkill.exe` from `%SystemRoot%\System32` when possible and invokes:

```text
taskkill.exe /PID <pid> /T /F
```

with `shell=False`, no inherited stdio, and a short cleanup timeout. If `taskkill` is missing, fails, or the direct process remains alive, the runner calls `process.kill()` and waits again.

This is a best-effort ordinary descendant cleanup strategy. A confirmed surviving Git descendant on a supported client system is the trigger for a later Job Object implementation; Job Objects are not preemptively introduced here.

### Windows Git environment

The current sparse Git environment is retained conceptually but includes the Windows variables required by ordinary executable and helper discovery:

```text
PATH
SystemRoot / SYSTEMROOT
WINDIR
COMSPEC
PATHEXT
TEMP
TMP
USERPROFILE
HOMEDRIVE
HOMEPATH
HOME when present
```

The runner then applies the existing Git isolation variables:

```text
GIT_CONFIG_NOSYSTEM=1
GIT_CONFIG_GLOBAL=os.devnull
GIT_TERMINAL_PROMPT=0
GIT_OPTIONAL_LOCKS=0
GIT_PAGER=cat
LC_ALL=C
LANG=C
```

This avoids copying the complete ambient environment while retaining the variables Git for Windows and Windows process startup ordinarily require.

## Decision 6: Keep Git orchestration common and add one Windows file observer

Git remains authoritative for:

- exact top-level worktree root;
- worktree-specific and common Git administration directories;
- object format;
- `HEAD` and branch;
- porcelain status;
- tracked and untracked paths;
- index stage entries; and
- HEAD-tree entries.

The command sequence, NUL-delimited parsing, product limits, index-aware snapshot schema, digest construction, and two complete controller capture passes remain common.

### POSIX observation

The current handle-relative directory and file observation remains unchanged on POSIX.

### Windows observation

`git_client.py` chooses a private Windows observation path at the existing `_read_path` and `_verify_observation` seam. It does not introduce a public `WorkspaceObserver` framework because there is only one caller.

For each validated Git-relative path, the Windows observer:

1. joins path components beneath the canonical root without accepting `.` or `..`;
2. records an initial `lstat` result;
3. handles missing paths without opening them;
4. reads a regular file in bounded binary chunks and compares `fstat`/`lstat` identity fields before and after;
5. reads a symbolic-link target when Windows exposes the entry as a symlink;
6. uses the existing Gitlink/submodule logic for mode `160000`;
7. rejects an ordinary directory or another unsupported special type; and
8. performs a final lightweight observation before sealing the snapshot.

The identity comparison may use the existing available stat fields (`st_mode`, `st_size`, `st_mtime_ns`, `st_ctime_ns`, `st_ino`, and link count where available). It is a change-detection aid, not a persistent Windows physical identity.

Git for Windows may check out a repository symlink as a regular file when symlink support is disabled. The observer records the filesystem representation it actually sees; it does not attempt to reconstruct a symlink from index metadata.

### Snapshot invariants retained

Windows snapshots retain:

- current workspace and repository-set Schema shapes;
- canonical relative Git paths using `/`;
- exact index stages and object IDs;
- per-file and total byte limits;
- complete status and index metadata;
- deterministic entry/resource ordering;
- complete digest validation;
- failure without controller mutation when capture is unavailable or unstable.

A snapshot digest is not required to match the digest of a separate checkout on another operating system because worktree mode and symlink representation can differ.

## Decision 7: Integrate canonical paths at the ownership boundaries

The path helper replaces direct path equality only where identity matters:

- `Controller._canonical_repositories`;
- repository ID derivation;
- root duplicate and overlap checks;
- controller-data/repository separation;
- captured root and Git administration-directory comparison;
- task-path discovery;
- snapshot root verification.

Domain validation in `model.py` continues to validate persisted strings lexically. It does not become a filesystem-aware module.

The persisted Windows path spelling is already normalized before a `RepositoryRecord` is created, so current byte-stable ordering and repository-set digest construction remain deterministic without adding platform fields to persisted state.

## Decision 8: Do not change version or persisted contracts in this runtime change

Adding a host backend does not require a new task shape. This change therefore does not modify:

- `PRODUCT_VERSION`;
- `PLUGIN_DATA_NAMESPACE`;
- `product_schema()` results;
- `PRODUCT_IDENTITY` inputs;
- workflow definitions;
- record or snapshot fields; or
- replay rules.

The project does not promise historical compatibility, but it also does not create unrelated version churn to implement a storage and process backend. A later release change may advance the product version according to the repository's normal release policy.

Tests SHALL verify only that this change does not accidentally alter persisted shapes. They SHALL NOT establish a new cross-version or cross-platform migration guarantee.

## Decision 9: Validate by layer instead of duplicating the full product matrix

### Windows automated validation

Add a focused Windows job, initially on GitHub's maintained Windows runner with Python 3.12. The runner is test infrastructure, not an expansion of the documented client support claim.

The job runs:

1. package import smoke;
2. path helper tests;
3. storage and cross-process lock tests;
4. bounded process-runner tests;
5. representative Git snapshot tests; and
6. one core controller journey.

It does not rerun every workflow, assurance profile, installed journey, documentation check, or boundary maximum.

### macOS regression validation

The existing macOS focused job remains the authority for the complete product suite. Touched low-level tests are kept or expanded to prove that POSIX extraction did not change observable behavior.

### Client acceptance smoke

Before the change is treated as ready for the later Hook and installer work, run one manual or self-hosted smoke on a real Windows 11 x64 client and, when available, one shorter Windows 10 22H2 x64 smoke.

The Windows 11 smoke executes:

```text
create ordinary local repository
→ start lite task
→ project preflight
→ apply preflight
→ project next action
→ inspect task
→ resume discovery through controller API
→ cancel task
```

This change does not claim full product installation on Windows because native Hook and installer work is deferred.

## Verification Matrix

| Area | Representative success | Main failure | Assertions |
| --- | --- | --- | --- |
| Import | import `controller`, `store`, `git_client`, `cli` on Windows | accidental `fcntl` import | import succeeds; no unavailable POSIX module is loaded |
| Path | local path with spaces and Unicode | UNC / `\\wsl$` root | stable canonical spelling; duplicate and containment decisions are correct |
| Data root | create new nested data root | final entry is a file or symlink | directories are created or a structured data-path error is returned |
| Task lock | second process waits while first holds byte zero | lock open or non-contention lock error | one process owns the region; state remains valid |
| Atomic write | replace existing state | `os.replace` failure injected | complete new bytes on success; old bytes remain authoritative on failure |
| Process output | child writes both stdout and stderr | combined output exceeds limit | both streams drain without deadlock; output error is structured |
| Process deadline | child exits normally | child exceeds timeout | timeout error; direct process is no longer running |
| Cancellation | uncancelled Git command | cancellation event set | cancellation error; no partial task mutation |
| Git identity | exact local root | nested directory or different root | exact-root rule is retained using Windows path keys |
| Snapshot | clean/staged/unstaged/untracked/deleted | file or metadata changes during capture | valid current snapshot or `SNAPSHOT_UNSTABLE`, never partial state |
| Linked worktree | ordinary initialized linked worktree | duplicate common directory in one task | current topology rules are retained |
| Core journey | one local repository | Git unavailable during admission | ordinary lifecycle succeeds or start fails before task state exists |
| Regression | existing macOS focused suite | changed POSIX error/shape | suite remains green and schemas/digests remain internally valid |

## Failure Behavior

| Failure | Required result |
| --- | --- |
| unsupported or malformed root | fail before revision-zero state |
| Windows lock cannot be opened/acquired | `STATE_LOCK_FAILED`; no mutation |
| temporary state file cannot be written | `STATE_WRITE_FAILED`; previous target remains authority |
| Git executable cannot start | `GIT_UNAVAILABLE` |
| Git timeout | `GIT_COMMAND_TIMEOUT`; process cleanup attempted |
| Git cancellation | `GIT_COMMAND_CANCELLED`; process cleanup attempted |
| Git output limit exceeded | `GIT_OUTPUT_TOO_LARGE`; no partial output accepted |
| Git returns nonzero | `GIT_COMMAND_FAILED` with bounded stderr |
| snapshot file changes during observation | `SNAPSHOT_UNSTABLE`; no controller record |
| unsupported filesystem entry in bounded path set | existing snapshot special-file error |
| one member fails in an aggregate capture | no member evidence is committed |

## Alternatives Considered

### Complete platform refactor before Windows work

Rejected. It would create interfaces before their Windows requirements were known and deliver no user capability by itself.

### Add `if os.name == "nt"` throughout existing modules

Rejected. A few branches inside `_platform` and the low-level snapshot observer are acceptable; spreading them through controller, store, engine, Hook, and Web UI would multiply future maintenance.

### Replace all process handling with one new thread-based implementation

Rejected for this change. The existing POSIX selector/process-group implementation is mature. Keeping two private runner branches reduces macOS regression risk.

### Use Job Objects and direct `CreateProcessW`

Deferred. They offer stronger descendant ownership but require substantially more Windows-specific handle and pipe code. `Popen` plus `taskkill /T` is sufficient until a supported-environment defect proves otherwise.

### Use `LockFileEx` or `pywin32`

Deferred. `msvcrt.locking` is available in every supported CPython and is adequate for one-byte lock files. A confirmed lock defect can justify a thin `LockFileEx` implementation later. Third-party runtime dependencies remain disallowed.

### Install custom DACLs

Rejected. The runtime should use the access policy of the supplied data location, especially when launched under Codex sandbox identities. This change verifies access rather than inventing a Windows security policy.

### Persist Windows volume and file IDs

Rejected. Current task identity is path-based, historical compatibility is not a goal, and ordinary developer repositories do not require a new persisted identity model.

### Advance the product version as part of the backend work

Rejected. No persisted shape changes. A version advance would force unrelated manifest, workflow, Skill, validator, documentation, and installed-evidence edits, obscuring the runtime change.

## Risks and Follow-up Triggers

| Risk accepted now | Trigger for follow-up |
| --- | --- |
| `taskkill` misses a real Git descendant | reproducible surviving child on supported Windows client → add Job Object process ownership |
| `msvcrt.locking` behaves incorrectly in a supported environment | reproducible overlapping mutation or false lock failure → replace Windows lock primitive |
| canonical text path misses a common alias | real duplicate/lease defect on supported local path → add targeted canonicalization |
| junction or reparse behavior escapes the expected root | confirmed ordinary-user defect → reject or handle that specific form |
| antivirus temporarily blocks replacement | recurring supported-environment failures → add bounded retry around the exact operation |
| Windows file mode causes inappropriate evidence drift | confirmed workflow defect → normalize only the affected mode semantics |

The project fixes these problems when observed; they are not preimplemented as hypothetical frameworks.

## Implementation and Rollback

Implementation is additive until the final integration switch. The POSIX code is first moved behind `_platform` and proven by existing tests. Windows code is then activated only when `os.name == "nt"`.

If Windows integration is not ready, the change can be rolled back by restoring the direct POSIX imports and removing the Windows job; no persisted migration or one-way data conversion has occurred.

## Complexity Check

This design intentionally adds:

- one four-file private platform package;
- one Windows branch at the existing snapshot file-observation seam;
- focused platform tests; and
- one CI job.

It intentionally does **not** add:

- another controller or workflow implementation;
- new public APIs or persisted fields;
- factories or platform registries;
- a release/install subsystem;
- a complete Windows security runtime; or
- a second copy of the product test suite.

If implementation requires platform branches in the workflow engine, assurance, delivery, model replay, or Dossier code, the design must be reviewed again because the host boundary has leaked.
