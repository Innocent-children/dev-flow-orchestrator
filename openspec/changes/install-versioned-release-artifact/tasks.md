## 1. Close the Release Artifact Contract

- [ ] 1.1 Define closed standard-library models for `dev-flow-release-index/1.0.0` and `dev-flow-release-artifact/1.0.0`, including strict JSON parsing, raw-manifest digest semantics, manifest self-exclusion, file-versus-directory entry fields, fixed hard caps, and rejection of unknown fields and duplicate keys.
- [ ] 1.2 Define and enforce the exact top-level artifact layout, one pure-Python project wheel, bundled `.codex-plugin/plugin.json`, `.mcp.json`, `skills/dev-flow/**`, `runtime-requirements.txt`, `uv.lock`, and versioned `lifecycle/**` helpers.
- [ ] 1.3 Implement the portable ASCII member-path contract, ASCII case-collision key, Windows device-name rejection, fixed mode profile, supported tar profile, and no-link/no-special-member policy in both release production and the shared verifier.
- [ ] 1.4 Pin the release-builder environment and implement deterministic assembly from an exact clean `vMAJOR.MINOR.PATCH` tag, wheel-only hash-locked dependency export, closed payload allow-list, known-secret/local-path checks, and double-build comparison inside that pinned environment.
- [ ] 1.5 Implement explicit release promotion that builds all four assets before upload, refuses same-version overwrite, re-downloads the final version-specific assets, and records index, archive, manifest, wheel, requirements, lock, plugin, lifecycle, and bootstrap digests.

## 2. Implement the Two-Phase Verification Boundary

- [ ] 2.1 Generate version-matched `install.sh` and `install.ps1` bootstraps containing the exact repository, product version, archive filename, and expected raw `release-index.json` SHA-256, with no production alternate-origin option.
- [ ] 2.2 Embed one byte-identical standard-library Phase A verifier in both bootstraps and make it verify the index digest before parsing, enforce fixed streaming limits, verify the archive before extraction, inspect all headers and paths, extract exclusively without following links or reparse ancestors, verify the manifest and complete inventory, and perform static package-topology checks before artifact code executes.
- [ ] 2.3 Separate Phase B semantic validation from Phase A so artifact lifecycle helpers, project imports, subprocesses, dependency installation, and candidate-runtime construction cannot run until Phase A has completed successfully.
- [ ] 2.4 Force candidate dependency installation to use exact hashes and wheels only, validate the supplied project wheel without building source, and retain the existing installed Skill and STDIO MCP health checks.
- [ ] 2.5 Bound and clean acquisition and extraction staging after every handled outcome, reporting exact retained paths without adopting them as installed or rollback authority.

## 3. Reduce Lifecycle Authority and Serialize Mutation

- [ ] 3.1 Define the closed runtime-receipt schema for the complete artifact and installed identity, and define the smaller active-record schema containing only generation, release ID, contained release path, receipt digest, dispatcher protocol, and committing transaction ID.
- [ ] 3.2 Install stable product-owned `dev-flow`, `dev-flow-mcp`, and `dev-flow-uninstall` dispatchers that are reused across ordinary releases; move versioned runtime verification and lifecycle entry points into each managed release.
- [ ] 3.3 Implement one installation-wide lifecycle lock acquired before reading active or transaction state, plus bounded transaction journals and generation-and-record-digest CAS for active creation, replacement, restoration, and removal.
- [ ] 3.4 Implement candidate-specific staged health, provisional marketplace and Codex plugin activation with read-back, active-record CAS, real public CLI/MCP post-commit proof, and exact compensating restoration to `committed`, `rolled_back`, or `partial`.
- [ ] 3.5 Implement interrupted-transaction recovery before any new lifecycle mutation and stop with `partial` when requested or previous authority cannot be proven exactly; do not add indefinite retry or broad cleanup.
- [ ] 3.6 Reject same-version repair when the newly downloaded index, archive, or manifest digest differs from the active receipt instead of silently adopting replaced bytes.

## 4. Implement the Bounded Product Lifecycle

- [ ] 4.1 Replace Git acquisition in `scripts/install.sh` with exact-version artifact acquisition and implement fresh install, healthy reuse, drift rebuild, target-version upgrade, automatic immediate-previous rollback, and recovery through the shared lifecycle state machine.
- [ ] 4.2 Implement the equivalent native PowerShell lifecycle in `scripts/install.ps1` without POSIX dependencies, preserving the same lock, generation, transaction, Phase A, Phase B, activation, rollback, and terminal-outcome contract.
- [ ] 4.3 Freeze fixtures for the immediately preceding conforming checkout installer and implement migration using only installed plugin, launcher, receipt, marketplace, ownership, and transaction observations; reject older, future, or ambiguous layouts before identity-specific mutation.
- [ ] 4.4 Reject `DEV_FLOW_SOURCE_ROOT` and checkout-driven lifecycle invocation before mutation, and never read, execute, update, or delete a legacy checkout during install, migration, rollback, or uninstall.
- [ ] 4.5 Implement source-independent uninstall with the stable minimal removal driver, uninstall transaction, exact compare-and-remove behavior, active-generation CAS, resumable interruption handling, stable dispatcher removal after runtime authority, and lifecycle support removal last.
- [ ] 4.6 Preserve Controller task data, unknown or changed content, unrelated marketplace and plugin state, unrelated launchers, standalone MCP registrations, and every legacy checkout; report exact retained paths and truthful terminal outcomes.

