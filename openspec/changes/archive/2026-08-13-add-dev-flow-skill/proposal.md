## Why

Installing Dev Flow Orchestrator currently exposes the local `dev-flow` MCP but does not package a Codex Skill that teaches the host when and how to use that MCP. A bundled Skill makes explicit `$dev-flow` invocation and description-based implicit routing part of the installed plugin while preserving the Controller as the sole task-state and transition authority.

## What Changes

- Add a focused `dev-flow` Skill with Codex interface metadata and activation/routing guidance.
- Register the plugin's `skills/` directory alongside the existing bundled `.mcp.json` STDIO server.
- Validate the Skill structure, metadata, authority boundary, package topology, and installed copy.
- Extend installed-stage and lifecycle coverage to prove that one installation exposes both the Skill and the existing MCP server.
- Document explicit invocation, implicit matching, installation contents, runtime boundaries, and verification in synchronized English and Simplified Chinese guides.

## Capabilities

### New Capabilities

- `codex-dev-flow-skill`: Package and discover a Codex Skill that selects or resumes a Dev Flow task and follows Controller-issued actions through the existing `dev-flow` MCP.

### Modified Capabilities

None.

## Impact

The change affects the plugin manifest, a new `skills/dev-flow/` package, package and installed-stage validators, managed-runtime and installer acceptance coverage, and public documentation. The `.mcp.json` server identity, MCP tool names, Controller model, persisted state, workflow definitions, transport, and authorization boundaries remain unchanged.
