## ADDED Requirements

### Requirement: Release production emits one complete immutable artifact
For every published product version, release production SHALL build one platform-neutral `dev-flow-orchestrator-<version>.tar.gz`, one `release-index.json`, and version-matched macOS and Windows bootstrap installers from an exact clean tagged commit. The archive SHALL contain the complete sealed Codex plugin tree, one project wheel, hash-locked runtime requirements, lifecycle and integrity helpers, and a closed embedded release manifest.

The release index SHALL bind the product version, canonical repository, source commit and tree, exact archive name, archive SHA-256, archive size bound, and embedded-manifest SHA-256. The embedded manifest SHALL inventory every payload member by normalized relative path, type, mode, size, and SHA-256. Product version and component identity SHALL agree across the tag, index, plugin manifest, wheel metadata, requirements provenance, and embedded manifest.

The archive SHALL have one top-level directory and SHALL contain only declared regular files and directories. Release validation SHALL reject duplicate or case-colliding normalized paths, absolute paths, parent traversal, links, devices, FIFOs, undeclared members, missing members, and local paths or credentials. Archive construction SHALL normalize ordering, timestamps, ownership, permissions, and compression metadata so repeated builds from the same inputs produce identical archive and manifest digests.

#### Scenario: Valid release artifact is produced
- **WHEN** release automation builds an artifact from an exact clean tagged commit whose version metadata agrees
- **THEN** the published index, archive, embedded manifest, plugin tree, wheel, requirements, and lifecycle helpers pass package and release validation with one shared version and immutable content identity

#### Scenario: Component version or content disagrees
- **WHEN** the tag, plugin manifest, wheel metadata, requirements provenance, embedded manifest, or archive bytes disagree with the release index
- **THEN** publication fails and no asset set is reported as a valid product release

#### Scenario: Archive contains an unsafe or undeclared member
- **WHEN** a candidate archive contains a path collision, traversal, link, special member, undeclared entry, or entry outside its single top-level directory
- **THEN** release validation rejects the archive before publication

#### Scenario: Release build is repeated
- **WHEN** the same tagged source and locked dependency inputs are assembled twice in clean release environments
- **THEN** the logical manifest, archive SHA-256, and every payload digest are identical

### Requirement: Bootstrap verifies the official release before executing artifact code
The public bootstrap installer SHALL select one exact version and accept release assets only from the canonical HTTPS GitHub Release path for the configured official repository and that version. A bootstrap obtained through the `latest` release route SHALL carry the selected version and SHALL use version-specific asset locators thereafter. Redirects SHALL remain HTTPS and preserve the exact expected asset names.

The bootstrap SHALL download the release index and archive into a newly created installer-owned temporary directory. Before executing any artifact-provided helper or mutating runtime, lifecycle, launcher, marketplace, plugin, MCP, or Codex state, it SHALL validate the closed index schema and source identity, enforce download and declared-size bounds, verify the archive SHA-256, inspect every archive header and normalized member path, extract without following links or overwriting existing paths, verify the embedded-manifest digest, and verify the complete extracted inventory.

Temporary acquisition and extraction paths SHALL NOT become installed authorities. The installer SHALL remove its temporary content after every success or handled failure and SHALL report any cleanup limitation without claiming a clean result.

#### Scenario: Official versioned artifact passes verification
- **WHEN** the selected version's canonical release index, archive digest, archive members, embedded manifest, and extracted inventory all agree
- **THEN** the bootstrap may pass the verified artifact root to package validation and managed-runtime staging

#### Scenario: Archive digest or manifest digest mismatches
- **WHEN** downloaded archive bytes do not match the index or the embedded manifest does not match the digest pinned by the index
- **THEN** installation fails before executing artifact code or mutating any installed component

#### Scenario: Downloaded archive is unsafe
- **WHEN** archive inspection finds an oversized, duplicate, case-colliding, absolute, traversing, linked, special, undeclared, or out-of-root member
- **THEN** extraction and installation fail with the existing installation unchanged

#### Scenario: Release locator is not canonical
- **WHEN** a public installation attempts to acquire the index or archive from a non-HTTPS, different-repository, different-version, or unexpected asset locator
- **THEN** the bootstrap rejects the locator before downloading or mutating product state

#### Scenario: Installation attempt terminates
- **WHEN** installation succeeds or reaches a handled failure after creating acquisition staging
- **THEN** no bootstrap download or extraction directory is retained as a product, marketplace, launcher, receipt, or rollback authority

### Requirement: Fresh installation requires no Git checkout
The macOS and native Windows installation paths SHALL install from the verified release artifact without requiring the `git` executable, cloning a repository, creating a `.git` directory, or retaining project source. Supported Python, `uv`, Codex, a writable absolute `PATH` directory, and the platform download facility SHALL remain explicit prerequisites.

The durable installation set SHALL be limited to content-addressed managed runtime releases, owned lifecycle support, owned launchers, the personal-marketplace member and installed plugin state, bounded transaction and active records, and Controller task data. `DEV_FLOW_SOURCE_ROOT` and checkout-driven lifecycle invocation SHALL fail before mutation with artifact-migration guidance.

