## Context

The current installer treats a clean checkout of the authoritative `main` branch as its acquisition, provenance, upgrade, and uninstall anchor. It exports a verified Git tree, creates a sealed plugin copy, builds a wheel and isolated environment, activates the plugin from the managed runtime, and retains the checkout for later repair and uninstall.

The installed topology is already largely source-independent. The personal marketplace points to a release-specific plugin copy under the managed runtime, the MCP launcher uses the runtime virtual environment, and receipts and ownership manifests bind installed files, dependencies, Python identity, launchers, and plugin content. The checkout remains because the lifecycle scripts reacquire and reseal source for every install and because uninstall loads its ownership helper from that checkout.

This change replaces the acquisition boundary while preserving the managed-runtime, activation, rollback, and exact-ownership foundations. Release production may use Git; end-user installation may not require or retain it. The artifact must carry the bundled Codex plugin assets in addition to the Python wheel because the Skill and `.mcp.json` registration are not wheel-only resources.

## Goals / Non-Goals

**Goals:**

- Install, repair, upgrade, roll back, and uninstall from a versioned release artifact with no persistent source checkout.
- Verify the selected official release and all extracted content before executing artifact-provided code or mutating installed state.
- Keep the installed plugin, Skill, MCP registration, runtime, launcher, receipt, and rollback identity on one release boundary.
- Preserve existing task data, Controller authority, MCP contracts, and unrelated Codex configuration.
- Provide a bounded migration from an existing checkout-based installation.
- Apply the same product contract to macOS and native Windows, with platform evidence reported independently.

**Non-Goals:**

- Produce a single native executable or remove the supported Python and `uv` prerequisites.
- Add remote MCP transport, standalone MCP registration, automatic branch or worktree management, external CI dispatch, or publication behavior to the runtime product.
- Change the Controller model, workflow catalog, MCP tool names or schemas, task-data namespace, plugin ID, or personal-marketplace mode.
- Delete a pre-existing source checkout during migration or uninstall.
- Add offline installation, third-party mirrors, release signing, transparency-log verification, or automatic pruning of retained rollback releases in the first delivery.

## Decisions

### Publish one platform-neutral release bundle and external release index

Each product version will publish these immutable GitHub Release assets:

- `dev-flow-orchestrator-<version>.tar.gz`;
- `release-index.json`;
- version-matched `install.sh` and `install.ps1` bootstraps.

The archive will contain a single top-level directory and only regular files and directories. It will preserve declared executable modes and reject symbolic links, hard links, devices, FIFOs, duplicate normalized paths, absolute paths, parent traversal, case-folding collisions, and entries outside that root. A single `tar.gz` keeps the release identity identical across supported platforms; supported Python provides the same bounded validation and extraction semantics on macOS and Windows.

`release-index.json` will use a closed `dev-flow-release-index/1.0.0` schema and bind the product version, exact official repository, source commit and tree, archive filename and SHA-256, archive size limit, and the SHA-256 of the embedded release manifest. The archive's `release-manifest.json` will use a closed `dev-flow-release-artifact/1.0.0` schema and inventory every payload member by normalized relative path, type, mode, size, and SHA-256. The index pins the archive; the archive manifest pins the extracted payload without a self-referential archive digest.

A ZIP-only bundle was not selected because executable-mode handling differs across the supported hosts. Per-platform bundles were not selected because the runtime and plugin payload are platform-neutral and duplicate release identities would complicate parity and rollback.

### Package installation-ready components

The archive will contain:

- the complete sealed Codex plugin tree, including `.codex-plugin/plugin.json`, `.mcp.json`, `skills/dev-flow/**`, and the plugin-side CLI and installed-validation assets;
- one prebuilt pure-Python project wheel;
- `runtime-requirements.txt` with exact versions and hashes exported from the locked dependency graph, plus the lock digest used to produce it;
- standard-library lifecycle and integrity helpers required for staging, receipt validation, repair, rollback, and uninstall;
- the embedded release manifest.

