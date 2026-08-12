## 1. Release Artifact Contract and Builder

- [ ] 1.1 Define closed standard-library models and validators for `dev-flow-release-index/1.0.0` and `dev-flow-release-artifact/1.0.0`, including canonical paths, size limits, component identities, complete inventory, and digest rules.
- [ ] 1.2 Add a deterministic release builder that validates an exact clean tagged commit, builds the pure-Python wheel, exports hash-locked runtime requirements, assembles the complete plugin and lifecycle payload, and emits the normalized `tar.gz`, embedded manifest, and external release index.
- [ ] 1.3 Extend package validation to require version agreement, exact bundled Skill/MCP/plugin topology, one wheel, locked requirements, lifecycle helpers, deterministic metadata, and the absence of secrets, personal paths, undeclared members, and unsafe archive entry types.
- [ ] 1.4 Integrate the version-matched archive, index, `install.sh`, and `install.ps1` into release promotion tooling, recording their digests while keeping actual publication an explicit release operation.

## 2. Verified Acquisition and Managed Runtime

- [ ] 2.1 Implement one shared standard-library acquisition verifier for both bootstraps that validates the canonical versioned HTTPS locator, closed index, size bounds, archive digest, all headers and normalized paths, safe extraction, embedded-manifest digest, and complete extracted inventory before artifact code executes.
- [ ] 2.2 Change managed-runtime construction to consume a verified artifact root, install supplied hash-locked requirements and the prebuilt wheel, copy the sealed plugin tree, and preserve the existing installed Skill/MCP smoke checks and atomic release promotion.
- [ ] 2.3 Extend runtime receipts, active installation records, ownership manifests, and verification to bind index, archive, embedded manifest, source provenance, wheel, requirements, plugin, installed distributions, Python, lifecycle helpers, launchers, transaction, and release path.
- [ ] 2.4 Update CLI and MCP startup launchers to fail closed through the extended receipt and installed-content attestation before importing Dev Flow project code.

## 3. macOS Artifact Lifecycle

- [ ] 3.1 Replace Git clone, fetch, branch, checkout, and source-inventory handling in `scripts/install.sh` with exact-version artifact acquisition in bounded temporary staging and remove Git from installer prerequisites.
- [ ] 3.2 Preserve standalone-registration conflict checks, marketplace compare-and-replace, plugin read-back, bundled Skill/MCP health, launcher ownership, transaction commit, and compensating rollback while ensuring every installed path resolves to the managed release.
- [ ] 3.3 Implement exact-version reuse, drift-triggered repair, verified-version upgrade, and offline rollback from the retained previous managed runtime without consulting a checkout.
- [ ] 3.4 Add transactional migration of conforming checkout-based installations and reject `DEV_FLOW_SOURCE_ROOT` or checkout-driven lifecycle invocation before mutation with explicit artifact-migration guidance.
- [ ] 3.5 Remove acquisition staging after every handled outcome and report any retained temporary path or uncertain external effect truthfully.

## 4. Native Windows Artifact Lifecycle

- [ ] 4.1 Replace Git checkout handling in `scripts/install.ps1` with the same exact-version index, archive, and inventory verification contract using native PowerShell download orchestration and supported Python validation.
- [ ] 4.2 Port managed activation, repair, upgrade, previous-runtime rollback, lifecycle replacement, migration, temporary cleanup, and partial-result semantics without POSIX dependencies.
- [ ] 4.3 Validate Windows path case-folding, reserved names, reparse points, long paths, spaces, Unicode, apostrophes, launcher replacement, and process-lock cleanup against the shared artifact identity.

## 5. Source-Independent Uninstall

- [ ] 5.1 Install an owned lifecycle support directory and `dev-flow-uninstall` launcher whose exact digests participate in active-record commit, repair, upgrade, and rollback.
- [ ] 5.2 Rework the macOS uninstaller to verify and copy its minimal helper into bounded temporary storage, remove only exact owned entries and empty owned directories, remove lifecycle support last, and complete without repository files.
- [ ] 5.3 Implement equivalent Windows temporary-helper and final self-cleanup behavior while preserving unknown, changed, concurrent, linked, reparse, special, or unprovable content.
- [ ] 5.4 Preserve Controller task data, unrelated marketplace and plugin entries, unrelated launchers, standalone MCP registrations, and every legacy checkout; report precise retained paths and partial outcomes.

## 6. Automated and Platform Evidence

- [ ] 6.1 Add release-builder and package-validator tests for reproducibility, version disagreement, wrong source provenance, archive or manifest digest mismatch, missing and extra members, size overflow, path traversal, duplicates, case collisions, links, special files, and credential or local-path leakage.
- [ ] 6.2 Rewrite macOS installer fixtures around versioned artifact downloads and cover fresh install without Git, exact reuse, drift repair, candidate-build failure, activation rollback, uncertain read-back, temporary cleanup, and checkout-based migration.
- [ ] 6.3 Extend managed-runtime, runtime-integrity, package, and installed-journey tests to prove one artifact identity across the wheel, dependencies, plugin, Skill, MCP registration, receipt, launchers, lifecycle helper, marketplace, startup, and rollback.
- [ ] 6.4 Rewrite uninstall tests to begin with no checkout and cover complete removal, helper self-removal, unknown-content preservation, task-data preservation, unrelated-state preservation, and legacy-checkout non-ownership.
- [ ] 6.5 Add PowerShell/static fixtures for the shared release contract and run equivalent fresh install, repair, failed upgrade rollback, launch, migration, and uninstall journeys on a native supported Windows host.

## 7. Documentation and Compatibility Guidance

- [ ] 7.1 Update the applicable English source documents, including `README.md`, `INSTALL.md`, `ARCHITECTURE.md`, and release-promotion guidance, with artifact prerequisites, commands, version selection, durable paths, trust and integrity boundaries, lifecycle behavior, migration, uninstall, and evidence limitations.
- [ ] 7.2 Translate and synchronize every affected public-document change into the corresponding Simplified Chinese document with identical product scope, commands, paths, versions, links, and safety constraints.
- [ ] 7.3 Remove supported-product claims that require Git, `DEV_FLOW_SOURCE_ROOT`, a retained checkout, source-based repair, or checkout-invoked uninstall, and document manual disposition of legacy checkouts without claiming product ownership.

## 8. Release Verification

- [ ] 8.1 Run focused release, installer, runtime, integrity, migration, uninstall, package, and installed-journey tests through the project `uv` environment.
- [ ] 8.2 Run complete unittest discovery, package validation, deterministic double-build comparison, strict OpenSpec validation, and all repository-defined release checks; record every failure, skip, degradation, and platform limitation truthfully.
- [ ] 8.3 Install the candidate from its final archive into an isolated clean macOS profile without Git, exercise Skill and MCP discovery plus repair, failed-upgrade rollback, startup, and uninstall, and verify that no checkout or acquisition staging remains.
- [ ] 8.4 Obtain native Windows evidence for the same final artifact lifecycle before marking Windows verified; static or simulated PowerShell results remain explicitly non-native evidence.
- [ ] 8.5 Verify the final promotion assets from their version-specific official release locators and record index, archive, manifest, wheel, requirements, plugin, and bootstrap digests without publishing or changing external state as part of ordinary implementation verification.
