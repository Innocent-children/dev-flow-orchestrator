## Context

Dev Flow Orchestrator already ships a local `dev-flow` STDIO MCP whose Controller owns task state, repository membership, bindings, transitions, recovery, review, and final delivery evidence. The plugin manifest currently registers only `.mcp.json`, and package validation explicitly excludes Skills. Codex therefore receives controlled tools but no packaged workflow layer for deciding when to use them or how to discover and resume the correct task.

The OpenAI Skill format requires `SKILL.md` with `name` and `description`; `agents/openai.yaml` can add interface metadata, implicit-invocation policy, and MCP dependencies. Current official dependency examples require `streamable_http` plus a URL, while the plugin's server is a bundled local STDIO process.

## Goals / Non-Goals

**Goals:**

- Package one focused `dev-flow` Skill with the existing MCP.
- Support explicit `$dev-flow` and description-based implicit matching.
- Teach Codex to discover, resume, start, and drive one Controller task safely.
- Prove source-package and installed-copy availability of both capabilities.
- Keep English and Simplified Chinese public documentation aligned.

**Non-Goals:**

- Change MCP tool names, transport, schemas, or Controller behavior.
- Define a second workflow protocol, state machine, action catalog, or payload catalog.
- Restore lifecycle Hooks or add a generic shell MCP tool.
- Add remote MCP transport, authentication, branch/worktree management, publication, parallel-agent dispatch, or external CI automation.

## Decisions

### Package the Skill at the plugin root

Create `skills/dev-flow/` with `SKILL.md`, `agents/openai.yaml`, and `references/activation-and-routing.md`; set the manifest `skills` field to `./skills/`. This matches the universal plugin layout and keeps the existing `mcpServers: "./.mcp.json"` registration intact.

An independent user-level Skill was considered but would not prove that one plugin installation supplies both capabilities and would require separate installation state.

### Keep `SKILL.md` concise and defer routing detail

Use frontmatter only for `name` and a trigger-oriented `description`. Keep the core Controller loop in `SKILL.md`; place applicability, repository-scope discovery, selection, start, ambiguity, and uncertain-response handling in `references/activation-and-routing.md`.

Embedding Controller action definitions and payload schemas was considered and rejected because those values are versioned runtime authority returned by `dev_flow_get_next_action`.

### Express Codex UI and invocation policy without a false MCP dependency

Generate `agents/openai.yaml` with `display_name`, a 25–64 character `short_description`, a one-sentence `default_prompt` that names `$dev-flow`, and `policy.allow_implicit_invocation: true`. Omit `dependencies` because the documented dependency form requires a remote streamable HTTP URL and cannot faithfully describe the bundled local STDIO server.

Using a fabricated URL, remote transport, or unsupported dependency field would create incorrect installation metadata. The plugin manifest remains the authoritative local MCP registration.

### Validate closed Skill content and installed coexistence

Extend `scripts/validate_package.py` to require the exact Skill file set, validate frontmatter and `openai.yaml` with the repository's standard-library YAML subset, check manifest linkage and key authority phrases, reject dependency metadata and forbidden workflow duplication, and include Skill files in product topology checks.

Extend installed-stage evidence to resolve the installed manifest's Skill path, validate the installed Skill metadata and file digests, and report a bounded Skill discovery result alongside the existing MCP initialization and catalog evidence. Installer and managed-runtime tests will assert that the sealed installed copy contains both capabilities.

### Preserve installed artifact integrity

Use the existing sealed plugin copy, ownership manifest, managed-runtime receipt, and snapshot checks. Skill files participate in the same release copy and integrity boundary as `.mcp.json`; no parallel installation or mutable external Skill directory is introduced.

## Risks / Trade-offs

- **Implicit invocation remains model-mediated** → Validate trigger metadata and enabled policy with representative positive and negative prompts; do not claim deterministic selection for every paraphrase.
- **Skill guidance can drift toward a second protocol** → Validate that it references Controller-issued action, binding, payload schema, guidance, and recovery instead of embedding catalogs or transition tables.
- **Installed Skill proof can become a source-only assertion** → Run validation against the sealed installed plugin root and include that result in installed-stage evidence together with a live MCP handshake.
- **Windows installation cannot be executed on the current macOS host** → Cover PowerShell packaging paths and installed topology with tests while keeping native Windows acceptance explicitly unverified.

## Migration Plan

1. Add and validate the Skill package and manifest linkage.
2. Extend installed-stage evidence and lifecycle tests.
3. Update English documentation, then synchronize Simplified Chinese translations.
4. Build and install the candidate in an isolated destination; run Skill discovery and MCP initialization checks.
5. Run the complete repository validation suite and strict OpenSpec validation.

Existing installations upgrade through the normal installer repair path. Rollback restores the previously sealed runtime and plugin copy; task data remains in the unchanged model namespace.

## Open Questions

None.
