# Change: Introduce an MCP-first runtime

## Why

Dev Flow currently reaches Codex through a large packaged Skill plus SessionStart,
UserPromptSubmit, and PreToolUse Hooks. That interface works, but it makes the host
model repeatedly consume procedural guidance, reconstruct shell commands, and in
some sessions inspect plugin source to understand how to invoke the Controller.
The result is avoidable context cost, slower task startup, and a Codex-specific
interaction boundary around an otherwise well-separated Controller and workflow
engine.

The product already has the right internal seam for MCP: CLI, Hook, and Web UI are
adapters over one Controller, while the Controller remains the sole task-state
writer. This change replaces the installed Skill-and-Hook interaction path with a
local STDIO MCP server that exposes typed Controller tools and returns only the
current action's bounded guidance. The plugin remains only as a distribution shell
for Codex; the same server can also be registered directly as a standalone MCP
server.

## User Value

- Codex discovers a small, stable tool catalog instead of reading long Skills or
  plugin source.
- Task operations use typed JSON schemas instead of shell command construction and
  string-escaped JSON arguments.
- Only current-action guidance enters the conversation, reducing unrelated context.
- macOS and Windows use the same MCP tool contracts and the same persisted task
  model.
- Existing `0.4.0` tasks remain resumable because the Controller, state namespace,
  workflows, bindings, records, and Delivery Dossiers do not change.
- CLI and Web UI remain available for recovery, inspection, and operator workflows.

## What Changes

### Installed interaction boundary

- **From:** packaged `follow-dev-flow`, `analyze-change-impact`, and
  `review-dev-flow-change` Skills plus Codex Hooks inject a Controller locator and
  tell Codex to invoke the JSON CLI.
- **To:** a plugin-bundled local STDIO MCP server exposes explicit read and mutation
  tools over the same Controller. Server instructions define only global invariants;
  `dev_flow_get_next_action` returns action-specific guidance on demand.
- **Impact:** breaking for automation or documentation that invokes the packaged
  Skills, parses Hook context, or expects the Hook to guard the Controller data
  directory.

### Plugin packaging

- **From:** `.codex-plugin/plugin.json` points to `skills/`, and Codex discovers the
  default `hooks/hooks.json` file.
- **To:** `.codex-plugin/plugin.json` points `mcpServers` to a root `.mcp.json` file.
  The release package no longer installs Dev Flow Skills or Hooks after MCP parity is
  proven.
- **Impact:** the project is MCP-first while retaining the existing plugin installer,
  marketplace identity, and Codex distribution path.

### MCP tool surface

The first stable interface, `dev-flow-mcp/1.0.0`, adds these tools:

1. `dev_flow_server_info`
2. `dev_flow_list_tasks`
3. `dev_flow_find_tasks_for_path`
4. `dev_flow_get_task`
5. `dev_flow_get_next_action`
6. `dev_flow_start_task`
7. `dev_flow_apply_action`
8. `dev_flow_revise_contract`
9. `dev_flow_record_decision`
10. `dev_flow_dispose_finding`
11. `dev_flow_cancel_task`

The server SHALL NOT expose a generic CLI passthrough, arbitrary command execution,
raw state-file access, branch/worktree creation, Git publication, external CI/PR
operations, or a tool that bypasses Controller validation.

### Guidance and context

- Global instructions become a short server initialization string whose first 512
  characters contain the complete authority and sequencing rule.
- Current-action guidance is generated from the live Controller projection and a
  versioned package guidance catalog.
- List and inspection tools return bounded summaries; no tool returns raw Controller
  files or complete history by default.
- Normal installed journeys must complete without reading `skills/`, `hooks/`, CLI
  source, MCP adapter source, or task-state files.

### Runtime and dependency boundary

- The target release is `0.5.0`; `MODEL_VERSION` remains `0.4.0`.
- Supported installed runtimes move from CPython 3.9–3.14 to CPython 3.10–3.14
  because the official MCP Python SDK v2 requires Python 3.10 or newer.
- Controller, Engine, Store, workflow, delivery, snapshot, review, and Git-domain
  code remain independent of the MCP SDK. Only the MCP adapter imports it.
- Installers create or update an isolated, installer-owned MCP runtime outside the
  verified source checkout and outside preserved task data, using locked dependency
  metadata.

### Discovery and trust boundary

- Automatic Hook injection is replaced by `dev_flow_find_tasks_for_path` plus MCP
  server instructions that require discovery before start or resume.
- The old best-effort PreToolUse data-directory guard is removed. The replacement
  boundary is explicit: state remains outside target repositories, no MCP response
  exposes the data root, all writes pass through typed Controller tools, and public
  guidance continues to forbid direct state access.
- Tool annotations and Codex approval policy communicate read-only, additive, and
  destructive behavior. Annotations are guidance, not a security boundary.

### Registration modes

- **Bundled mode:** the Codex plugin loads `.mcp.json` and starts `dev-flow-mcp
  --stdio`.
- **Standalone mode:** an operator may register the same launcher with `codex mcp
  add` for a non-plugin Codex surface.
- The installer SHALL NOT create both registrations and SHALL diagnose an active
  duplicate rather than claim a healthy installation.

## What Does Not Change

- The Controller remains the sole application boundary and task-state writer.
- `MODEL_VERSION`, current schema identifiers, and the `0.4.0` data namespace remain
  unchanged.
