## Why

Dev Flow Orchestrator currently clones and permanently retains its Git repository even though Codex runs a separately sealed plugin and managed Python runtime after installation. A versioned release artifact can provide the same verified plugin, Skill, MCP, and lifecycle contents while removing Git checkout state from the installed product.

## What Changes

- Publish one immutable, versioned release artifact containing the complete Codex plugin tree, the prebuilt project wheel, hash-locked runtime requirements, lifecycle helpers, and a closed release manifest.
- Make the macOS and Windows bootstrap installers download the selected official release into bounded temporary staging, verify its locator, version, archive digest, manifest, and complete member inventory before executing artifact code, and leave no persistent download or source checkout.
- Build, activate, repair, upgrade, and roll back through the existing versioned managed-runtime transaction, with the release artifact identity added to runtime receipts, launch attestation, and ownership evidence.
- Install a small owned lifecycle bootstrap so repair and uninstall remain available after temporary artifact staging is removed. Uninstall removes only receipt-bound product content and preserves task data and unrelated Codex state.
- Migrate checkout-based installations by activating a verified artifact release and ceasing all dependence on the legacy checkout. Any pre-existing checkout remains external user-owned content and is reported for manual disposition.
- Preserve the bundled `dev-flow` Skill, `.mcp.json` STDIO registration, MCP tools and schemas, Controller model, task data namespace, plugin ID, and personal-marketplace mode.
- **BREAKING**: Git checkout installation, `DEV_FLOW_SOURCE_ROOT`, checkout-driven upgrade/repair, and invoking uninstall from the retained repository stop being supported product interfaces.

## Capabilities

### New Capabilities

- `versioned-release-artifact-installation`: Build, acquire, verify, activate, upgrade, roll back, attest, and uninstall a complete Dev Flow release artifact without a persistent Git checkout.

### Modified Capabilities

None.

## Impact

The implementation phase will affect release packaging, macOS and Windows installers and uninstallers, managed-runtime construction, runtime receipts and integrity verification, launcher installation, package validation, lifecycle and installed-journey tests, and synchronized English and Simplified Chinese documentation. Git is removed from end-user runtime requirements; supported Python and `uv` remain required to construct the isolated managed environment. No Controller, MCP protocol, workflow, task-state, repository-membership, authorization, or task-data migration is introduced.