#### Scenario: Fresh host has no Git executable
- **WHEN** all supported prerequisites except Git are available and the official release artifact is valid
- **THEN** fresh installation succeeds and exposes the bundled Skill and MCP without creating or retaining a source checkout

#### Scenario: Legacy source-root option is supplied
- **WHEN** an operator supplies `DEV_FLOW_SOURCE_ROOT` to the artifact installer
- **THEN** the installer makes no product mutation and reports that release selection is artifact-based with migration guidance

#### Scenario: Fresh installation completes
- **WHEN** a verified candidate is committed successfully
- **THEN** every durable product path belongs to the declared installation set and neither the downloaded archive nor an extracted source tree remains

### Requirement: Managed runtime activates the complete artifact identity
Managed-runtime construction SHALL consume only the verified artifact root. It SHALL install the supplied hash-locked requirements and prebuilt project wheel into an isolated environment, copy and verify the sealed plugin tree, run installed Skill and MCP health checks, generate owned launchers, and atomically publish a release-specific runtime directory.

The runtime receipt and active installation record SHALL bind the release-index digest, archive digest, embedded-manifest digest, source commit and tree, project-wheel digest, requirements digest, plugin-release digest, installed distribution inventory, Python identity, lifecycle-helper digest, launcher digests, transaction identity, and release path. The personal marketplace SHALL point to the exact managed plugin root. No bootstrap, download, extraction, checkout, or mutable shared directory SHALL be recorded as the plugin source or runtime authority.

The installed plugin SHALL retain the `dev-flow` Skill, `.mcp.json` registration for `dev-flow-mcp --stdio`, existing plugin ID, expected MCP tool catalog, and installed validation evidence.

#### Scenario: Candidate runtime passes installed health
- **WHEN** the verified artifact is staged and its wheel, requirements, plugin, Skill, MCP registration, launchers, and receipt all match one release identity
- **THEN** the runtime may be promoted and the marketplace may name its managed plugin root

#### Scenario: Installed component differs from the artifact
- **WHEN** any installed dependency, wheel, plugin member, Skill file, MCP registration, lifecycle helper, launcher, receipt field, or marketplace path differs from the verified artifact identity
- **THEN** activation and active-record commit fail and no receipt claims those bytes as the selected release

#### Scenario: Temporary path is proposed as installed authority
- **WHEN** activation would record a bootstrap, download, extraction, checkout, or transaction-staging path as the marketplace or runtime source
- **THEN** validation rejects the candidate before plugin activation

### Requirement: Repair, upgrade, and rollback use verified runtime releases
Repair of the exact active version SHALL reuse a managed runtime only after complete receipt, ownership, plugin, distribution, launcher, lifecycle, and startup attestation. Any mismatch SHALL rebuild a candidate from a newly acquired and verified artifact.

Upgrade SHALL acquire, verify, build, and smoke-test the candidate before changing the active plugin, marketplace, launchers, or lifecycle support. The previous conforming managed runtime and receipt SHALL be the complete rollback source. Rollback SHALL NOT require network acquisition, Git, or a source checkout and SHALL be complete only after previous plugin read-back and installed health succeed.

If a provisional external effect cannot be classified exactly, the transaction SHALL prohibit active commit and identity-specific cleanup, preserve uncertain content, record a truthful `partial` result, and provide bounded recovery guidance.

#### Scenario: Exact active release is healthy
- **WHEN** repair observes that the complete active runtime and artifact attestation still match
- **THEN** it may reuse that runtime after installed health succeeds and SHALL NOT create a checkout

#### Scenario: Exact active release has drifted
- **WHEN** repair finds a receipt, owned file, dependency, plugin, launcher, lifecycle, or startup mismatch
- **THEN** it stages a fresh candidate from the verified artifact and does not claim reuse of the drifted runtime

#### Scenario: Candidate build fails before activation
- **WHEN** artifact acquisition, verification, runtime construction, or staged health fails
- **THEN** the previous active release remains unchanged and usable

#### Scenario: Candidate activation fails after provisional effects
- **WHEN** marketplace, launcher, lifecycle, or plugin activation changes began but candidate read-back or health fails
- **THEN** the installer restores and revalidates the retained previous runtime or records a truthful partial result if exact restoration cannot be proven

#### Scenario: Rollback occurs without acquisition inputs
- **WHEN** the candidate fails after the previous artifact download and any source checkout are unavailable
- **THEN** rollback succeeds from the retained previous runtime, plugin assets, receipt, lifecycle support, and launcher evidence alone

### Requirement: Runtime startup attests the installed release before import
The managed MCP and CLI launch paths SHALL invoke an installer-owned verifier before importing project runtime code. The verifier SHALL validate the active record, receipt schema, release path, artifact and plugin manifest digests, wheel and installed distribution inventory, exact runtime dependencies, Python identity, lifecycle and launcher identity, and complete owned-file inventory. Missing, malformed, incompatible, changed, or cross-release evidence SHALL fail closed before project import or MCP initialization.

