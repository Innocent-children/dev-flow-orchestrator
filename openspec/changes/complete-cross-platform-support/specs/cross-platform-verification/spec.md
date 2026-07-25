## ADDED Requirements

### Requirement: Cross-platform tests use portable and isolated fixtures
Tests that assert platform-independent behavior SHALL use Python standard-library helpers, `sys.executable`, `tempfile`, and argument-vector subprocess calls instead of assuming `true`, `cat`, `/bin/sh`, executable permission bits, or another POSIX-only facility exists. Git fixtures MUST isolate repository, global, and system configuration from the host. Capability-specific assertions MUST be separated from portable assertions and gated narrowly on the capability they exercise rather than skipping an entire behavior suite by operating-system name.

#### Scenario: Portable suite runs on Windows
- **WHEN** the full unit suite runs on a native Windows runner
- **THEN** platform-independent tests execute without requiring a POSIX shell, POSIX utility, or executable-mode emulation

#### Scenario: Host Git configuration is adversarial
- **WHEN** the CI host has user or system Git settings that differ from repository defaults
- **THEN** ordinary fixtures remain deterministic because external configuration is isolated and only a dedicated adversarial test injects non-default settings

#### Scenario: Filesystem-specific assertion is unsupported
- **WHEN** a runner lacks a capability such as POSIX mode bits or symlink creation
- **THEN** only the capability-specific assertion is skipped with an explicit reason while byte, path, state, and guardrail assertions continue to run

### Requirement: Native operating-system and supported-Python CI matrix
Required CI SHALL run on native Windows, macOS, and Linux hosted runners with real Git. The project SHALL declare Python 3.9 as its minimum version and SHALL explicitly identify the highest supported Python minor. The matrix MUST run both the minimum and highest declared versions on every operating system, and every intervening declared minor MUST run on at least one native runner. A new Python minor MUST NOT be advertised as supported until it is included in the declared matrix.

#### Scenario: Minimum and highest Python versions are exercised everywhere
- **WHEN** the CI workflow is expanded for a release candidate
- **THEN** Windows, macOS, and Linux each contain native jobs for Python 3.9 and the highest version documented as supported

#### Scenario: Intermediate supported Python version is retained
- **WHEN** the declared support interval contains a Python minor between the minimum and highest versions
- **THEN** at least one native CI job runs the full required validation set for that minor

#### Scenario: Required native job fails
- **WHEN** any operating-system and required-Python matrix job fails or is cancelled
- **THEN** the cross-platform verification gate fails and the release is not considered supported

### Requirement: Runtime safety contracts have native regression coverage
The automated suite SHALL verify fail-closed lock acquisition and release, concurrent writer exclusion, child-process quiescence and quarantine, controller-managed storage permissions, default data-directory selection, actor discovery, UTF-8 CLI and hook JSON, subprocess decoding, CRLF handling, portable task identifiers, and canonical filesystem identity. Native tests MUST cover POSIX directory/file modes, secure and insecure Windows DACLs, Windows drive and UNC forms, alternate separators, case-equivalent paths, reserved device names, trailing-dot names, exact task-ID length/ASCII boundaries, long paths within runner policy, and space/Unicode path components.

#### Scenario: Writers contend for one task revision
- **WHEN** two native processes attempt mutations against the same task and expected revision
- **THEN** exactly one process commits under the exclusive lock and the other receives a deterministic stale-revision or lock diagnostic without an unlocked mutation

#### Scenario: Native lock cannot be acquired
- **WHEN** the platform locking primitive reports an unsupported operation or unrecoverable acquisition error
- **THEN** the mutation fails closed, state and events remain unchanged, and the error identifies the lock path and platform cause

#### Scenario: Lock owner terminates
- **WHEN** a process exits or is terminated after acquiring a test lock
- **THEN** the operating system releases the lock and a subsequent process can acquire it without corrupting persisted state

#### Scenario: Mutating child survives the first termination request
- **WHEN** a native helper child participating in a protected mutation ignores the first termination request and attempts a delayed marker write
- **THEN** the controller escalates and reaps it before unlocking, or records a durable quarantine that blocks every later mutation until recovery proves quiescence and validates the marker/postconditions

#### Scenario: Controller-managed permissions remain private
- **WHEN** state directories and replacement files are created on POSIX and Windows fixtures with secure and deliberately insecure permission policies
- **THEN** POSIX modes remain `0700`/`0600`, secure Windows inherited DACLs pass, insecure or unverifiable DACLs fail before commit, and atomic replacement never broadens access

#### Scenario: Platform default state location is selected
- **WHEN** no explicit data directory is supplied on Windows, macOS, or Linux
- **THEN** the controller selects the documented native state directory, treats empty environment variables as absent, and records the native account name including `USERNAME` on Windows

