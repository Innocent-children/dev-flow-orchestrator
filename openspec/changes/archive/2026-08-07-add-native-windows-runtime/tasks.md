## 1. Freeze the touched behavior

- [x] 1.1 Record the current storage and Git error codes, mutation boundaries, and snapshot field sets; add only the missing POSIX regression tests needed to protect the extraction.
- [x] 1.2 Add a Windows import smoke for `controller`, `store`, `git_client`, and `cli` that initially exposes the unavailable host dependency.
- [x] 1.3 Add a scope assertion that this change does not alter current persisted fields, Schema identifiers, workflow definitions, or `PRODUCT_VERSION`.

## 2. Introduce the minimal host seam

- [x] 2.1 Add `_platform/__init__.py`, `paths.py`, `storage.py`, and `process.py` as private function-based modules; do not add factories, service classes, or public APIs.
- [x] 2.2 Move the current POSIX storage behavior behind `_platform.storage`, import `fcntl` only on non-Windows hosts, and keep `filesystem.py` as a compatibility façade.
- [x] 2.3 Move the current POSIX selector/process-group behavior behind `_platform.process` and prove the extraction with the existing macOS store, snapshot, controller, CLI, and installed-journey suites.

## 3. Implement practical Windows path handling

- [x] 3.1 Implement strict canonicalization for existing repository roots and non-strict canonicalization for a data root that may be created later.
- [x] 3.2 Normalize Windows paths with `normpath` and `normcase`, reject `\\`, `\\wsl$`, and `\\?\` anchors, and provide one equality/containment helper including the different-drive case.
- [x] 3.3 Route repository IDs, canonical ordering, duplicate and overlap checks, controller-data separation, task discovery, captured-root checks, and Git administration-directory checks through the helper.
- [x] 3.4 Test drive-case and separator aliases, redundant components, trailing separators, spaces, Unicode, different drives, nested roots, duplicate roots, UNC, and `\\wsl$`.

## 4. Implement Windows controller storage

- [x] 4.1 Implement directory preparation, regular state reads, and task-directory listing with inherited ACLs and final-entry type checks, without `chmod` or custom DACL code.
- [x] 4.2 Implement one-byte exclusive task and membership locks with `msvcrt.LK_NBLCK`, contention retry, descriptor-lifetime ownership, and guaranteed unlock cleanup.
- [x] 4.3 Implement same-directory temporary writes with complete binary write, flush, file `fsync`, close, `os.replace`, and failed-temporary cleanup while preserving existing structured errors.
- [x] 4.4 Add child-process contention tests for both lock types and success/failure tests proving complete replacement or preservation of the previous state.

## 5. Implement bounded Windows process execution

- [x] 5.1 Define the private runner result/failure contract and keep Git-specific command construction and `DevFlowError` mapping in `git_client.py`.
- [x] 5.2 Build the Windows Git environment from required Windows process variables plus the existing Git isolation variables, then start argument sequences with `shell=False`, binary pipes, `DEVNULL`, and `CREATE_NEW_PROCESS_GROUP`.
- [x] 5.3 Drain stdout and stderr concurrently with two reader threads, track exact stream byte counts, and enforce the existing combined output limit without accepting truncated success output.
- [x] 5.4 Coordinate normal exit, nonzero exit, monotonic timeout, cancellation, overflow, and reader failure; close pipes and join reader threads on every path.
- [x] 5.5 Terminate aborting commands through `%SystemRoot%\System32\taskkill.exe /PID <pid> /T /F`, then use direct `kill` as fallback, preserving all current Git error codes and bounded stderr.
- [x] 5.6 Test argument boundaries, simultaneous stdout/stderr, normal and nonzero exit, timeout, cancellation, output overflow, missing executable, and ordinary child cleanup.

## 6. Add the Windows worktree observer

- [x] 6.1 Keep Git enumeration, NUL parsing, index/HEAD handling, bounds, resources, ordering, digests, and repository-set orchestration shared.
- [x] 6.2 Add private Windows read/final-observation branches for missing paths, regular files, visible symlinks, initialized Gitlinks, and unsupported directories/special entries.
- [x] 6.3 Read regular files in bounded chunks and compare initial `lstat`, opened `fstat`, final `lstat`, and initial/final Git evidence; map detected changes to current instability behavior without mutation.
- [x] 6.4 Test clean, staged, unstaged, untracked, deleted, detached-HEAD, space/Unicode path, resource capture, and ordinary linked-worktree snapshots.

## 7. Prove the delivered slice

- [x] 7.1 Add one Windows single-repository journey covering start, preflight projection/application, next projection, inspection, controller path discovery, and cancellation.
- [x] 7.2 Add one two-repository admission/snapshot smoke proving canonical order and all-or-none failure when one member is unavailable.
- [x] 7.3 Add a focused Windows Python 3.12 CI job for import, path, storage, process, snapshot, and core-journey tests; retain the existing macOS job as the complete product regression gate.
- [x] 7.4 Run and record one Windows 11 x64 client smoke, run a shorter Windows 10 22H2 x64 smoke when available, and add a targeted regression test for every defect found.
- [x] 7.5 Run `openspec validate add-native-windows-runtime --type change --strict` and review the final diff for scope leakage into Hook, installer, Web UI, versioning, persisted fields, workflow, assurance, or Dossier code.
