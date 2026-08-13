## Why

Dev Flow Orchestrator currently clones and permanently retains its Git repository even though Codex runs a separately sealed plugin and managed Python runtime after installation. The checkout remains an acquisition and lifecycle dependency rather than a runtime requirement. A version-addressed release artifact can preserve the existing plugin, Skill, STDIO MCP, managed runtime, rollback, and ownership behavior without retaining source control state on the user's machine.

## What Changes

- Publish one platform-neutral, version-addressed release archive containing the complete Codex plugin tree, one prebuilt pure-Python project wheel, hash-locked runtime requirements, the dependency lock used to produce them, versioned lifecycle helpers, and a closed embedded manifest.
- Generate version-matched macOS and Windows bootstraps that embed the selected version and the expected release-index digest. Each bootstrap downloads only that version's official GitHub Release assets and verifies the index, archive, safe member set, embedded manifest, and complete extracted inventory before executing artifact code or changing installed authority.
- Reuse the existing managed-runtime and exact-ownership foundations, but reduce lifecycle authority to one active record protected by one installation-wide lock, a monotonic generation, and a bounded transaction journal.
- Keep `dev-flow`, `dev-flow-mcp`, and `dev-flow-uninstall` as small stable dispatchers. Versioned runtime and lifecycle implementations live in the active managed release, so ordinary upgrade and automatic rollback do not replace multiple external launcher payloads.
- Support fresh install, exact-version repair, target-version upgrade, automatic rollback of a failed activation, crash recovery, source-independent uninstall, and migration from the immediately preceding conforming checkout-based installation.
- Preserve the bundled `dev-flow` Skill, `.mcp.json` registration for `dev-flow-mcp --stdio`, MCP tools and schemas, plugin ID, personal-marketplace mode, Controller model, and task-data namespace.
- **BREAKING**: Git checkout installation, `DEV_FLOW_SOURCE_ROOT`, checkout-driven repair or upgrade, and repository-invoked uninstall stop being supported product interfaces.

## Completion Target

This change is complete only when one final release artifact can, on both macOS and native Windows:

1. install without Git or a persistent checkout;
2. pass staged Skill and MCP health before activation;
3. repair an intact or drifted exact-version installation;
4. upgrade to a target version and automatically restore the immediate previous authority when activation or post-commit startup proof is forced to fail;
5. recover or stop truthfully after a simulated interrupted lifecycle transaction;
6. uninstall without repository files while preserving Controller task data, unknown content, unrelated Codex state, and every legacy checkout; and
7. finish each lifecycle operation as `committed`, `rolled_back`, or `partial`, with no unclassified success state.

The completion gate does not require independent release signing, offline fresh installation, arbitrary Unicode archive member names, automatic update channels, or user-selectable rollback to arbitrary historical versions. Those capabilities require separate OpenSpec changes.

## Capabilities

### New Capabilities

- `versioned-release-artifact-installation`: Build, acquire, verify, activate, repair, upgrade, automatically roll back failed activation, attest, migrate, and uninstall a complete Dev Flow release artifact without a persistent Git checkout.

### Modified Capabilities

None.

## Impact

Implementation affects release packaging, macOS and Windows installers and uninstallers, managed-runtime construction, runtime receipts and active authority, stable dispatchers, package validation, lifecycle transaction recovery, installed-journey tests, and synchronized English and Simplified Chinese documentation. Git is removed from end-user prerequisites; supported Python, `uv`, Codex, a writable absolute `PATH` directory, and the platform download facility remain required. No Controller, MCP protocol, workflow, task-state, repository-membership, authorization, or task-data migration is introduced.