- Existing task IDs, immutable repository membership, active leases, revision CAS,
  action bindings, workflow definitions, assurance policies, findings, decisions,
  and Delivery Dossiers retain their current semantics.
- The six official workflows remain `lite`, `feature`, `bugfix`, `investigation`,
  `refactor`, and `full`.
- One task still has one immutable exact repository set, one current action, and one
  executor.
- Users still prepare worktrees. Dev Flow does not create branches/worktrees, publish
  Git changes, run parallel executors, or operate external CI/PR/release systems.
- The strict JSON CLI remains a supported recovery and operator interface.
- The local read-only Web UI remains available and continues to use the Controller.
- Existing source verification, authoritative `main`, fast-forward-only upgrade,
  marketplace isolation, and uninstall data-preservation rules remain in force.
- The first MCP release is local STDIO only. Remote Streamable HTTP, OAuth, hosted
  service operation, server-side sampling, elicitation, MCP task augmentation, and
  cross-machine state are outside this change.

## Capabilities

### New capabilities

- `mcp-server-runtime`: local MCP initialization, transport, lifecycle, dependency,
  logging, cancellation, and error behavior.
- `mcp-controller-tools`: stable typed tools mapped to Controller operations.
- `mcp-guidance-and-context`: bounded global and action-specific guidance with
  context budgets and source-reading independence.
- `mcp-plugin-packaging`: bundled and standalone registration, runtime installation,
  duplicate detection, and uninstallation behavior.

### Modified capabilities

- `personal-delivery-workflows`: the workflow executor follows MCP projections and
  action guidance instead of packaged Skill and Hook instructions.
- `task-discovery-boundaries`: current-task discovery becomes an explicit MCP tool
  contract rather than Hook injection.
- `package-delivery-validation`: package and installed-journey validation prove MCP
  behavior and reject stale Skill/Hook authority.
- `authoritative-plugin-installation`: supported installers provision and validate
  the bundled MCP runtime before activation.
- `native-windows-product-support`: Windows launches the MCP server natively and no
  longer depends on command Hooks.
- `native-windows-runtime`: the supported Python floor becomes 3.10 and the official
  MCP SDK is the sole permitted production dependency outside the core runtime.

## Impact

### Source and package areas

Expected changes include:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `pyproject.toml` and `uv.lock`
- `src/dev_flow_orchestrator/mcp/`
- shared data-directory resolution and bounded inspection APIs
- MCP launchers for POSIX and Windows
- `scripts/install.sh`, `scripts/install.ps1`, uninstallers, package validator, and
  installed smoke scripts
- README, installation, architecture, contribution, promotion, and roadmap documents
- removal of installed `skills/` and `hooks/` assets after parity
- new MCP unit, protocol, package, lifecycle, and installed-journey tests

### Compatibility

- **Persisted model:** compatible; no state migration.
- **CLI:** retained.
- **Web UI:** retained.
- **Skill invocation:** removed in `0.5.0`.
- **Hook context and guard:** removed in `0.5.0`.
- **Python 3.9 installed product:** no longer supported.
- **macOS and Windows x64:** retained, using native STDIO launchers.
- **Standalone MCP clients:** protocol-compatible where they support local STDIO,
  but the public end-to-end delivery claim remains limited to documented Codex
  surfaces with local repository tools.

## Migration

1. Upgrade through the existing authoritative installer.
2. The installer preserves `<current data root>/0.4.0` and provisions the new MCP
   runtime separately.
3. Plugin activation loads the bundled MCP server. No user task migration or export
   is performed.
4. Start a new Codex session and verify the server with the documented MCP status
   command or UI.
5. Existing active tasks are located with `dev_flow_find_tasks_for_path` and resumed
   with `dev_flow_get_next_action`.
6. Remove any manually registered standalone Dev Flow server before enabling bundled
   mode, or disable bundled mode before registering standalone mode.
7. Rollback may reinstall the last `0.4.x` release. Because the task model remains
   `0.4.0`, prior tasks remain readable; work performed through `0.5.0` must still
   obey the existing model schemas.

## Definition of Done

- The installed candidate initializes a local STDIO MCP server and lists exactly the
  approved stable tool catalog.
- Every MCP mutation reaches the existing Controller and preserves current
  validation, snapshot, lease, binding, and revision-CAS behavior.
- All six official workflows complete representative installed journeys through MCP
  without invoking the JSON CLI from the model and without reading plugin source.
- Existing `0.4.0` tasks created by `0.4.x` resume and finalize through MCP with no
  byte migration.
- CLI/MCP parity tests prove equivalent Controller state and domain errors for every
  mapped operation.
- macOS and Windows x64 lifecycle suites validate install, repair, fast-forward
  upgrade, activation failure, duplicate registration, and safe uninstall.
- Package validation rejects stale installed Skills, Hooks, source-reading guidance,
  missing `.mcp.json`, missing launcher/runtime assets, unlocked MCP dependencies,
  schema drift, over-budget metadata, or an untested tool.
- MCP protocol tests cover initialize, instructions, `tools/list`, `tools/call`,
  structured success, domain failure, invalid parameters, cancellation, timeout,
  stdout purity, and restart.
- Public English and Simplified Chinese documentation explains the MCP-first
  architecture, approval boundary, loss of Hook guard behavior, Python 3.10+
  requirement, registration modes, preserved task data, and rollback path.
- `openspec validate dev-flow-orchestrator-mcp --strict` succeeds.
