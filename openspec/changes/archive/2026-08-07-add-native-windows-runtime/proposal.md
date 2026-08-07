## Why

Dev Flow's workflow, contract, assurance, and delivery logic is mostly platform-neutral, but the core runtime cannot currently operate natively on Windows. Controller storage imports `fcntl` at module import time; Git execution uses Unix process groups and pipe selectors; and workspace observation depends on POSIX descriptor-relative filesystem calls. As a result, even ordinary Windows repositories cannot complete the core task lifecycle without a POSIX compatibility environment.

The project is evolving quickly. The goal is therefore not to build a universal Windows abstraction or eliminate every theoretical filesystem and process edge case. The goal is to make the existing core product work on common Windows client machines, keep the platform-specific code contained, and learn from real defects after release.

## User Value

After this change, a developer using a common Windows 10 or Windows 11 x64 workstation can run the Dev Flow core controller and CLI directly with 64-bit Python and Git for Windows. They can create a task, capture repository evidence, obtain the next action, apply an action, inspect the task, resume it from a member repository, and cancel it without WSL, Git Bash, or Cygwin.

This is a runtime milestone. Native Codex Hook launch, PowerShell installation, Web UI release validation, and the final public Windows support claim remain later work.

## What Changes

- Add one small internal platform package for host path handling, controller storage, and bounded subprocess execution.
- Move the current POSIX storage and process behavior behind that package with minimal behavioral change.
- Add Windows implementations using Python's standard library and built-in Windows commands:
  - normalized local path handling;
  - ordinary directory and state-file operations;
  - `msvcrt.locking`-based inter-process locks;
  - same-directory temporary files plus `os.replace`;
  - concurrent stdout/stderr pipe draining;
  - timeout, cancellation, and output-limit enforcement;
  - best-effort process-tree termination through `taskkill /T /F` with direct-process fallback.
- Add a narrow Windows file-observation path inside `git_client.py` while retaining the existing Git enumeration, snapshot schemas, product bounds, and two-pass aggregate capture.
- Use one canonical Windows path spelling and comparison key for repository membership, overlap checks, task discovery, repository IDs, and Git-reported paths.
- Add focused Windows runtime tests and CI while retaining the existing macOS validation job as the main regression gate.

## What Does Not Change

- No separate `refactor-for-cross-platform` change is introduced.
- No workflow, assurance, contract, record, snapshot, Dossier, or public controller API is duplicated per platform.
- No persisted task shape, Schema identifier, product version, or workflow definition is changed solely for this runtime work.
- No historical-data migration or compatibility layer is added. Incidental readability of unchanged current-version data is not a new compatibility promise.
- No Codex Hook, `.cmd` launcher, PowerShell installer, uninstaller, Web UI release work, or public Windows installation command is delivered here.
- No custom ACL/DACL management, physical file identity, general PowerShell parser, suspended `CreateProcessW`, Job Object runtime, reparse-point framework, fuzzing, power-loss simulation, antivirus simulation, or exhaustive test matrix is introduced.

## Capabilities

### New Capabilities

- `native-windows-runtime`: Defines the first practical Windows client runtime boundary for paths, storage, Git processes, workspace observation, support scope, and core CLI behavior.

### Modified Capabilities

- `multi-repository-delivery`: Applies the existing exact repository-set and aggregate snapshot model to canonical ordinary Windows worktree paths.
- `task-discovery-boundaries`: Applies repository discovery and controller-data separation through the same Windows comparison keys used at admission.
- `package-delivery-validation`: Adds focused Windows runtime validation without duplicating the complete product suite on every platform.

## Impact

Expected production changes are concentrated in:

- `src/dev_flow_orchestrator/_platform/`;
- `src/dev_flow_orchestrator/filesystem.py`;
- `src/dev_flow_orchestrator/git_client.py`;
- `src/dev_flow_orchestrator/controller.py`;
- `src/dev_flow_orchestrator/store.py`;
- focused tests and `.github/workflows/focused.yml`.

The domain engine, workflow definitions, assurance logic, delivery contracts, Dossier generation, Hook assets, installer scripts, and Web UI protocol remain outside the implementation scope.

## Definition of Done

The change is complete when:

1. the package imports natively on Windows without loading unavailable POSIX modules;
2. ordinary local Windows repositories support the core controller lifecycle;
3. two Windows processes cannot corrupt one task through concurrent mutation;
4. Git timeout, cancellation, and output limits retain their structured error behavior;
5. clean, staged, unstaged, untracked, deleted, detached-HEAD, and ordinary linked-worktree evidence can be captured on Windows;
6. the focused Windows job passes; and
7. the existing macOS focused validation remains green.
