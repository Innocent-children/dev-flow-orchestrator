## ADDED Requirements

### Requirement: Release production emits one closed version-addressed artifact
For each `MAJOR.MINOR.PATCH` release, production SHALL build one platform-neutral archive, one `release-index.json`, and version-matched macOS and Windows bootstraps from an exact clean `v<version>` tag.

The archive SHALL contain one top-level directory with the complete `plugin/**` tree, exactly one pure-Python project wheel, `runtime-requirements.txt`, the `uv.lock` used to produce it, versioned `lifecycle/**` helpers, and `release-manifest.json`. The plugin tree SHALL include `.codex-plugin/plugin.json`, `.mcp.json`, and `skills/dev-flow/**`.

The closed index SHALL bind repository, version, source commit and tree as builder assertions, archive name, size and SHA-256, raw manifest SHA-256, and schema. The closed manifest SHALL inventory every descendant except itself; file entries bind path, type, mode, size and SHA-256, while directory entries bind path, type and mode.

Member paths SHALL use `/` and a portable ASCII component grammar. Validation SHALL reject traversal, absolute or drive paths, backslashes, colons, control characters, case collisions, trailing dots or spaces, Windows device names, links, sparse or special entries, unsupported tar features, resource-limit violations, and missing, extra or undeclared members. Dependencies SHALL be hash-locked and wheel-only. A pinned builder and closed input allow-list SHALL produce identical payload digests and archive bytes in two clean builds.

#### Scenario: Valid release set is produced
- **WHEN** version, topology, wheel, lock, requirements, manifest and source assertions agree
- **THEN** all four assets pass validation with one release identity

#### Scenario: Manifest avoids self-reference
- **WHEN** the manifest is generated
- **THEN** it excludes itself and the index pins its raw UTF-8 bytes

#### Scenario: Existing version would be replaced
- **WHEN** promotion finds assets for the same version
- **THEN** promotion refuses replacement rather than redefining that version

### Requirement: Bootstrap verifies release bytes before artifact code or product mutation
Each bootstrap SHALL hard-code the canonical repository, exact version, archive name, expected raw index SHA-256, and bootstrap schema. Production options SHALL NOT select another origin. A bootstrap reached through `latest` SHALL use only version-specific release URLs after execution begins.

Both bootstraps SHALL embed the same standard-library Phase A verifier. Under fixed hard caps it SHALL verify the index digest before parsing, parse strict closed JSON, verify repository and version, verify the archive before extraction, inspect every member, extract exclusively into a new empty installer-owned directory without following links or reparse ancestors, verify the raw manifest digest, compare the complete inventory, and statically validate package topology.

Only after Phase A succeeds MAY Phase B execute artifact helpers, import artifact modules, run artifact subprocesses, install wheel-only locked dependencies, or build a candidate runtime. No runtime, lifecycle, dispatcher, marketplace, plugin, MCP, Codex, active-record, or transaction authority SHALL change before Phase A succeeds. Temporary acquisition paths SHALL never become installed or rollback authority.

#### Scenario: Verified artifact enters Phase B
- **WHEN** index, archive, members, manifest, inventory and topology agree
- **THEN** the verified artifact root may enter semantic validation and candidate construction

#### Scenario: Any pinned digest differs
- **WHEN** index, archive or manifest bytes fail the expected digest
- **THEN** installation stops before artifact code executes or product state changes

#### Scenario: Extraction boundary is unsafe
- **WHEN** a member, destination, ancestor, inventory or resource bound violates Phase A
- **THEN** installation fails with prior authority unchanged

### Requirement: Installation requires no checkout and has one active authority
macOS and native Windows SHALL install without Git, repository cloning, `.git`, or retained source. Supported Python, `uv`, Codex, a writable absolute `PATH` directory, and the platform download facility remain prerequisites. `DEV_FLOW_SOURCE_ROOT` and checkout-driven lifecycle invocation SHALL fail before mutation.

A managed release SHALL contain the isolated environment, sealed plugin, runtime receipt, installed-content verifier, and versioned lifecycle entry points. The receipt SHALL bind the complete artifact and installed identity. The active record SHALL be the only local selector of the active release and SHALL bind a closed schema, monotonic generation, release ID, contained release path, receipt digest, stable-dispatcher protocol, and committing transaction ID.