#### Scenario: Non-ASCII protocol data crosses a legacy code page
- **WHEN** repository paths, actor names, or diagnostics contain Unicode while the Windows console uses a non-UTF-8 code page
- **THEN** controller and hook processes exchange deterministic UTF-8 JSON and either decode Git output predictably or return a structured decoding error without failing after a committed mutation

#### Scenario: Equivalent Windows paths identify one resource
- **WHEN** task, repository, or workspace selection receives equivalent drive-letter case, slash styles, UNC spellings, or filesystem case variants
- **THEN** identity and ownership checks resolve them consistently and reject collisions before mutation

#### Scenario: Non-portable task identifier is requested
- **WHEN** a new task identifier is a Windows reserved name, ends in a dot or space, or is path-equivalent to an existing identifier
- **THEN** creation fails before any task directory, lock, or workspace path is written

### Requirement: Cross-host validation candidate identity is canonical and layered
The project SHALL provide one versioned standard-library candidate-identity implementation shared by the bundled validator, handoff builder, and Windows native runner. Its explicit canonical cross-host allowlist MUST include every plugin/runtime, hook, script, skill, manifest, package validator, test, CI, root-documentation, license, and line-ending-policy input that can affect native validation, reject any unexpected non-excluded path, and exclude OpenSpec only from this canonical identity while retaining it in host-local review. Canonical contract v1 MUST compute SHA-256 over the exact preimage `b"dev-flow-canonical-v1\x00" || U64BE(entry_count) || entries`, where each regular-file entry is ordered by exact UTF-8 POSIX-relative path bytes and encoded as `U64BE(path_length) || path_bytes || b"\x46" || U64BE(payload_length) || raw_payload`; omit directories and host metadata; reject absolute/drive/UNC/backslash/traversal names, duplicates, NFC-plus-casefold collisions, symlinks, reparse points, and special entries; and never use host timestamps, ownership, or executable mode. The normative two-entry vector `README.md`=`hello\n` and `scripts/测试.py`=`print("ok")\n` MUST produce SHA-256 `a5f265def6c95a23cf668937f83a6d06320d2e784f064627a6847aed11974674` in every implementation and native job. A separate mode-sensitive host-local full-snapshot digest MUST retain review coverage for OpenSpec planning state and POSIX mode drift. The supported Windows handoff MUST use a deterministic byte-preserving archive plus an external no-clobber manifest, all generated outputs MUST be outside the candidate root, extraction MUST validate exact members and paths without `extractall`, and any canonical-inventory change MUST invalidate prior local and native evidence. The release workflow's required reviewed-digest input, lowercase-hex validation, propagation, golden-vector assertion, and per-job comparison MUST be implemented before candidate freeze; the authorized release invocation MUST NOT modify a canonical entry.

#### Scenario: Host metadata differs for one byte-identical candidate
- **WHEN** macOS and Windows inspect the byte-preserved handoff with identical canonical paths, kinds, and bytes but different host executable-mode metadata
- **THEN** both produce the same canonical candidate digest, may produce different host-local snapshot digests, and never compare the host-local values for cross-host equality

#### Scenario: Checkout or transfer transforms an included entry
- **WHEN** a Windows candidate is missing an included path, contains an extra included path, has a different entry kind, or has bytes transformed by line-ending checkout behavior
- **THEN** canonical verification fails before native fixture mutation and directs the tester to use the deterministic handoff rather than accepting a logically similar tree

#### Scenario: Progress-only planning state changes after native validation
- **WHEN** a reviewed native report is followed only by OpenSpec checkbox or external review-evidence updates
- **THEN** the canonical candidate remains unchanged while the host-local full snapshot records the planning-state difference

#### Scenario: An included candidate input changes after evidence
- **WHEN** implementation, tests, CI, validators, manifest/cachebuster, line-ending policy, or user documentation changes after local or native validation
- **THEN** the canonical digest changes and the cachebuster, local validations, handoff, and Windows report are all regenerated before any release claim

#### Scenario: Release CI receives the reviewed canonical identity
- **WHEN** the authorized native release matrix starts without the reviewed canonical digest input or any Windows, macOS, or Linux job computes a different value
- **THEN** the required workflow fails and cannot serve as release evidence

### Requirement: Project-local Windows native validation is safe and evidence-producing
The project SHALL ship a standard-library Python runner and Windows command launcher that a user can execute from the byte-preserved handoff to cover native-only legacy-code-page, UNC, and long-path checks. Native execution MUST bind to the expected canonical candidate and handoff/archive identities, require explicit existing local and UNC test roots that it proves are aliases of the same writable backing directory before mutation, use only one unpredictable sentinel-owned child beneath that directory, and atomically create a stable redacted JSON evidence report with host/tool versions, input identity digests, observed code page, per-check results, deterministic diagnostics, cleanup status, and overall result. The runner MUST NOT create or remove a network share, overwrite a report, reuse live plugin state, install or publish the plugin, persistently alter the console code page, change machine/global Git configuration, expose credentials, raw test-root paths, or arbitrary environment values, or report PASS on a non-Windows host or incomplete required check.

