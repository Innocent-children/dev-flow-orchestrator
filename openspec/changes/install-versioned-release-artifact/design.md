## Context

The current installer treats a clean checkout of the authoritative `main` branch as its acquisition, provenance, repair, upgrade, and uninstall anchor. It exports a verified Git tree, creates a sealed plugin copy, builds a wheel and isolated environment, activates the plugin from the managed runtime, and retains the checkout for later lifecycle operations.

The installed product is already mostly source-independent. The personal marketplace points to a release-specific plugin copy under the managed runtime, the MCP launcher uses the runtime virtual environment, and receipts and ownership manifests bind installed files, dependencies, Python identity, launchers, and plugin content. The checkout remains because lifecycle scripts reacquire source and because uninstall loads an ownership helper from the checkout.

This change replaces only that acquisition and lifecycle dependency. Release production may use Git; end-user installation may not require or retain it. The release artifact must carry the complete Codex plugin assets in addition to the Python wheel because the bundled Skill and `.mcp.json` registration are not wheel-only resources.

## Goals / Non-Goals

**Goals:**

- Install, repair, upgrade, automatically roll back failed activation, recover interrupted lifecycle work, and uninstall from a version-addressed release artifact without a persistent source checkout.
- Verify release bytes and the complete extracted payload before executing artifact-provided code or mutating installed authority.
- Preserve the bundled Skill, STDIO MCP, managed runtime, exact ownership, Controller authority, task data, and unrelated Codex configuration.
- Reduce durable authority to one active record, one installation-wide lifecycle lock, runtime receipts, and bounded transaction journals.
- Support the same product contract on macOS and native Windows while reporting platform evidence independently.
- Migrate only the immediately preceding conforming checkout-based installation without reading, changing, or deleting its checkout.

**Non-Goals:**

- Build a general package manager, automatic updater, release channel system, or background service.
- Add independent release signing, Sigstore, transparency-log verification, third-party mirrors, or offline fresh installation.
- Defend against an attacker that already has unrestricted write access to the user's bootstrap, active record, dispatchers, verifier, and managed runtime at the same time.
- Support arbitrary Unicode archive member names. Artifact-internal names use a closed portable ASCII grammar; user installation roots may still contain spaces, apostrophes, and Unicode.
- Provide user-selectable rollback to arbitrary historical versions or retain an unbounded release history. Rollback in this change means automatic restoration of the immediate previous authority while the current activation transaction is unsettled.
- Guarantee byte-identical compressed archives across arbitrary operating systems or toolchains. Reproducibility is evaluated in the pinned release-builder environment.
- Migrate every historical checkout installer schema or delete any legacy checkout.
- Repeat the full lifecycle and failure-injection matrix on every supported Python minor version.
- Change the Controller model, workflow catalog, MCP tool names or schemas, task-data namespace, plugin ID, or personal-marketplace mode.

## Completion and Terminal Outcomes

The implementation stops when the final release artifact satisfies the release gates in this change on macOS and native Windows. Scope expansion beyond the stated non-goals requires a separate OpenSpec change.

Every lifecycle command must finish in exactly one of these terminal outcomes:

- `committed`: the requested release or uninstall state is authoritative and read back successfully. Exact cleanup residue that is no longer authoritative may be retained and reported without changing this outcome.
- `rolled_back`: the candidate is not authoritative and the immediate previous authority, or the absence of an authority for a failed fresh install, has been restored and proven.
- `partial`: neither the requested authority nor the previous authority can be proven exactly. Automatic identity-specific mutation stops, uncertain content is preserved, and the transaction records the observed state and bounded recovery guidance.

A command must not return success while its transaction remains non-terminal, while the active record disagrees with observed plugin or marketplace state, or while an unclassified provisional effect remains.

## Decisions

### Publish one closed platform-neutral artifact

Each product version uses the release grammar `MAJOR.MINOR.PATCH` and tag `v<version>`. Release production emits:

- `dev-flow-orchestrator-<version>.tar.gz`;
- `release-index.json`;
- version-matched `install.sh` and `install.ps1` bootstraps.

The archive has this fixed top-level layout:

```text
dev-flow-orchestrator-<version>/
  release-manifest.json
  plugin/**
  wheels/dev_flow_orchestrator-<version>-py3-none-any.whl
  runtime-requirements.txt
  uv.lock
  lifecycle/**
```