## 5. Add Focused Automated Evidence

- [ ] 5.1 Add shared verifier unit tests for strict JSON, index-before-parse digest verification, manifest self-exclusion, missing and extra inventory, digest mismatch, fixed hard caps, portable paths, case collisions, Windows device names, links, sparse and special entries, unsupported tar headers, reparse ancestors, and exclusive extraction.
- [ ] 5.2 Add release-builder and package-validator tests for exact layout, one pure-Python wheel, bundled Skill/MCP/plugin topology, wheel-only locked dependencies, version disagreement, source-provenance assertion mismatch, closed input allow-list, known-secret/local-path findings, and deterministic double-build output in the pinned builder environment.
- [ ] 5.3 Add lifecycle state-machine tests for lock acquisition before observation, generation CAS, stale transaction rejection, `A -> B -> A` protection, staged health, failure before provisional effects, failure after host effects, failure after active commit, exact rollback, `partial`, and interrupted-transaction recovery.
- [ ] 5.4 Add only the two authority-relevant concurrency tests: upgrade versus upgrade and upgrade versus uninstall.
- [ ] 5.5 Rewrite uninstall tests around the durable uninstall journal and cover exact removal, interruption and rerun, unknown-content preservation, task-data preservation, unrelated-state preservation, legacy-checkout non-ownership, and no mutation after lifecycle-lock removal.
- [ ] 5.6 Keep ordinary pull-request integration deterministic with fake Codex observations; do not require a real Codex host or full lifecycle matrix on every Python minor.

## 6. Obtain Native Platform and Release-Candidate Evidence

- [ ] 6.1 On a clean isolated macOS profile and one supported Python version, install from the final archive without Git, prove bundled Skill and STDIO MCP startup, run healthy and drift repair, complete one successful upgrade, force one failed activation rollback, recover one interrupted transaction, migrate the frozen predecessor, and uninstall while preserving task data and legacy checkout content.
- [ ] 6.2 Run the same bounded final-artifact lifecycle on a native supported Windows host, including native path roots with spaces, apostrophes, and Unicode, plus native reparse and locked-file behavior; static or simulated PowerShell evidence remains non-native.
- [ ] 6.3 Across every supported Python minor on macOS and Windows, run lightweight wheel-only dependency installation and project import or STDIO MCP smoke checks instead of duplicating the full lifecycle and failure matrix.
- [ ] 6.4 For the release candidate only, use a real Codex host to read back the exact managed plugin root, discover the bundled `dev-flow` Skill, start `dev-flow-mcp --stdio`, and complete uninstall.
- [ ] 6.5 Verify the final promotion assets after re-download from their exact version-specific official locators and record all failures, skips, retained paths, degradations, and platform limitations truthfully.

## 7. Documentation and Completion Gate

- [ ] 7.1 Update the applicable English source documents, including `README.md`, `INSTALL.md`, `ARCHITECTURE.md`, and release-promotion guidance, with artifact prerequisites, exact-version install/repair/upgrade interfaces, trust and SHA-256 boundaries, stable dispatchers, durable paths, terminal outcomes, migration scope, uninstall, and task-data preservation.
- [ ] 7.2 Synchronize every affected public change into the corresponding Simplified Chinese document with identical commands, paths, versions, links, scope, and safety constraints.
- [ ] 7.3 Remove supported-product claims requiring Git, `DEV_FLOW_SOURCE_ROOT`, a retained checkout, source-driven repair, repository-invoked uninstall, independent signing, or public arbitrary-history rollback.
- [ ] 7.4 Run focused tests, complete unittest discovery, package validation, pinned-environment deterministic build comparison, strict OpenSpec validation, and repository-defined release checks through the project `uv` environment.
- [ ] 7.5 Mark this change complete only after Sections 1 through 7 pass for the final artifact, both native platform gates are available, every lifecycle result is classifiable as `committed`, `rolled_back`, or `partial`, and all evidence limitations are recorded.
- [ ] 7.6 Open a separate OpenSpec change rather than extending this implementation when work requires signing, offline fresh install, automatic update channels, arbitrary historical rollback, broader legacy migration, general Unicode archive members, or a dispatcher-protocol migration.