`dev-flow`, `dev-flow-mcp`, and `dev-flow-uninstall` SHALL be small stable product-owned dispatchers. Ordinary repair, upgrade and automatic rollback SHALL reuse them; versioned verification and lifecycle behavior SHALL live inside managed releases. The personal marketplace SHALL point only to the exact plugin root inside the active managed release.

#### Scenario: Fresh host has no Git
- **WHEN** all other prerequisites and the selected artifact are valid
- **THEN** installation succeeds with the bundled Skill and STDIO MCP and creates no checkout

#### Scenario: Candidate passes staged health
- **WHEN** wheel, dependencies, plugin, Skill, MCP, receipt, verifier and helpers share one identity
- **THEN** it may enter provisional host activation without yet becoming active authority

#### Scenario: Temporary path is proposed as authority
- **WHEN** a download, extraction, checkout or staging path would become marketplace or active authority
- **THEN** activation is rejected

### Requirement: Lifecycle mutation is serialized and has explicit terminal outcomes
Install, repair, upgrade, migration, recovery and uninstall SHALL acquire one installation-wide lock before reading active or transaction authority and SHALL hold it until a terminal outcome is durable. Each operation SHALL create or resume one bounded journal recording expected active generation and digest, target and previous authority, exact external observations, provisional effects, transaction-owned paths, phase and outcome. Active creation, replacement, restoration and removal SHALL use generation-and-digest compare-and-swap.

Activation SHALL complete candidate-specific staged health, provision and read back marketplace and Codex plugin state, commit the active record by CAS, and then run real public CLI and MCP startup proof while still holding the lock. It SHALL record `committed` only after public proof succeeds. Failure SHALL restore and prove the immediate previous authority and record `rolled_back`, or preserve uncertainty, stop identity-specific mutation and record `partial`.

The immediate previous runtime SHALL remain until the activation transaction is terminal; automatic rollback SHALL require neither network nor checkout. This change SHALL NOT expose arbitrary historical rollback. Repair MAY reuse only a fully attested active runtime; drift SHALL build a verified same-version candidate. Repair SHALL reject a different digest envelope for an already installed version. Upgrade SHALL run the target version's bootstrap. A new lifecycle request SHALL first recover or classify any non-terminal journal and SHALL NOT retry indefinitely or broaden cleanup.

#### Scenario: Competing lifecycle operations start
- **WHEN** two upgrades, or upgrade and uninstall, target one installation
- **THEN** lock and generation CAS prevent provisional effects from interleaving

#### Scenario: Candidate fails before active commit
- **WHEN** acquisition, verification, construction, staged health or provisional read-back fails
- **THEN** previous authority is restored or unchanged and the transaction becomes `rolled_back`

#### Scenario: Public proof fails after active commit
- **WHEN** the real public CLI or MCP path fails after target generation commit
- **THEN** the installer CAS-restores and revalidates previous authority or records `partial`

#### Scenario: Prior transaction was interrupted
- **WHEN** a new lifecycle command finds a non-terminal journal
- **THEN** it first recovers or classifies that journal and refuses new mutation while authority is unresolved

### Requirement: Runtime startup attests before project import
Stable CLI and MCP dispatchers SHALL minimally validate the active record, contained release path, receipt digest, dispatcher protocol, and versioned verifier digest before invoking the active verifier. The active verifier SHALL validate the complete receipt and installed identity before importing Dev Flow code or initializing MCP.

Startup attestation SHALL be described as protection against corruption, drift and cross-release mixing, not against coherent replacement of all same-user trust inputs.

#### Scenario: Installed release is intact
- **WHEN** active, receipt, runtime, plugin, dependency, Python, verifier and owned-file evidence agree
- **THEN** the selected CLI or `dev-flow-mcp --stdio` entry point may run

#### Scenario: Installed release has drifted
- **WHEN** required active or installed evidence is missing, malformed, changed or cross-release
- **THEN** startup fails before project import and reports exact-version repair guidance

### Requirement: Uninstall is source-independent and ownership-bounded
`dev-flow-uninstall` SHALL validate stable infrastructure and current authority, verify a copied minimal standard-library removal driver, and create or resume a durable uninstall transaction under the lifecycle lock.