Release validation will require product version agreement across the release index, plugin manifest, wheel metadata, and project release metadata. It will also prove that the bundled Skill and MCP catalog are the expected package contents. The end-user installer will create the isolated virtual environment and install the hash-locked dependencies and wheel, but it will not build the project wheel from source.

Publishing a wheel by itself was not selected because it cannot represent the complete Codex plugin tree or lifecycle bootstrap. Shipping a self-contained native binary was deferred because it creates separate platform build and signing pipelines without being necessary to remove the checkout.

### Trust an exact official release locator and verify content in two stages

The public bootstrap will carry its release version and accept only the canonical HTTPS GitHub Release path for the configured repository and that exact version. The `latest` download route may select a version-matched bootstrap, after which all remaining URLs are version-specific. Redirects must remain HTTPS and the requested asset names must remain exact.

The bootstrap will download the index and archive into a newly created installer-owned temporary directory. Its built-in verifier will:

1. validate the closed index and expected version/source identity;
2. enforce download and declared-size bounds;
3. verify the archive SHA-256 before extraction;
4. inspect all archive headers and normalized names before writing members;
5. extract without following links or overwriting pre-existing paths;
6. verify the embedded manifest digest and complete extracted inventory;
7. run package validation before any real runtime, launcher, marketplace, plugin, or lifecycle mutation.

Only after these checks may the installer execute helpers from the verified artifact. Temporary download and extraction paths never become marketplace, launcher, receipt, or runtime authorities and are removed after success or failure.

The first version uses the canonical GitHub HTTPS release origin as the publication authority and SHA-256 as its content-integrity mechanism. Independent signing and transparency attestations remain compatible future hardening because the index is the single trust-input envelope.

### Reuse the managed-runtime transaction with artifact identity

The verified artifact root replaces the sealed Git-export root as the input to managed-runtime construction. The runtime builder will copy the verified plugin tree, install the supplied requirements and wheel, run the existing installed MCP and Skill checks, generate launchers, and publish a content-addressed release directory atomically.

The release ID will remain derived from immutable installed content and source provenance. Runtime receipts and the active installation record will additionally bind the release-index digest, archive digest, release-manifest digest, project wheel digest, requirements digest, plugin-release digest, source commit and tree, and lifecycle-helper digest. Normal MCP startup will continue to verify the runtime receipt and installed distribution before importing candidate code.

The marketplace source will continue to name the release-specific managed plugin root. It must never name the bootstrap, download cache, extraction staging, a source checkout, or a mutable shared directory. Bundled `dev-flow-mcp --stdio` registration and Skill discovery remain part of the installed health gate.

### Preserve the previous verified runtime for upgrade and rollback

Repairing the exact active release may reuse it only after complete receipt and startup attestation. Any mismatch causes a fresh candidate to be built from a newly verified artifact.

An upgrade will fully acquire, verify, build, and smoke-test the candidate before changing the active plugin, launchers, lifecycle bootstrap, or marketplace member. The previous conforming runtime and its receipt provide all rollback input; rollback does not reacquire a prior artifact or consult a checkout. Activation success requires host read-back of the managed plugin root, bundled MCP registration, Skill metadata, and installed health. A failure after provisional effects restores and revalidates the previous release. If exact active identity cannot be proven, the transaction records `partial`, preserves all uncertain content, and gives bounded recovery guidance.

### Install a source-independent lifecycle bootstrap

The installer will publish an owned lifecycle support directory under the managed product root and a `dev-flow-uninstall` command in the selected writable `PATH` directory. The active record will bind the lifecycle helper and launcher digests. Upgrade and rollback replace or restore these files within the same activation transaction.

For uninstall, the launcher will verify the active record and lifecycle helper, copy the minimal standard-library uninstaller to a bounded temporary directory, verify the copy, and execute it with a supported system Python. The temporary helper can remove the runtime and lifecycle support after the managed runtime is no longer executing. Platform-specific final launcher removal must use a contained self-cleanup mechanism and report any retained file rather than broadening deletion.

