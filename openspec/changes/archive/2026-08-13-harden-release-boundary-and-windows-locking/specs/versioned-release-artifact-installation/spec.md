## MODIFIED Requirements

### Requirement: Release production emits one closed version-addressed artifact
For each `MAJOR.MINOR.PATCH` release, production SHALL build one platform-neutral archive, one `release-index.json`, and version-matched macOS and Windows bootstraps from an exact clean `v<version>` tag.

The archive SHALL contain one top-level directory with the complete `plugin/**` tree, exactly one pure-Python project wheel, `runtime-requirements.txt`, the `uv.lock` used to produce it, versioned `lifecycle/**` helpers, and `release-manifest.json`. The plugin tree SHALL include `.codex-plugin/plugin.json`, `.mcp.json`, and `skills/dev-flow/**`.

The closed index SHALL bind repository, version, source commit and tree as builder assertions, archive name, size and SHA-256, raw manifest SHA-256, and schema. The closed manifest SHALL inventory every descendant except itself; file entries bind path, type, mode, size and SHA-256, while directory entries bind path, type and mode.

Member paths SHALL use `/` and a portable ASCII component grammar. Validation SHALL reject traversal, absolute or drive paths, backslashes, colons, control characters, case collisions, trailing dots or spaces, Windows device names, links, sparse or special entries, unsupported tar features, resource-limit violations, and missing, extra or undeclared members. Dependencies SHALL be hash-locked and wheel-only. A pinned builder and closed input allow-list SHALL produce identical payload digests and archive bytes in two clean builds.

Promotion SHALL validate all four local assets before mutation, prove the remote tag commit and tree equal the index source identity, create a Draft Release, upload the exact four assets, re-download every asset through the official authenticated asset API, rerun complete asset and component-digest validation, and publish only after exact equality. It SHALL atomically maintain a bounded closed machine-readable journal sufficient to resume only a proven matching draft. Any published, mismatched, ambiguous, or unprovable same-version release SHALL be refused and SHALL NOT be overwritten.

#### Scenario: Valid release set is produced
- **WHEN** version, topology, wheel, lock, requirements, manifest and source assertions agree
- **THEN** all four assets pass validation with one release identity

#### Scenario: Manifest avoids self-reference
- **WHEN** the manifest is generated
- **THEN** it excludes itself and the index pins its raw UTF-8 bytes

#### Scenario: Draft assets pass authenticated verification
- **WHEN** local assets, remote tag commit/tree, uploaded asset identities, authenticated re-download bytes and every component digest agree
- **THEN** promotion records the verified phase and may make the Draft Release public

#### Scenario: Draft verification fails or is interrupted
- **WHEN** an uploaded or re-downloaded asset differs, verification fails, or promotion is interrupted
- **THEN** the release remains draft, the bounded journal records the last proven phase, and a rerun resumes only after re-proving the exact draft identity

#### Scenario: Existing version would be replaced
- **WHEN** promotion finds a published, mismatched, ambiguous, or unprovable release for the same version
- **THEN** promotion refuses replacement rather than redefining that version

### Requirement: Bootstrap verifies release bytes before artifact code or product mutation
Each bootstrap SHALL hard-code the canonical repository, exact version, archive name, expected raw index SHA-256, and bootstrap schema. Production options SHALL NOT select another origin. A bootstrap reached through `latest` SHALL use only version-specific release URLs after execution begins.

Both bootstraps SHALL embed the same standard-library Phase A verifier. Under fixed hard caps it SHALL verify the index digest before parsing, parse strict closed JSON, verify repository and version, verify the archive before extraction, inspect every member, extract exclusively into a new empty installer-owned directory without following links or reparse ancestors, verify the raw manifest digest, compare the complete inventory, and statically validate package topology.

Phase A SHALL accept caller input only for `runtime-root`, `bin-dir`, `marketplace-file`, `codex-home`, `data-root`, and `lock-timeout`. It SHALL reject option abbreviations, repeated options regardless of spelling, positional input, and every repository, version, archive, index, artifact-root, release, source, or transaction identity option. It SHALL preserve exact argument boundaries for both `--option value` and `--option=value`, including native paths containing spaces, apostrophes, and Unicode.