`plugin/**` is the complete sealed Codex plugin tree and includes `.codex-plugin/plugin.json`, `.mcp.json`, `skills/dev-flow/**`, plugin-side CLI assets, and installed-validation assets. `lifecycle/**` contains the versioned standard-library helpers used after pre-execution verification. The archive contains exactly one project wheel and no source distribution.

`release-index.json` uses the closed schema `dev-flow-release-index/1.0.0` and binds:

- product version and canonical repository;
- source commit and source tree as release-builder provenance assertions;
- exact archive filename, byte size, and SHA-256;
- SHA-256 of the raw UTF-8 bytes of `release-manifest.json`;
- the fixed artifact schema version.

`release-manifest.json` uses the closed schema `dev-flow-release-artifact/1.0.0`. Its entries are relative to the archive top-level directory and cover every descendant except `release-manifest.json` itself. The external index pins the manifest bytes, avoiding a self-referential manifest entry. Directory entries bind `path`, `type`, and declared `mode`. Regular-file entries additionally bind `size` and SHA-256. Unknown fields, duplicate JSON keys, duplicate paths, missing entries, and undeclared entries are rejected.

Artifact member paths use `/` as the only separator. Every component must match `[A-Za-z0-9._-]+`; empty components, `.`, `..`, backslashes, colons, control characters, trailing dots or spaces, and absolute or drive-qualified forms are rejected. An ASCII-lowercase key is used to reject case collisions. Windows device basenames such as `CON`, `PRN`, `AUX`, `NUL`, `COM1` through `COM9`, and `LPT1` through `LPT9` are rejected even when followed by an extension. This deliberately avoids a general Unicode-normalization protocol for artifact-internal names.

The archive contains only directories and regular files. Symbolic links, hard links, junction-like entries, devices, FIFOs, sparse files, and unsupported tar extensions are rejected. Declared modes are limited to `0755` for directories and declared executable helpers and `0644` for other regular files. Windows validates the declared archive and manifest mode but does not claim an equivalent NTFS executable-bit identity.

The shared verifier owns fixed hard caps for index bytes, manifest bytes, archive bytes, entry count, component length, relative path length, nesting depth, per-file extracted bytes, and total extracted bytes. The index may declare smaller bounds but cannot raise bootstrap hard caps.

### Build from pinned inputs without broad reproducibility claims

Release automation runs in one pinned builder environment with fixed Python, `uv`, build backend, tar, and gzip implementations. It validates an exact clean tagged commit, builds one pure-Python wheel, exports `runtime-requirements.txt` from the included `uv.lock`, assembles the allow-listed payload, and generates the manifest, archive, index, and version-matched bootstraps.

The requirements export contains exact transitive versions, environment markers, and hashes for supported hosts. End-user dependency installation is hash-required and wheel-only so it does not execute an sdist build backend. Release validation checks that the project wheel is pure Python, has the expected project name and version, has a closed safe member set, and agrees with the plugin and release metadata.

Two clean instances of the pinned builder environment must produce identical logical manifests, payload digests, and compressed archive bytes. The change does not claim that an arbitrary different OS, Python, tar, or gzip implementation produces identical compressed bytes.

The builder uses a closed payload allow-list and rejects untracked, ignored, cache, home, temporary, and credential-configuration inputs. A best-effort secret and local-path scan is supporting evidence, not a proof that no possible credential byte pattern exists.

All four release assets are built and validated before promotion. Promotion refuses to overwrite an existing asset set for the same version, uploads through an explicit release operation, re-downloads the final version-specific assets, and records their digests before the release is considered complete.

### Treat the version-matched bootstrap as the first release trust root

The production bootstrap hard-codes the canonical repository, product version, expected `release-index.json` SHA-256, artifact filename, and bootstrap schema version. A bootstrap downloaded through a `latest` route may select the release, but after execution it constructs only version-specific release URLs. Production command-line options do not permit an alternate repository or mirror; tests replace the downloader at an internal test seam rather than exposing a public origin override.

The initial index and archive requests use canonical HTTPS GitHub Release URLs. GitHub-controlled HTTPS redirects are transport details and do not establish identity; the embedded index digest and archive digest establish byte consistency after download. A redirect to a non-HTTPS target is rejected.