#### Scenario: Windows tester produces matching native evidence
- **WHEN** a user runs the project-local launcher on native Windows from the verified byte-preserved handoff with its exact expected canonical digest, a writable local long-path root, and an existing accessible UNC alias resolving to the same backing directory
- **THEN** the runner exercises scoped legacy-code-page controller/hook round-trips plus real Git/worktree identity and tracked-byte flows, safely cleans its sentinel-owned fixtures, and writes a PASS report bound to that candidate only when every required check succeeds

#### Scenario: Required Windows capability or input is unavailable
- **WHEN** the runner executes on a non-Windows host, the handoff/archive or candidate digest differs, an archive member is unsafe or colliding, the requested code page is unavailable, a supplied root is missing or unsafe, the roots do not resolve to the same stable identity, the UNC root is inaccessible, the report is inside a protected input/root or already exists, the long-path policy cannot support the required fixture, or cleanup cannot be proven
- **THEN** it exits non-zero with `failed` or `incomplete`, identifies the exact unmet prerequisite without secrets, performs no out-of-scope mutation, and cannot satisfy native verification

#### Scenario: Cleanup target is not the runner-owned child
- **WHEN** cleanup encounters a missing/mismatched sentinel, an alias outside the supplied root, or the supplied root itself
- **THEN** the runner refuses deletion, records the cleanup blocker in the report, and returns non-zero

#### Scenario: Portable hosts validate the runner without claiming Windows evidence
- **WHEN** ordinary unit tests run on macOS or Linux
- **THEN** they can build and verify the deterministic handoff and validate runner imports, CLI parsing, canonical/host digest separation, report schema, candidate binding, redaction, no-clobber output, and fail-closed cleanup decisions while the native execution path remains explicitly incomplete

### Requirement: Bundled hook behavior is tested through real launch commands
Verification SHALL execute the actual `command` and `commandWindows` entries from the packaged `hooks/hooks.json`, not only call handler functions directly. It MUST supply representative Codex JSON events and `PLUGIN_ROOT`/`PLUGIN_DATA` values through paths containing spaces, Unicode, and shell metacharacters. Parser coverage MUST include direct `git`, `git.exe`, absolute Windows Git paths, POSIX shell wrappers, `cmd.exe /c`, Windows PowerShell, and `pwsh -Command`.

#### Scenario: Packaged hook command round-trips JSON
- **WHEN** a native CI job launches each bundled handler using the command selected for that operating system
- **THEN** the handler reads one representative JSON event, writes valid JSON, uses the injected plugin directories, and exits according to the hook contract

#### Scenario: Equivalent protected Git commands are parameterized
- **WHEN** the parser test table supplies equivalent protected Git mutations through every supported executable spelling and shell wrapper
- **THEN** every case returns the same denial category and an assertion identifies any unrecognized wrapper

#### Scenario: Benign commands remain allowed
- **WHEN** the same wrapper and quoting table carries commands that do not mutate protected Git state
- **THEN** the hook preserves its existing allow behavior and does not introduce a platform-specific false denial

### Requirement: Windows support includes a real Codex-host pickup smoke
A Windows release claim SHALL include evidence from an actual native Windows Codex host after the cache-busted plugin is installed from a confirmed local marketplace and a new Codex task is started. The smoke MUST prove official default discovery of `hooks/hooks.json`, selection of `commandWindows`, real `PLUGIN_ROOT` and `PLUGIN_DATA` injection, bootstrap/checkpoint pickup, and a protected-command guardrail through a plugin source or install path containing spaces, Unicode, `&`, and parentheses. CI command emulation alone MUST NOT satisfy this requirement.

#### Scenario: New Windows Codex task loads the packaged hook
- **WHEN** the approved release candidate is installed on a native Windows Codex host from the confirmed local marketplace and a new task starts
- **THEN** Codex discovers the default hook file, selects `commandWindows`, injects the real plugin directories, and the task receives a controller bootstrap using the installed Python interpreter and explicit plugin data directory

#### Scenario: Windows Codex host round-trips a special-character installation
- **WHEN** the Windows smoke uses a local marketplace/plugin path containing spaces, Unicode, `&`, and parentheses and submits both a benign command and a protected Git mutation
- **THEN** the hook protocol remains valid, the benign command keeps its normal decision, and the protected mutation receives the documented guardrail denial