Only after Phase A succeeds MAY Phase B execute artifact helpers, import artifact modules, run artifact subprocesses, install wheel-only locked dependencies, or build a candidate runtime. Phase B SHALL derive the artifact root from its own versioned lifecycle location rather than caller input. Before candidate construction, copying, dependency installation, or further helper execution, Phase B SHALL recompute the complete current artifact inventory and require exact type, mode, size, and digest equality with the index-bound manifest. Candidate construction SHALL repeat this live check at its pre-install boundary. No runtime, lifecycle, dispatcher, marketplace, plugin, MCP, Codex, active-record, or transaction authority SHALL change before these checks succeed. Temporary acquisition paths SHALL never become installed or rollback authority.

#### Scenario: Verified artifact enters Phase B
- **WHEN** index, archive, members, manifest, inventory, topology, closed caller options and the Phase B derived root agree
- **THEN** the verified artifact root may enter semantic validation and candidate construction

#### Scenario: Caller attempts identity replacement
- **WHEN** caller input names, abbreviates, or repeats an artifact, index, digest, repository, version, archive, source, release, or transaction identity option
- **THEN** Phase A rejects the request before Phase B execution or product mutation

#### Scenario: Native destination values preserve boundaries
- **WHEN** an allowed shell or PowerShell option uses separate or `=` syntax and contains spaces, apostrophes, or Unicode
- **THEN** Phase A forwards one exact canonical option/value pair without reinterpretation

#### Scenario: Artifact changes after Phase A
- **WHEN** a wheel, lifecycle helper, manifest entry, directory, or other artifact descendant is replaced, removed, added, or changed after extraction
- **THEN** Phase B rejects the live inventory before installation, helper execution, or product mutation

#### Scenario: Any pinned digest differs
- **WHEN** index, archive or manifest bytes fail the expected digest
- **THEN** installation stops before artifact code executes or product state changes

#### Scenario: Extraction boundary is unsafe
- **WHEN** a member, destination, ancestor, inventory or resource bound violates Phase A
- **THEN** installation fails with prior authority unchanged

### Requirement: Lifecycle mutation is serialized and has explicit terminal outcomes
Install, repair, upgrade, migration, recovery and uninstall SHALL acquire one installation-wide lock before reading active or transaction authority and SHALL hold it until a terminal outcome is durable. Each operation SHALL create or resume one bounded journal recording expected active generation and digest, target and previous authority, exact external observations, provisional effects, transaction-owned paths, phase and outcome. Active creation, replacement, restoration and removal SHALL use generation-and-digest compare-and-swap.

On both POSIX and native Windows, lock admission SHALL use one positive bounded timeout and cooperative cancellation contract. It SHALL check cancellation while waiting and immediately after OS acquisition, check the deadline immediately after OS acquisition, return `STATE_LOCK_TIMEOUT` on expiry, return `REQUEST_CANCELLED` on cancellation, and release any acquired OS lock before descriptor close on every exceptional path. The lock file format, state formats, and lock acquisition order SHALL remain unchanged.

Activation SHALL complete candidate-specific staged health, provision and read back marketplace and Codex plugin state, commit the active record by CAS, and then run real public CLI and MCP startup proof while still holding the lock. It SHALL record `committed` only after public proof succeeds. Failure SHALL restore and prove the immediate previous authority and record `rolled_back`, or preserve uncertainty, stop identity-specific mutation and record `partial`.

The immediate previous runtime SHALL remain until the activation transaction is terminal; automatic rollback SHALL require neither network nor checkout. This change SHALL NOT expose arbitrary historical rollback. Repair MAY reuse only a fully attested active runtime; drift SHALL build a verified same-version candidate. Repair SHALL reject a different digest envelope for an already installed version. Upgrade SHALL run the target version's bootstrap. A new lifecycle request SHALL first recover or classify any non-terminal journal and SHALL NOT retry indefinitely or broaden cleanup.