Uninstall will remove only exact ownership-manifest entries and empty owned directories. Changed, unknown, concurrent, symlinked, reparse, or special content is retained and reported. Controller task data, unrelated marketplace members, unrelated plugin state, and standalone MCP registrations remain outside the removal set.

### Migrate legacy installations without adopting or deleting their checkout

The artifact installer will recognize an existing Dev Flow installation only through current plugin observations, managed launcher markers, runtime receipts, marketplace state, and transaction records. It will not read, fetch, fast-forward, clean, or otherwise use a source checkout.

A conforming legacy runtime may serve as the previous release during the activation transaction. The new artifact release becomes authoritative only after full candidate health and active-record commit. If migration fails, the legacy installation and its existing checkout remain unchanged. After successful migration, the new lifecycle bootstrap handles repair and uninstall; any old checkout is external user-owned content and may be reported as a manual cleanup candidate, but the product never deletes it.

`DEV_FLOW_SOURCE_ROOT` and checkout-based lifecycle commands will fail with explicit migration guidance so an operator cannot accidentally believe that local source affected the selected release.

### Keep release production separate from end-user installation

Release automation will build from an exact clean tagged Git commit, export the locked requirements, build the wheel, assemble the plugin and lifecycle payload, generate both manifests, validate the final archive, and publish all version-matched assets together. Publication evidence will record artifact and manifest digests. Git remains a release-engineering dependency only.

Package validation and release tests will reproduce archive construction twice and require identical logical manifests and payload digests. Compressed archive byte-for-byte reproducibility is required after normalizing timestamps, ownership, ordering, modes, and gzip headers.

## Risks / Trade-offs

- **The official release account can replace both index and artifact** → Pin every lifecycle operation to a version-specific official path and closed digest envelope; keep independent signing as a compatible hardening step and make no stronger authenticity claim in this release.
- **Bootstrap verification logic diverges between shell and PowerShell** → Put schema, archive, and inventory validation in one standard-library Python helper embedded identically in both bootstraps, with only download and process-launch code remaining platform-specific.
- **A source-free uninstaller can delete its own verifier too early** → Verify and copy the minimal helper to bounded temporary storage before mutation, remove owned lifecycle support last, and report partial cleanup truthfully on platform-specific retention.
- **Legacy state may be ambiguous** → Accept only receipts, markers, and host read-back that prove one previous authority; preserve ambiguous content and fail before identity-specific mutation.
- **Retained previous runtimes consume disk** → Retain the current previous verified release for rollback; automated pruning is outside this delivery and can be specified later with an ownership-safe retention policy.
- **Native Windows behavior cannot be proven on the development macOS host** → Require native Windows install, upgrade-failure rollback, launch, and uninstall evidence before claiming Windows release verification.

## Migration Plan

1. Add release schemas, deterministic bundle construction, validators, and fixture artifacts while the checkout installer remains the active production path.
2. Adapt managed-runtime construction and receipts to accept the verified artifact layout and bind artifact provenance.
3. Implement the macOS bootstrap and lifecycle command, then prove fresh install, repair, upgrade, rollback, and uninstall in isolated profiles.
4. Implement the equivalent native PowerShell path and obtain native Windows evidence.
5. Enable artifact-based migration for existing installations; keep activation transactional so failure leaves the prior installation usable.
6. Switch public installation and repair documentation to versioned artifact commands and remove Git and source-root prerequisites. Update English source documents before synchronizing Simplified Chinese translations.
7. Publish one release candidate, verify its published index and archive from a clean environment, and retain the prior verified product release as the rollback target.

Rollback of the product rollout uses the prior published bootstrap and retained managed runtime. The installer never attempts to reconstruct rollback state from a source checkout.

## Open Questions

None.
