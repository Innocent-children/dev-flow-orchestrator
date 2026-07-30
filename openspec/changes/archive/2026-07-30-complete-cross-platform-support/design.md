## Context

`dev-flow-orchestrator` is a standard-library-only Python plugin whose controller owns durable workflow transitions and whose hooks provide resumability and best-effort guardrails. The current implementation and tests were developed on POSIX-like hosts: bundled hooks launch `python3`, Windows lock failures can fall through to an unlocked critical section, command parsing assumes POSIX shell syntax, and Git evidence forces filesystem capabilities that normal Windows and case-insensitive macOS worktrees may not provide.

The change crosses the controller, hook protocol, Git evidence, skills, packaging, documentation, and release validation. The safety-sensitive call path is:

`CLI mutation -> task/workspace lock -> revision and approval checks -> Git or state operation -> atomic state/event commit`.

The hook path is deliberately different:

`Codex event -> non-mutating parser/context lookup -> advisory context or guardrail decision`.

The controller must remain authoritative even when hooks are absent or fail open. Existing schema-v1 task files with portable identifiers must remain readable. Python 3.9+ and Git remain host prerequisites; OpenSpec and codebase-memory remain optional external integrations rather than runtime imports.

## Goals / Non-Goals

**Goals:**

- Provide the same state-machine, approval, locking, Git/worktree, hook, and evidence outcomes on native Windows, macOS, and Linux.
- Fail closed before protected mutation whenever lock ownership, path identity, filesystem capability, or complete Git evidence cannot be established.
- Preserve deterministic, byte-accurate repository evidence while representing host filesystem limitations explicitly.
- Keep controller and hook runtime code on the Python standard library and keep Git invocation argument-vector based with `shell=False`.
- Ship portable hook registration, workflow guidance, package contents, tests, native CI, and bilingual documentation as one verifiable contract.
- Ship a safe project-local Windows validation entry point that lets a user on a separate Windows host produce structured evidence for native-only checks without granting publication, plugin installation, or access to live workflow state.
- Bind cross-host validation to a canonical source/package identity that is independent of host mode bits and is delivered to Windows without byte transformations, while retaining a separate host-local full-snapshot digest for complete review.
- Keep persisted changes additive except for stricter validation of newly requested non-portable task identifiers.

**Non-Goals:**

- Migrating one active task or data directory between operating systems. Absolute paths and filesystem identities remain local to the host that created them.
- Bundling Python, Git, OpenSpec, codebase-memory, or a POSIX compatibility layer.
- Emulating POSIX executable modes, symlinks, case sensitivity, or signals when the host cannot provide them.
- Turning hooks into an unbypassable security boundary or moving durable transitions into hook code.
- Automatically stashing, resetting, cleaning, fetching, committing, force-pushing, or deleting recovery evidence.
- Automatically creating or removing Windows network shares, changing a machine-wide console code page or Git configuration, publishing code, installing the plugin, or reusing an active task data directory during self-test.
- Modifying target business repositories to support the plugin.

## Decisions

### 1. Keep platform primitives explicit and local to each trust boundary

The controller will introduce small standard-library helpers for non-empty environment lookup, protocol I/O, portable task identity, filesystem identity, process execution, locking, and Git capability discovery. The hook will keep a smaller self-contained set for protocol I/O, executable identity, and shell-aware command inspection.

The hook will not import a broad new platform abstraction from the controller. A controller import failure inside a hook would otherwise enlarge the hook's fail-open surface. Shared behavior will instead be fixed by contract tests that feed the same cases through controller and hook boundaries.

**Alternative considered:** one shared cross-platform utility module. Rejected because hook startup must stay small and independently fail open, whereas controller mutation helpers must fail closed and return structured errors.

### 2. Make every mutation lock acquisition fail closed

Lock files will be opened in binary update mode and contain a stable byte so both POSIX `flock` and Windows byte-range locking protect a non-empty range. Acquisition and release will seek to the documented range and translate unsupported, timed-out, or failed operations into structured lock errors. No exception path may yield the critical section without verified ownership.