#### Scenario: Competing lifecycle operations start
- **WHEN** two upgrades, or upgrade and uninstall, target one installation
- **THEN** lock and generation CAS prevent provisional effects from interleaving

#### Scenario: Lock wait expires on Windows or POSIX
- **WHEN** the installation or state lock remains contended through the bounded deadline
- **THEN** admission returns `STATE_LOCK_TIMEOUT` without entering the critical section or writing state

#### Scenario: Lock wait is cancelled around acquisition
- **WHEN** cancellation is observed while waiting or immediately after the OS grants the lock
- **THEN** admission returns `REQUEST_CANCELLED`, releases any acquired raw lock, and does not enter the critical section

#### Scenario: Candidate fails before active commit
- **WHEN** acquisition, verification, construction, staged health or provisional read-back fails
- **THEN** previous authority is restored or unchanged and the transaction becomes `rolled_back`

#### Scenario: Public proof fails after active commit
- **WHEN** the real public CLI or MCP path fails after target generation commit
- **THEN** the installer CAS-restores and revalidates previous authority or records `partial`

#### Scenario: Prior transaction was interrupted
- **WHEN** a new lifecycle command finds a non-terminal journal
- **THEN** it first recovers or classifies that journal and refuses new mutation while authority is unresolved

### Requirement: Delivery evidence has a bounded completion gate
Shared verifier and state-machine behavior SHALL be tested primarily through unit and deterministic simulated integration tests. Native macOS and native Windows SHALL each run one final-artifact lifecycle on one supported Python version covering fresh install, healthy and drift repair, successful upgrade, one failed-activation rollback, one interrupted transaction, startup, predecessor migration, uninstall and task-data preservation.

Native Windows lock evidence SHALL include real multiprocess contention, timeout, cancellation, post-acquisition rejection, subsequent reacquisition, and exact release behavior using `msvcrt.locking`. Such tests MAY be present but skipped on other hosts; a skip, mocked Windows branch, POSIX result, WSL, Wine, or static PowerShell inspection SHALL NOT count as native Windows evidence.

The supported Python matrix SHALL run lightweight wheel-only installation and import or MCP smoke checks rather than repeat the full lifecycle matrix. Concurrency evidence SHALL cover only upgrade-versus-upgrade and upgrade-versus-uninstall. A release candidate SHALL use a real Codex host for plugin read-back, bundled Skill discovery, STDIO MCP startup and uninstall; ordinary pull requests MAY use deterministic fakes.

Release-promotion tests SHALL use only deterministic fake authenticated API and command adapters. They SHALL prove local validation, remote source identity, draft creation/resume, upload, authenticated re-download, component verification, journal recovery, publication ordering, and same-version refusal without mutating GitHub. Real GitHub, native Windows, and real Codex evidence SHALL be reported only when actually obtained in those environments.

Static or simulated PowerShell SHALL NOT count as native Windows evidence. Completion SHALL require re-downloaded final assets, both native gates, all Requirements and tasks, aligned English and Simplified Chinese documentation, and only `committed`, `rolled_back`, or `partial` lifecycle results.

Signing, offline fresh install, automatic updates, arbitrary historical rollback, broader legacy migration, general Unicode artifact members, or dispatcher-protocol migration SHALL require separate OpenSpec changes.

#### Scenario: Candidate satisfies the completion target
- **WHEN** final assets, native gates, Python smoke matrix, real Codex evidence, strict OpenSpec validation and repository checks pass
- **THEN** the change may be marked complete with actual digests, evidence and limitations recorded

#### Scenario: Native Windows evidence is unavailable
- **WHEN** validation uses only macOS, POSIX, mocked Windows behavior, or static or simulated PowerShell
- **THEN** the change remains incomplete for Windows and Windows is reported unverified

#### Scenario: Promotion tests use fakes
- **WHEN** the Draft promotion and recovery workflow is exercised in repository tests
- **THEN** all GitHub reads, downloads, uploads and publication mutations use deterministic fake adapters and no real GitHub state changes

#### Scenario: A non-goal is requested
- **WHEN** implementation would add a listed non-goal
- **THEN** that work is excluded and requires a separate OpenSpec proposal