Uninstall SHALL remove only exact compare-and-remove matches and empty owned directories. It SHALL read back plugin and marketplace state, remove the active record by generation CAS, remove managed releases before stable CLI and MCP dispatchers, remove lifecycle support and the uninstall dispatcher last, and perform no product mutation after lock removal. Rerun after interruption SHALL resume or classify the journal without a checkout or removed runtime.

Changed, unknown, concurrent, linked, reparse, special or unprovable content SHALL be retained and reported. Controller task data, unrelated Codex state, unrelated launchers, standalone MCP registrations, and every checkout SHALL remain outside the removal set.

#### Scenario: Exact owned installation is removed
- **WHEN** all product-owned state matches exact ownership evidence
- **THEN** uninstall removes product authority without repository files and records `committed`

#### Scenario: Unknown content is encountered
- **WHEN** an owned root or external component contains changed or unprovable content
- **THEN** uninstall retains it, avoids broad deletion, reports exact paths, and records `partial` when needed

#### Scenario: Uninstall is interrupted
- **WHEN** the process terminates after recording a removal phase
- **THEN** rerun resumes or classifies the journal without a checkout or removed runtime

### Requirement: Legacy migration is bounded to the known predecessor
The artifact installer SHALL migrate only installations matching frozen fixtures for the immediately preceding conforming checkout installer. Fixtures SHALL define accepted plugin observations, launcher markers, receipt and ownership schemas, marketplace shape and transaction outcomes. Older, future, malformed or ambiguous installations SHALL fail before identity-specific mutation.

Migration SHALL classify previous authority only from installed observations. It SHALL NOT read, execute, update, clean, seal or delete a checkout, and the checkout SHALL NOT be rollback input. A conforming previous runtime MAY serve as immediate rollback authority while the artifact candidate is unsettled.

#### Scenario: Known predecessor is migrated
- **WHEN** fixtures prove one previous authority and the candidate passes activation and public proof
- **THEN** the artifact release becomes authoritative and the checkout remains untouched

#### Scenario: Migration fails before host effects
- **WHEN** Phase A, Phase B, construction or staged health fails
- **THEN** previous installation and checkout remain unchanged and the transaction becomes `rolled_back`

#### Scenario: Previous installation is unsupported or ambiguous
- **WHEN** observations do not match fixtures or prove one authority
- **THEN** migration fails before identity-specific mutation and reports conflicts

### Requirement: Delivery evidence has a bounded completion gate
Shared verifier and state-machine behavior SHALL be tested primarily through unit and deterministic simulated integration tests. Native macOS and native Windows SHALL each run one final-artifact lifecycle on one supported Python version covering fresh install, healthy and drift repair, successful upgrade, one failed-activation rollback, one interrupted transaction, startup, predecessor migration, uninstall and task-data preservation.

The supported Python matrix SHALL run lightweight wheel-only installation and import or MCP smoke checks rather than repeat the full lifecycle matrix. Concurrency evidence SHALL cover only upgrade-versus-upgrade and upgrade-versus-uninstall. A release candidate SHALL use a real Codex host for plugin read-back, bundled Skill discovery, STDIO MCP startup and uninstall; ordinary pull requests MAY use deterministic fakes.

Static or simulated PowerShell SHALL NOT count as native Windows evidence. Completion SHALL require re-downloaded final assets, both native gates, all Requirements and tasks, aligned English and Simplified Chinese documentation, and only `committed`, `rolled_back`, or `partial` lifecycle results.

Signing, offline fresh install, automatic updates, arbitrary historical rollback, broader legacy migration, general Unicode artifact members, or dispatcher-protocol migration SHALL require separate OpenSpec changes.

#### Scenario: Candidate satisfies the completion target
- **WHEN** final assets, native gates, Python smoke matrix, real Codex evidence, strict OpenSpec validation and repository checks pass
- **THEN** the change may be marked complete with actual digests, evidence and limitations recorded

#### Scenario: Native Windows evidence is unavailable
- **WHEN** validation uses only macOS or static or simulated PowerShell
- **THEN** the change remains incomplete for Windows and Windows is reported unverified

#### Scenario: A non-goal is requested
- **WHEN** implementation would add a listed non-goal
- **THEN** that work is excluded and requires a separate OpenSpec proposal