Task creation will also serialize portable task-namespace identity checks, preventing concurrent creation of identifiers with the same ASCII case-folded identity. The existing per-task, workspace-registry, and configuration lock scopes remain deterministic. Kernel release after process death remains the recovery mechanism; the controller never deletes a possibly live lock file as a recovery shortcut.

An unlock failure cannot roll back a state file already atomically committed. It will therefore be reported as a lock-integrity error, leave recovery evidence intact, and prevent the caller from treating the operation as an ordinary successful continuation.

**Alternative considered:** retain best-effort Windows locking and rely on expected revisions. Rejected because two writers can read the same revision before either commit and because revision checks are not a substitute for mutual exclusion.

### 3. Separate portable names from host filesystem identity

New task IDs retain the exact 1–64 byte ASCII grammar `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. They additionally reject a trailing dot and any case-insensitive Windows device-name stem before the first dot (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, and `LPT1`–`LPT9`). Because the grammar is ASCII-only, the task-namespace identity is the validated string's ASCII lowercase form; Unicode normalization is deliberately not part of task-ID identity and every non-ASCII task ID is rejected. Existing schema-v1 IDs satisfying this portable contract continue unchanged.

Path authorization and workspace ownership will use a filesystem identity helper:

- existing objects prefer resolved paths plus `samefile`/stable file identity;
- a not-yet-created destination binds its nearest existing ancestor and normalized remaining components;
- native and alternate separators, drives, UNC roots, symlink/junction aliases, Unicode normalization, and verified case behavior are handled before comparison;
- case behavior for an uncreated child is established by a cleaned-up standard-library probe in the relevant existing parent, and inability to probe a safety-sensitive location fails closed.

Selectors will recognize either slash style and drive/UNC syntax before any basename fallback. Git refs remain logically case-preserving, but branch creation will conservatively reject a host-filesystem alias of an existing or protected ref.

**Alternative considered:** apply `Path.resolve()` plus raw string equality everywhere. Rejected because it cannot reliably identify uncreated destinations, alternate Windows spellings, junctions, or case-insensitive aliases.

### 4. Use byte-oriented subprocess capture and explicit UTF-8 protocols

Controller and hook protocol output will be serialized once and written as UTF-8 bytes followed by LF, bypassing the active console code page. Hook input will be read as bytes and decoded explicitly, accepting ordinary LF or CRLF framing. Controller-owned text files remain UTF-8/LF.

Subprocesses continue to receive argument lists and `shell=False`, but capture will be byte-oriented. Machine-readable Git output is parsed in its byte or NUL-delimited form whenever possible. Human diagnostics use deterministic decoding with escaped or replacement diagnostics while raw bytes remain available for hashing and evidence. Spawn failures and child exit failures become distinct structured errors.

For a subprocess participating in a protected mutation, interruption first requests platform-appropriate termination, escalates when necessary, and waits/reaps the child or owned process group before releasing task or workspace locks. If quiescence cannot be proven, the controller atomically records an unready quarantine/blocker while it still owns the lock; every later mutation refuses to proceed until recovery proves that no child remains and validates the partial filesystem/Git postconditions.

Atomic state replacement continues to use a same-directory temporary file, flush/fsync where supported, `os.replace`, and best-effort temporary cleanup. POSIX state directories remain mode `0700` and controller-owned state, event, lock, and artifact files remain `0600`; creation and replacement must not broaden them. On Windows, a standard-library `ctypes` check reads the owner and inherited DACL of the data root and replacement file, rejects a null/unreadable descriptor or broad write grants, and blocks mutation when the private-root policy cannot be verified. The controller does not describe POSIX mode calls as Windows ACL enforcement.

**Alternative considered:** set `text=True, encoding="utf-8"` globally. Rejected because Git path and diagnostic bytes are not guaranteed to be valid UTF-8 and complete evidence must not discard undecodable values.

### 5. Bind effective Git and filesystem capabilities into evidence

Evidence commands will stop forcing `core.fileMode=true`, `core.symlinks=true`, and `core.ignoreCase=false`. They will retain all existing environment sanitization and anti-transformation settings, query effective repository configuration, and verify material claims against the hosting filesystem. The resulting capability profile is hashed into repository fingerprints and review/test evidence.

Tracked evidence remains independent of text-oriented Git presentation:

- enumerate cached entries in deterministic NUL-delimited form;
- bind raw/lossless path identity, stage, index mode, object ID, worktree type, size, and SHA-256 of on-disk regular-file or symlink-target bytes;
- retain hidden-index, filter, redirection, replacement-object, submodule, and hostile-configuration checks;
- treat CRLF and other checkout bytes as evidence rather than normalizing them;
- explicitly record substitute representations such as a symlink placeholder, and block when case collisions or another limitation make the snapshot ambiguous.

Capability differences may change the evidence profile and representation, but never remove the tracked-byte manifest or turn an incomplete observation into a complete snapshot. Capability-aware fingerprints and snapshots carry an explicit evidence-contract version. Legacy schema-v1 task state remains readable, but evidence recorded without the current capability profile is invalid for a downstream evidence gate and must be regenerated before the task advances.

**Alternative considered:** choose one forced Git configuration for every platform. Rejected because Git for Windows and common macOS filesystems cannot truthfully provide those semantics and may report a clean native checkout as dirty.

### 6. Use paired hook launchers and conservative shell-aware inspection

Each packaged handler will have both `command` and `commandWindows`. POSIX launch uses the documented Python 3 command with a quoted `PLUGIN_ROOT`; the Windows override uses a packaged command shim that locates a supported `py -3` or `python` interpreter, preserves stdin/stdout and exit status, and invokes the same Python handler through `%PLUGIN_ROOT%`. Global-hook documentation continues to require an explicit absolute interpreter path.

The hook constructs resumable controller prefixes from `sys.executable`, the controller below `PLUGIN_ROOT`, and explicit `PLUGIN_DATA`. Skills must preserve that injected prefix rather than rebuilding it with `python3`.

Command inspection will:

- normalize `/` and `\`, strip executable suffixes for identity, and recognize absolute `git`/`git.exe` paths;
- identify direct commands and supported POSIX shell, `cmd.exe /c`, Windows PowerShell, and `pwsh -Command` wrappers;
- use a grammar appropriate to the recognized wrapper for quotes, escapes, and command separators;
- deny a recognized but ambiguous wrapper payload with a diagnostic;
- preserve the official canonical Codex `Bash` matcher instead of inventing platform-specific tool names.

Malformed hook protocol input or hook-internal exceptions still fail open with no malformed output or mutation. Ambiguity in a successfully recognized command wrapper is a guardrail decision, not an internal hook failure.

**Alternative considered:** run every command through `shlex(posix=True)`. Rejected because it misinterprets Windows paths, `cmd` quoting, and PowerShell quoting and can miss protected Git mutations.

### 7. Make package completeness and guidance executable release checks

The plugin manifest will continue to omit a `hooks` field because the supported plugin validator rejects that field; Codex's official default discovery of `hooks/hooks.json` remains the contract. Documentation and package trees will stop referring to files that are not shipped unless those files are intentionally added. A standard-library package validator/test will resolve manifest, default hook, skill, template, and documentation references using portable path rules and reject missing or case-colliding assets.

Workflow references will define `<ctl>` as the exact injected interpreter/controller/data-dir prefix. Platform-neutral command examples will be one-line argument sequences; multiline Bash, PowerShell, or Command Prompt examples will be labelled and paired where needed. `README.md`, `README.zh-CN.md`, and `INSTALL.md` will state the same prerequisites, launcher behavior, limitations, update/reinstall flow, validation commands, and recovery contract.

**Alternative considered:** fix only runtime code and leave packaging examples as user configuration. Rejected because bundled hooks and skills are the normal entry path and a runtime fix that users cannot start is not cross-platform support.

### 8. Prove parity with portable fixtures and a native CI matrix

Tests will replace assumptions about `true`, `cat`, `/bin/sh`, shebang execution, and broad POSIX skips with `sys.executable`, temporary helper scripts, and capability-scoped assertions. Git fixtures will isolate system/global configuration except in explicit adversarial tests.

Required CI will run real Git on native Windows, macOS, and Linux. Python 3.9 and the highest documented stable minor will run on all three; intermediate supported minors will run on at least Linux. Every required job runs the complete unittest suite, an automated runtime-import/standard-library audit, package checks, OpenSpec strict validation, and available skill/manifest validation. Native tests launch the exact packaged hook command for that platform and cover lock contention, child quiescence, permissions, default directories, UTF-8/code-page behavior, path identity, Git capabilities, and managed worktree flows.

CI command execution is necessary but not sufficient evidence for Codex integration. Before Windows support is claimed, an actual Windows Codex host must install the cache-busted plugin from a confirmed local marketplace, start a new task, prove default `hooks/hooks.json` discovery and `commandWindows` selection, observe real `PLUGIN_ROOT`/`PLUGIN_DATA`, and round-trip a plugin location containing spaces, Unicode, and command-shell metacharacters.

The highest supported Python minor is a release declaration tied to the matrix, not an open-ended `3.9+` promise. A version is documented only after its CI job exists.

**Alternative considered:** mock `os.name` on one host. Rejected because Windows file locking, command launch, path aliases, Git defaults, and filesystem behavior require native evidence.

### 9. Separate canonical cross-host identity from host-local snapshot evidence

The repository will add one standard-library candidate-identity helper shared
by `scripts/run_bundled_validators.py`, the Windows handoff builder, and the
native runner. It will produce two deliberately different identities:

- a versioned canonical validation-candidate digest for cross-host binding; and
- a host-local full-snapshot digest for detecting all source-tree, file-mode,
  and planning-artifact drift during local review.

The canonical inventory will be an explicit allowlist covering
`.codex-plugin/`, `.github/`, `hooks/`, `scripts/`, `skills/`, `tests/`,
package-declared `assets/` or `templates/`, `.gitattributes`, `.gitignore`,
`README.md`, `README.zh-CN.md`, `INSTALL.md`, and `LICENSE`. Always-excluded
host/development state is limited to a `.git` directory or worktree marker,
`.codex/`, `.idea/`, every `__pycache__/`, `*.py[cod]`, `.pytest_cache/`,
`.coverage`, `htmlcov/`, `.DS_Store`, and `work/`. `openspec/` is excluded only
from the canonical cross-host identity and remains mandatory in the host-local
digest and final review. Handoff/report outputs must be outside the candidate
root, so no broad generated-output glob is accepted. Any other path outside
the allowlist and exact exclusions fails closed instead of being silently
ignored.

Canonical identity contract v1 uses the following normative byte grammar:

- `DOMAIN` is the exact 22-byte sequence consisting of the 21 ASCII bytes
  `dev-flow-canonical-v1` followed by one NUL byte (`00`);
- `U64BE(n)` is one unsigned 64-bit integer in network byte order;
- `FILE_KIND` is the single byte `46` (ASCII `F`);
- directories are omitted; and
- for `N` regular-file entries sorted lexicographically by exact path bytes,
  the SHA-256 preimage is
  `DOMAIN || U64BE(N) || Σ(U64BE(path_len) || path_utf8 || FILE_KIND ||
  U64BE(payload_len) || payload)`.

The exact UTF-8 POSIX-relative path spelling is never case-folded or
Unicode-normalized before hashing. Before hashing, the helper rejects absolute,
drive, or UNC names, backslashes, empty/`.`/`..` components, duplicate paths,
and NFC-plus-casefold collisions. Timestamps, ownership, and host `st_mode`
executable bits do not enter the canonical digest. The host-local digest
retains current mode-sensitive behavior so a POSIX executable-bit change
remains reviewable rather than being silently discarded.

The normative golden vector has two entries in this order:

1. path `README.md` (hex `524541444d452e6d64`), payload `hello\n`
   (hex `68656c6c6f0a`);
2. path `scripts/测试.py`
   (hex `736372697074732fe6b58be8af952e7079`), payload
   `print("ok")\n` (hex `7072696e7428226f6b22290a`).

Its complete preimage hex is
`6465762d666c6f772d63616e6f6e6963616c2d76310000000000000000020000000000000009524541444d452e6d6446000000000000000668656c6c6f0a0000000000000011736372697074732fe6b58be8af952e707946000000000000000c7072696e7428226f6b22290a`
and its required SHA-256 is
`a5f265def6c95a23cf668937f83a6d06320d2e784f064627a6847aed11974674`.
Every implementation and native CI job must assert this vector before hashing
the real candidate.

Canonical handoff v1 rejects every symlink, Windows reparse point, and other
special entry. The current source candidate contains none. Native symlink and
reparse behavior remains testable inside runner-created disposable Git
fixtures; the handoff never guesses how to materialize a privileged link.

A repository `.gitattributes` policy will keep shipped text inputs on their
declared bytes across ordinary checkouts. The supported handoff will be
stronger: a portable mode of the validation tool will atomically create a
deterministic, byte-preserving ZIP and a separate JSON handoff manifest in an
explicit existing directory outside the candidate root. Both paths must be new
and use exclusive creation. ZIP members are sorted, `ZIP_STORED`, use fixed
timestamp/creator/attributes, and contain no extra fields or comment. The
external manifest contains the canonical digest, archive SHA-256, inventory
contract version, exact member list, per-member digest, and path count without
creating an archive-hash self-reference.

The Windows runner first verifies the manifest, archive digest, exact member
set, and every member path against traversal, drive/UNC, backslash, duplicate,
and NFC-plus-casefold collision rules. It never calls `ZipFile.extractall`; it
writes validated regular files as binary into one new empty extraction
directory, rehashes the extracted canonical inventory, and fails before native
fixture mutation on any missing, extra, transformed, or wrong-kind entry.
Tests will prove a golden candidate has the same canonical digest when host
mode metadata differs, while the host-local digest may legitimately differ.

The returned Windows report and tasks 6.1–6.5 bind the canonical digest. The
host-local digest is additional review evidence and is never compared for
equality across operating systems. Updating excluded OpenSpec completion
checkboxes or external review evidence after native validation does not change
the canonical subject; changing any included file invalidates the cachebuster,
local validations, handoff, and returned Windows report and requires the
sequence to restart. The authorized release CI invocation receives the
reviewed canonical digest as a required immutable workflow input; every matrix
job fails on a missing or mismatched value rather than merely printing its
locally computed digest. The workflow-dispatch input, lowercase-hex format
check, job propagation, golden-vector assertion, and per-job comparison are
implemented and tested before the cachebuster/freeze. The later release step
only invokes that frozen workflow and records evidence; it does not edit
`.github/` or any other canonical entry.

**Alternative considered:** reuse the existing worktree digest on Windows.
Rejected because it hashes host executable bits and checkout bytes, so NTFS
mode semantics or `core.autocrlf` can make an identical logical candidate
impossible to match.

### 10. Ship a project-local, evidence-producing Windows self-test

The repository will include the shared candidate-identity helper,
`scripts/windows_native_validation.py`, and a
`scripts/windows_native_validation.cmd` launcher. The Python tool will use only
the standard library and the repository's own controller/hook code. Its
portable preparation mode will create the deterministic ZIP and handoff
manifest from Decision 9. Its native execution mode will require:

- the handoff manifest and expected canonical candidate SHA-256 produced only
  after the runner, documentation, line-ending policy, package inventory,
  cachebuster, and local final validations are stable;
- an explicit existing writable local root under which a long-path fixture may
  be created;
- an explicit existing, accessible UNC alias for that same backing directory,
  supplied by the Windows tester;
- a non-UTF-8 code-page identifier, with a documented safe default that the
  host confirms is available; and
- an explicit new JSON report destination whose parent already exists outside
  the extracted candidate and both supplied test roots.

Before mutation, the runner will verify the handoff/archive identity, recompute
the extracted canonical candidate digest,
verify native Windows and tool prerequisites, reject drive/share roots and
other broad targets, prove that the local and UNC inputs identify the same
existing directory using stable Windows filesystem identity, and refuse to
overwrite an existing report. It will then create exactly one unpredictable,
sentinel-owned child beneath that backing directory and access it through both
aliases. The sentinel binds the run nonce, candidate digest, supplied-root
identities, and child identity. Temporary repositories and the isolated
controller data directory remain inside that child. Cleanup refuses the
supplied root, any different identity, and any missing or mismatched sentinel;
it records an `incomplete` result rather than guessing. The runner will never
create or remove a network share, modify the supplied roots themselves, reuse
the plugin's active data directory, install/reinstall the plugin, publish/push
code, persistently change the console code page, or change machine/global Git
configuration.

The code-page check will scope `chcp` to a child `cmd.exe` process and prove
that Unicode controller/hook input and output remain exact UTF-8 bytes with
deterministic diagnostics. The path check will prove filesystem identity,
repository selection, workspace ownership, real `git worktree`
materialization, postconditions, and tracked-byte fingerprinting through both
the supplied UNC root and a path longer than the ordinary Windows `MAX_PATH`
boundary when the host policy supports it.

Every invocation will atomically create a stable JSON document containing the
schema version, exact expected and observed canonical candidate digests,
handoff/archive identity, host/Python/Git versions, redacted root classes and
identity digests, observed code page, ordered per-check
identifiers/status/diagnostic codes, cleanup status, and overall `passed`,
`failed`, or `incomplete` result. It will not copy raw root paths, environment
variables, credentials, remote URLs, or arbitrary file contents into the
report. A non-Windows host may prepare the byte-preserving handoff and validate
imports, CLI parsing, report schema, digest binding, redaction, no-clobber
output, and fail-closed cleanup logic, but it cannot produce a native PASS.
Tasks 5.3 and 5.4 remain incomplete until a matching report from a real Windows
host is returned and reviewed.

**Alternative considered:** automatically create a loopback SMB share or ask
the tester to run the controller against their active plugin data. Rejected
because share management may require elevation and changes external machine
state, while reusing live data would mix verification fixtures with valuable
workflow evidence.

## Risks / Trade-offs

- **[Risk] Conservative identity checks reject an unusual but safe path.** → Prefer verified `samefile`/filesystem probes, return the compared identities in a structured blocker, and never guess through ambiguity.
- **[Risk] Capability probes have side effects or leave temporary names.** → Probe only in an approved existing parent, use unpredictable names, clean in `finally`, and fail closed if cleanup or interpretation is uncertain.
- **[Risk] Windows command parsing can never cover arbitrary shell programs or dynamic scripts.** → Support and test the documented wrappers, deny ambiguous recognized payloads, describe hooks as guardrails, and keep controller gates authoritative.
- **[Risk] A Windows Python launcher is absent from `PATH`.** → The packaged shim tries documented launchers and emits a non-mutating diagnostic; installation docs require a verified launcher or an absolute global-hook interpreter.
- **[Risk] Capability-aware Git behavior accidentally weakens snapshots.** → Keep the explicit tracked-byte manifest and hostile-configuration checks mandatory, hash the capability profile, and add regression tests where bytes change under every profile.
- **[Risk] Windows sharing violations make atomic replacement or lock release transiently fail.** → Return a structured error, preserve the last committed file and lock evidence, and require a fresh state read before retry.
- **[Risk] Windows ACLs cannot be represented by POSIX mode bits.** → Verify the actual inherited DACL with standard-library Win32 bindings, reject null/unreadable or broadly writable descriptors, and test replacement files against the same policy.
- **[Risk] A child Git process survives interruption.** → Terminate and reap before unlocking; otherwise commit a durable quarantine and block every later mutation until explicit recovery proves quiescence and validates partial postconditions.
- **[Risk] A large native matrix increases CI time.** → Keep correctness jobs required, use an explicit include matrix to avoid unnecessary cross-products, and parallelize by native runner rather than dropping coverage.
- **[Risk] A tester supplies a valuable, overly broad, or unrelated pair of Windows roots.** → Require explicit existing roots that resolve to one stable filesystem identity, reject drive/share roots, create only one unpredictable sentinel-owned child, and delete only that verified child; never manage the share itself.
- **[Risk] A returned report belongs to a different source snapshot.** → Require the expected candidate SHA-256, recompute the local candidate digest before native work, include both identities in the report, and reject a mismatch before claiming evidence.
- **[Risk] A macOS candidate digest cannot be reproduced on Windows because mode bits or checkout filters differ.** → Use the versioned canonical inventory/digest for cross-host binding, retain mode-sensitive host evidence separately, force declared text bytes with `.gitattributes`, and deliver the exact candidate through the deterministic ZIP/handoff pair.
- **[Risk] OpenSpec task-progress updates after native validation change the full source snapshot.** → Exclude planning/progress artifacts from the canonical Windows subject, keep them in host-local full review, and invalidate native evidence on any change to an included plugin, test, CI, validator, manifest, or documentation input.
- **[Risk] Stricter task-ID rules reject a previously accepted new identifier.** → Limit the break to new task creation, preserve existing portable schema-v1 tasks, and document the portable grammar and error.

## Migration Plan

1. Add portable primitives and focused tests without changing persisted schema; keep new evidence fields additive and version the evidence contract.
2. Land fail-closed locking, task identity, protocol I/O, path identity, and subprocess behavior before expanding platform claims.
3. Add paired hook launchers and shell-aware guardrails, then execute the packaged commands in native tests.
4. Replace forced Git capability settings with the bound capability profile while retaining and regression-testing the tracked-byte manifest.
5. Update skills, manifest, package validation, and bilingual documentation to match the implemented contract.
6. Add the shared canonical identity and normative golden vector, dual-digest validator output, line-ending policy, byte-preserving handoff builder, Windows self-test runner/launcher, portable tests, package registration, bilingual instructions, and the release-workflow canonical-input/comparison gate.
7. Once every canonical-inventory implementation and documentation input is stable, apply the cachebuster once and compute the final canonical candidate plus host-local snapshot identities.
8. Against that canonical digest, run the full local suite, automated standard-library audit, every bundled skill validator, plugin manifest/package validation, and a pre-handoff full-source review; then create and independently verify the deterministic ZIP/handoff pair without changing the source candidate.
9. Have the Windows tester run that exact handoff, review the matching native report, and update the legacy-code-page plus UNC/long-path task progress only when every required check and cleanup result passes. Then run strict OpenSpec validation and a final host-local full-snapshot review that proves the canonical digest stayed unchanged and every post-report source difference is limited to allowed OpenSpec progress state. Any included-file change invalidates steps 7–9 and requires a new cachebuster, local validation, handoff, and Windows run.
10. After separate publication authorization, pass the approved canonical digest into the native CI workflow and require every matrix job to match it. After separate Windows-host installation authorization, reinstall that same candidate and complete the real Windows Codex-host smoke before starting ordinary new-task validation on other supported hosts.

Rollback may install only a build that declares support for the same evidence-contract version. Installing the pre-capability-profile plugin may preserve task data and managed worktrees for forward recovery, but it MUST NOT point at that data directory or advance any task that ran under the new contract; schema readability is not evidence-semantic compatibility. Recovery reinstalls a compatible build, invalidates/regenerates legacy evidence where required, and resumes from the last compatible committed revision. A task/data directory is not moved to a different operating system as part of rollout or rollback.

## Open Questions

There are no blocking design questions. Release validation must record the concrete highest supported Python minor and a real Windows Codex-host smoke result before documentation claims that version/platform combination as supported.