The first-version trust boundary is:

- the bootstrap bytes the user chose to execute;
- the canonical GitHub repository and its release publication permissions;
- HTTPS/TLS and GitHub delivery infrastructure;
- the supported system Python, platform download facility, `uv`, and Codex installation;
- the user's local account and filesystem permissions.

SHA-256 proves that downloaded and extracted bytes agree with the version-matched bootstrap, index, and manifest. It detects corruption, partial replacement, and cross-release mixing. It does not independently prove that a GitHub account was not compromised, that a same-version asset was never replaced before download, or that source provenance was reconstructed by the end-user installer. The source commit and tree are release-builder assertions bound into the digest envelope.

### Separate pre-execution verification from verified artifact execution

Both bootstraps embed the same standard-library Phase A verifier as bootstrap-owned code. Before executing any code from the archive or mutating runtime, lifecycle, launcher, marketplace, plugin, MCP, or Codex authority, Phase A:

1. downloads the index under a fixed byte cap and verifies its bootstrap-pinned SHA-256 before parsing;
2. parses strict closed JSON and verifies repository, version, archive name, schema, and fixed bounds;
3. downloads the archive with streaming byte accounting and verifies its exact size and SHA-256 before extraction;
4. inspects all tar headers, member types, portable paths, collisions, declared modes, and resource bounds before writing any member;
5. extracts only into a newly created empty installer-owned directory using exclusive file creation and without following links or reparse points in any ancestor;
6. verifies the raw embedded-manifest digest and strict schema;
7. compares the complete extracted inventory with the manifest; and
8. performs static topology checks for the plugin root, one project wheel, locked requirements, `uv.lock`, and lifecycle helper set without importing artifact modules or running artifact subprocesses.

Only after Phase A succeeds may Phase B execute a helper from the verified artifact. Phase B performs semantic package validation, constructs a transaction-owned candidate runtime, installs wheel-only hash-locked dependencies and the supplied project wheel, and runs candidate-specific Skill and MCP health. Candidate staging is not an installed authority and may be removed by exact transaction ownership.

Temporary download and extraction roots never become marketplace, launcher, receipt, active-record, or rollback authorities. They are cleaned after every handled outcome, and retained paths are reported truthfully.

### Keep one local authority and stable external dispatchers

A managed release contains the isolated environment, sealed plugin tree, runtime receipt, full installed-content verifier, and versioned lifecycle entry points. The runtime receipt binds the complete release identity:

- index, archive, and embedded-manifest digests;
- source commit and tree assertions;
- wheel, requirements, and `uv.lock` digests;
- installed distribution inventory and Python identity;
- plugin-release digest and complete owned-file inventory;
- versioned verifier and lifecycle helper digests;
- release path and transaction identity.

The active record is intentionally smaller. It is the single local authority and binds only its closed schema, monotonic generation, release ID, absolute contained managed-release path, runtime-receipt digest, stable-dispatcher protocol, and committing transaction ID. Other records must not independently select a different active release.

`dev-flow`, `dev-flow-mcp`, and `dev-flow-uninstall` are small product-owned stable dispatchers installed in the selected writable absolute `PATH` directory. Their bytes are installation infrastructure rather than per-release payload and are replaced only when the dispatcher protocol changes. Ordinary repair, upgrade, and rollback leave them unchanged.

The CLI and MCP dispatchers perform minimal standard-library checks of the active-record schema, contained release path, receipt digest, and versioned verifier digest before invoking the active release's verifier. The versioned verifier then validates the full receipt and installed content before importing Dev Flow project code. This startup attestation protects against corruption, drift, and cross-release mixing; it is not claimed to resist an attacker that can coherently replace every same-user trust input.

The personal marketplace continues to point to the exact plugin root inside the managed release. It never points to a bootstrap, download cache, extraction directory, source checkout, transaction staging directory, or mutable shared plugin directory.

### Serialize lifecycle changes and use generation-based commit

Fresh install, repair, upgrade, migration, recovery, and uninstall use one installation-wide lifecycle lock. The lock is acquired before reading the active record or any transaction journal and is held until a terminal outcome is durably recorded. No product-state mutation occurs after the lock is removed during uninstall.

Each lifecycle operation creates one bounded transaction journal containing:

- a unique transaction ID and operation type;
- expected active generation and active-record digest, or expected absence for fresh install;
- target release identity;
- previous authority and exact external observations;
- provisional effects and their expected compare-and-replace values;
- candidate and retained paths owned by the transaction;
- current phase and terminal outcome.

Active-record creation, replacement, restoration, and removal use compare-and-swap against the expected generation and record digest. A monotonic generation prevents a stale process or an `A -> B -> A` sequence from satisfying an old observation.

Candidate activation is intentionally two-stage:

1. Phase B builds the candidate and proves candidate-specific Skill, MCP, package, receipt, and runtime health without using the public active record.
2. Under the lifecycle lock, the installer applies provisional marketplace and Codex plugin changes and reads them back.
3. If read-back is exact, the installer commits the active record with generation CAS.
4. While still holding the lock, it invokes the real public CLI and MCP startup paths as post-commit proof.
5. If post-commit proof succeeds, the transaction becomes `committed`.
6. If any provisional step before active commit fails, the installer restores and reads back the previous external state.
7. If post-commit proof fails, the installer CAS-restores the previous active generation, restores external state, and revalidates the previous public startup path.
8. If exact restoration cannot be proven, the transaction becomes `partial` and automatic identity-specific cleanup stops.

The immediate previous runtime remains available until the activation transaction reaches a terminal outcome. After a successful commit it is not a supported manual rollback target and may be removed by exact ownership cleanup. A retained inactive runtime caused by unknown or changed content is reported as non-authoritative residue. This change does not expose a public arbitrary-version rollback command.

### Use versioned bootstraps for install, repair, and upgrade

The lifecycle interfaces are deliberately small:

- fresh install runs the target version's public bootstrap;
- exact-version repair reruns the bootstrap matching the active version;
- upgrade runs the target version's bootstrap;
- automatic rollback is internal to an unsettled activation transaction;
- any bootstrap or uninstall command first recovers a non-terminal prior transaction under the lifecycle lock;
- uninstall runs `dev-flow-uninstall` and requires no checkout or network acquisition.

A healthy exact-version repair may reuse the active release only after complete startup and ownership attestation. Drift causes a newly acquired and verified same-version candidate to be constructed. If the remote asset set for an already installed version has a different index, archive, or manifest digest than the active receipt, repair fails with a same-version identity-change error rather than silently adopting different bytes.

Recovery either proves and records the prior transaction as `committed` or `rolled_back`, or records `partial` and refuses the new requested mutation. It does not retry indefinitely or broaden cleanup to make progress.

### Make uninstall source-independent and crash-classifiable

The stable uninstall dispatcher contains or locates only a minimal bootstrap-owned standard-library removal driver. Before mutation it verifies its own expected digest, the lifecycle state, and the active authority, then copies the driver to a newly created bounded temporary directory and verifies the copy.

Under the same lifecycle lock, uninstall creates a durable uninstall transaction that records the expected active generation, exact product-owned external state, owned runtime and lifecycle paths, and removal phase. The copied helper can continue after the active managed runtime is removed. Removal proceeds by exact compare-and-remove operations:

1. remove and read back the Dev Flow Codex plugin state;
2. compare-and-remove only the Dev Flow personal-marketplace member;
3. remove the exact active and transaction-owned managed-release entries;
4. remove the active record by generation CAS;
5. remove the stable CLI and MCP dispatchers;
6. remove lifecycle state and the uninstall dispatcher last; and
7. perform no further product mutation after releasing or removing the lifecycle lock.

A rerun after interruption resumes or classifies the uninstall transaction. Changed, unknown, concurrent, linked, reparse, special, or unprovable content is retained and reported. The uninstaller never broadens to recursive deletion merely to finish cleanup.

Controller task data, its model namespace, unrelated marketplace members, unrelated plugin state, unrelated launchers, standalone MCP registrations, and every source checkout are always outside the removal set. A temporary helper that cannot delete itself is reported by exact path; product-owned state that remains prevents a complete uninstall claim.

### Bound legacy migration to one known predecessor

Migration supports only the conforming checkout-based installer represented by the implementation baseline for this change. The implementation freezes its accepted plugin observations, managed launcher markers, runtime receipt schema, ownership schema, marketplace shape, and transaction outcomes as explicit legacy fixtures. Older, future, malformed, or ambiguous layouts are not adopted automatically.