#### Scenario: Real Windows pickup evidence is unavailable
- **WHEN** the release candidate has only unit/CI command-launch evidence and no successful native Windows Codex-host task
- **THEN** verification does not claim complete Windows plugin support and keeps the release gate incomplete

### Requirement: Git evidence and worktree flows are capability-aware and byte-accurate
Native verification SHALL exercise preflight, baseline, analysis, managed-worktree materialization, fingerprinting, test evidence, and review evidence with real Git on each supported operating system. Tests MUST vary `core.fileMode`, `core.symlinks`, `core.ignoreCase`, and line-ending behavior according to capabilities available on the runner. Capability-aware normalization MUST retain explicit byte-accurate tracked-content manifests and deterministic dirty-state detection; it MUST NOT turn an unsupported filesystem feature into either a false modification or omitted evidence.

#### Scenario: Normal Windows checkout is fingerprinted
- **WHEN** Git for Windows reports its native file-mode, symlink, case, and line-ending configuration for an unchanged checkout
- **THEN** preflight and fingerprinting classify the checkout as clean while recording sufficient capability and tracked-byte evidence to reproduce the decision

#### Scenario: Case-insensitive macOS checkout is fingerprinted
- **WHEN** a macOS worktree resides on a case-insensitive filesystem
- **THEN** path identity and Git evidence avoid case-only ownership collisions without suppressing a real tracked-content change

#### Scenario: Tracked bytes change under any capability set
- **WHEN** a tracked file's bytes change while mode, symlink, case, or autocrlf settings vary
- **THEN** the manifest and workflow evidence detect the change and the same deterministic gate blocks stale or mismatched evidence

#### Scenario: Worktree path contains Windows-specific syntax
- **WHEN** a managed worktree is planned and materialized beneath a supported drive, UNC, long, space-containing, or Unicode path
- **THEN** argv-based Git operations address the intended path and ownership claims prevent an equivalent path from being assigned twice

### Requirement: Every release validates skills, manifest, and package inventory
Required automation SHALL run the complete unit suite, an automated runtime import/dependency audit, the bundled skill validator against every shipped skill, the plugin manifest validator, the package inventory/reference and default-hook-discovery validator, and OpenSpec validation for the change artifacts. These checks MUST operate on the exact source snapshot being packaged. The runtime audit MUST parse every shipped controller/hook Python import and verify it is standard-library or package-internal, then start the runtime in an isolated environment without third-party packages. The manifest and inventory checks SHALL confirm that hook configuration, runtime scripts, skill references, templates, and English/Chinese documentation are present with portable path spelling.

#### Scenario: A bundled skill becomes invalid
- **WHEN** any shipped skill violates the skill schema or contains a broken required reference
- **THEN** the validator job names the skill, exits non-zero, and blocks packaging

#### Scenario: Manifest or package content drifts
- **WHEN** the manifest is invalid, a referenced file is missing, or the validation snapshot differs from the packaged snapshot
- **THEN** release validation identifies the offending path or digest and fails before publication

#### Scenario: Third-party runtime import is introduced
- **WHEN** a controller or hook runtime file imports a top-level module outside the Python standard library and packaged internal modules
- **THEN** the automated dependency audit names the file and import, exits non-zero on every required CI job, and blocks the release

#### Scenario: All release validators pass
- **WHEN** unit, standard-library dependency, skill, manifest, default-hook discovery, inventory, and OpenSpec validation succeed for the exact candidate snapshot
- **THEN** the CI result records each validator and the source revision used to produce the package

### Requirement: Platform parity and failures are diagnosable
Windows, macOS, and Linux SHALL preserve the same state-machine transitions, approvals, revision checks, protected-Git guardrails, evidence requirements, and standard-library-only runtime policy. Platform-specific capability handling MUST be explicit, covered by a native test, and unable to weaken a deterministic gate. Every native failure MUST identify the operating system, Python version, failing capability or command, and relevant structured controller or hook diagnostic without exposing secrets.

#### Scenario: One platform requires capability-specific behavior
- **WHEN** an operating system cannot represent a mode, symlink, case, signal, or lock behavior available on another platform
- **THEN** the implementation records or diagnoses that capability explicitly and retains equivalent approval, evidence, concurrency, and mutation-safety outcomes

#### Scenario: Cross-platform behavior regresses
- **WHEN** a platform-specific code path bypasses a gate, changes a transition, omits required evidence, or introduces a runtime dependency outside the Python standard library
- **THEN** a required native parity or dependency check fails and blocks the release

#### Scenario: Native CI reports a failure
- **WHEN** a runtime, hook, Git, validator, or packaging assertion fails in the matrix
- **THEN** the job output identifies the OS, Python version, invoked test or validator, and actionable failure reason so the problem can be reproduced on that platform
