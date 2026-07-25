## Why

The plugin currently contains POSIX-specific launch, locking, path, shell, and Git assumptions, while its test suite only proves behavior on a macOS host. Those gaps can prevent hooks from running or weaken deterministic workflow guards on Windows, so the plugin needs functionally equivalent, natively verified behavior on Windows, macOS, and Linux without relaxing its safety model or standard-library-only runtime constraint.

## What Changes

- Make controller, hook, and script execution platform-aware for executable discovery, shell command parsing, process handling, signals, temporary directories, UTF-8 text, and line endings.
- Make task identifiers, filesystem identity comparisons, default data directories, and workspace ownership safe across Windows and POSIX filesystem semantics.
- Make state locking fail closed on every supported operating system and verify mutual exclusion with native contention tests.
- Define capability-aware Git/worktree evidence behavior for executable bits, symlinks, and case sensitivity while retaining byte-accurate tracked-content evidence and deterministic gates.
- Add Windows-compatible hook commands and ensure skills, manifests, packaging, installation guidance, and user documentation expose equivalent workflows on all three operating systems.
- Replace platform-dependent test fixtures with portable helpers and add a native Windows/macOS/Linux CI matrix covering supported Python versions, hooks, controller behavior, Git/worktree flows, packaging, and validators.
- Add a shared, platform-neutral candidate identity plus byte-preserving handoff bundle so macOS, Windows, and Linux can bind one logical validation payload without depending on host executable bits or checkout line-ending transforms.
- Ship a project-local, standard-library Windows native-validation runner and launcher that a user can execute against explicit local and UNC aliases of the same existing writable directory, producing canonical-candidate-bound JSON evidence for the native long-path and legacy-code-page checks that cannot run on the current macOS host.
- **BREAKING**: Reject newly created task identifiers that are reserved, invalid, or path-equivalent on any supported platform; existing portable identifiers and persisted task schema remain compatible.

## Capabilities

### New Capabilities

- `cross-platform-runtime-safety`: Portable controller and hook behavior for paths, identifiers, locking, processes, text encoding, line endings, temporary storage, and platform defaults.
- `cross-platform-git-evidence`: Deterministic Git/worktree inspection and evidence generation across filesystem capability differences without weakening safety checks.
- `cross-platform-plugin-invocation`: Installable plugin metadata, hook launch commands, generated skill guidance, and documentation that work equivalently on Windows, macOS, and Linux.
- `cross-platform-verification`: Portable automated tests and native CI coverage that prove supported behavior and prevent platform regressions.

### Modified Capabilities

None. The repository has no existing OpenSpec capability specifications.

## Impact

The change affects the state-machine controller, hook runtime and configuration, skill instructions, plugin manifest and packaging inputs, canonical candidate identity and handoff scripts, project-local native-validation scripts, test fixtures and assertions, CI configuration, and English/Chinese installation and usage documentation. It changes no external runtime dependency policy, introduces no implicit Git mutation, and keeps workflow state outside target repositories.