#### Scenario: Installed release is intact
- **WHEN** a managed launcher starts and every active-record, receipt, artifact, runtime, plugin, dependency, Python, and launcher claim matches installed content
- **THEN** the verifier permits the selected CLI or `dev-flow-mcp --stdio` entry point to run

#### Scenario: Installed release has drifted
- **WHEN** startup finds a missing, malformed, incompatible, changed, or mismatched receipt, file, dependency, interpreter, plugin, lifecycle helper, or launcher
- **THEN** startup fails before importing Dev Flow project code and reports repair guidance

### Requirement: Uninstall is source-independent and ownership-bounded
Installation SHALL provide an owned `dev-flow-uninstall` command and lifecycle helper whose digests are bound by the active record. Before product mutation, uninstall SHALL validate current installed authority, copy the minimal standard-library removal helper to a newly created temporary directory, verify that copy, and execute it with a supported system Python so removal does not depend on the managed runtime or a checkout remaining present.

Uninstall SHALL remove only entries matching exact ownership manifests and empty owned directories, with lifecycle support and uninstall launchers removed last. It SHALL preserve and report changed, unknown, concurrent, symlinked, reparse, special, or unprovable content. It SHALL preserve Controller task data, unrelated marketplace members, unrelated plugins, unrelated launchers, standalone MCP registrations, and every source checkout.

#### Scenario: Exact owned installation is uninstalled
- **WHEN** active authority and every product-owned entry match their ownership evidence
- **THEN** plugin state, marketplace member, managed runtime, lifecycle support, and owned launchers are removed without a source checkout and uninstall reports complete success

#### Scenario: Unknown or changed content is encountered
- **WHEN** an owned root contains an entry that is changed, unknown, concurrent, linked, special, or not covered by exact ownership evidence
- **THEN** uninstall retains that content, avoids broad recursive deletion, reports a partial result and exact retained paths, and preserves unrelated state

#### Scenario: Controller task data exists
- **WHEN** uninstall removes an otherwise exact installation
- **THEN** Controller task data and its model namespace remain unchanged

#### Scenario: Legacy checkout exists
- **WHEN** a source checkout from an older installation remains on disk
- **THEN** uninstall neither reads nor deletes it and reports it, when known, as external user-owned content

### Requirement: Checkout-based installations migrate transactionally
The artifact installer SHALL classify an existing Dev Flow installation using plugin observations, managed launcher markers, runtime receipts, marketplace state, and transaction records. It SHALL NOT inspect, fetch, fast-forward, clean, seal, or execute a source checkout during migration.

A conforming previous runtime MAY serve as rollback authority while the artifact candidate is staged. The artifact release SHALL become active only after exact plugin read-back, bundled Skill and MCP validation, installed health, and active-record commit. Successful migration SHALL install the source-independent lifecycle bootstrap. Failed migration SHALL leave the prior installation usable or report a truthful partial result under the normal transaction rules.

#### Scenario: Conforming checkout-based installation is migrated
- **WHEN** a previous managed runtime is provable and the new artifact candidate passes activation and health
- **THEN** the artifact release becomes active, future lifecycle operations require no checkout, and the legacy checkout remains untouched for manual disposition

#### Scenario: Migration candidate fails before activation
- **WHEN** artifact verification, runtime construction, or staged health fails during migration
- **THEN** the previous installation and any existing checkout remain unchanged

#### Scenario: Previous installation identity is ambiguous
- **WHEN** plugin, launcher, receipt, marketplace, or transaction observations do not prove one previous authority
- **THEN** migration fails before identity-specific mutation and reports the conflicting observations

### Requirement: Delivery evidence and documentation describe the artifact lifecycle
Release validation SHALL cover deterministic artifact construction, malformed index and archive cases, pre-execution failure boundaries, fresh install without Git, exact-version repair, drift rebuild, upgrade, activation rollback, startup attestation, checkout-free uninstall, legacy migration, and installed Skill/MCP coexistence. macOS and native Windows evidence SHALL be recorded independently; static or simulated PowerShell evidence SHALL NOT be reported as native Windows verification.

The English source documentation and corresponding Simplified Chinese translations SHALL describe the artifact-based prerequisites, commands, version selection, durable paths, integrity boundary, upgrade and rollback behavior, migration, uninstall, retained task data, and platform evidence with equivalent scope and constraints.

#### Scenario: Candidate is assessed for release
- **WHEN** implementation verification is performed
- **THEN** package validation, focused lifecycle tests, complete repository tests, installed journeys, strict OpenSpec validation, and supported-platform evidence report their actual results and limitations

#### Scenario: Native Windows evidence is unavailable
- **WHEN** validation runs only on macOS or through static or simulated PowerShell checks
- **THEN** Windows lifecycle status remains explicitly unverified rather than inferred from non-native evidence

#### Scenario: Public documentation is validated
- **WHEN** package validation inspects installation documentation
- **THEN** English and Simplified Chinese documents contain aligned artifact commands, paths, prerequisites, compatibility behavior, and safety boundaries and no supported path requires a persistent clone