The artifact installer classifies previous authority only from those installed observations. It does not read, execute, fetch, fast-forward, clean, seal, or delete a source checkout. The checkout path is never used as rollback input.

A migration candidate is built and staged under the normal artifact contract. Failure before provisional external effects leaves the previous installation unchanged. Failure after provisional effects restores and revalidates the previous installed authority or records `partial` if exact restoration cannot be proven. Successful migration commits the artifact release and stable lifecycle infrastructure; the old checkout remains external user-owned content for manual disposition.

`DEV_FLOW_SOURCE_ROOT` and checkout-driven lifecycle invocation fail before mutation with explicit artifact-migration guidance.

### Use layered evidence instead of a Cartesian test matrix

State-machine and verifier behavior is tested at the lowest practical layer:

- shared unit tests cover strict schemas, digest and inventory checks, portable paths, tar member rejection, resource bounds, active generation CAS, transaction outcomes, exact ownership, and compare-and-remove behavior;
- simulated integration tests cover managed-runtime construction, fake Codex observations, repair, upgrade, rollback, recovery, migration, and uninstall without repeating every input across every platform;
- native macOS and native Windows each run one full final-artifact lifecycle with fresh install, healthy and drift repair, successful upgrade, one failed activation rollback, one interrupted transaction recovery, startup, migration, and uninstall;
- the supported Python-version matrix runs lightweight wheel-only dependency installation and import/MCP smoke checks rather than the complete lifecycle matrix;
- release-candidate evidence uses a real Codex host for plugin read-back, bundled Skill discovery, STDIO MCP startup, and uninstall; ordinary pull requests may use deterministic fakes;
- concurrency evidence covers the two authority-relevant pairs: upgrade versus upgrade and upgrade versus uninstall.

Static or simulated PowerShell checks never count as native Windows verification. A platform is reported as unverified when native evidence is unavailable.

## Risks / Trade-offs

- **The GitHub release account remains part of the trust root** -> The bootstrap pins the index digest and all content is digest-bound, but the documentation makes no independent-signature or historical-immutability claim.
- **Stable dispatchers add a small permanent protocol boundary** -> They substantially reduce multi-file rollback complexity. Dispatcher protocol changes require a separate, explicitly transactional migration rather than routine per-release replacement.
- **The active record is briefly committed before real public startup proof** -> The lifecycle lock remains held, the proof runs immediately, and failure CAS-restores and revalidates the previous authority. Candidate-specific health has already passed before this point.
- **Wheel-only dependencies may exclude a dependency without supported wheels** -> Release validation fails rather than executing an end-user sdist build. Supporting such a dependency requires a separate packaging decision.
- **Only the immediate predecessor is migrated** -> This keeps migration bounded and testable. Older installations require the documented intermediate upgrade or manual recovery path.
- **No public manual rollback remains after a successful upgrade** -> Automatic failed-activation rollback is reliable and bounded. Historical rollback and retention policy are separate product features.
- **Native Windows behavior cannot be inferred from macOS or static PowerShell** -> Windows remains unverified until the final artifact passes the native Windows gate.

## Migration Plan

1. Add the release schemas, portable path contract, pinned builder, fixture artifact, and Phase A verifier while the checkout installer remains the production path.
2. Adapt managed-runtime construction, receipts, stable dispatchers, active generation, lifecycle lock, and transaction recovery to consume the verified artifact layout.
3. Implement the macOS bootstrap and source-independent uninstall, then pass the bounded native macOS lifecycle gate.
4. Implement the equivalent native Windows path and pass the bounded native Windows lifecycle gate.
5. Enable migration only for the frozen immediate-predecessor legacy fixtures.
6. Update English source documentation and corresponding Simplified Chinese translations, removing Git and checkout-based product instructions.
7. Build one release candidate in the pinned environment, validate the final version-specific assets after re-download, run real Codex host evidence, and record all limitations.
8. Mark this change complete only when every requirement and completion gate is satisfied. Any signing, automatic update, arbitrary historical rollback, broader migration, or archive-path expansion starts a separate OpenSpec change.

## Open Questions

No implementation-blocking questions remain. Expanding any explicit non-goal requires a separate change rather than extending this implementation implicitly.
