# Dev Flow Orchestrator MCP 化 OpenSpec 完整文档

> 本文件是提案评审时生成的合订快照，便于连续阅读，不是当前任务状态或校验证据
> 的权威来源。当前规范和任务状态以同目录下的 `proposal.md`、`design.md`、
> `tasks.md` 与 `specs/` 分文件为准，实际验证结果以 `VALIDATION_REPORT.md` 为准。
> OpenSpec 正式内容保持英文，以与仓库现有规范风格和 Requirement 名称一致。

## 文档目录

1. `openspec/changes/dev-flow-orchestrator-mcp/proposal.md`
2. `openspec/changes/dev-flow-orchestrator-mcp/design.md`
3. `openspec/changes/dev-flow-orchestrator-mcp/tasks.md`
4. `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-server-runtime/spec.md`
5. `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-controller-tools/spec.md`
6. `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-guidance-and-context/spec.md`
7. `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-plugin-packaging/spec.md`
8. `openspec/changes/dev-flow-orchestrator-mcp/specs/personal-delivery-workflows/spec.md`
9. `openspec/changes/dev-flow-orchestrator-mcp/specs/task-discovery-boundaries/spec.md`
10. `openspec/changes/dev-flow-orchestrator-mcp/specs/package-delivery-validation/spec.md`
11. `openspec/changes/dev-flow-orchestrator-mcp/specs/authoritative-plugin-installation/spec.md`
12. `openspec/changes/dev-flow-orchestrator-mcp/specs/native-windows-product-support/spec.md`
13. `openspec/changes/dev-flow-orchestrator-mcp/specs/native-windows-runtime/spec.md`

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/proposal.md`

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

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/design.md`

# Design: MCP-first Dev Flow runtime

## Context

Dev Flow 0.4.2 already separates product authority from presentation adapters:

```text
Codex Skill / Hook / JSON CLI / Web UI
                  │
                  ▼
             Controller
          ┌───────┼────────┐
          ▼       ▼        ▼
       Engine    Store   GitClient
          │
          ▼
 workflow, delivery, assurance, review, snapshot, model
```

The Controller is the sole application boundary for task inspection and mutation.
It owns admission, active membership leases, complete repository-set snapshots,
workflow selection, current-action projection, action application, contract
revision, decisions, finding dispositions, cancellation, and bounded inspection.
The Engine and domain modules do not need to know whether a caller is a CLI, Hook,
Web request, or MCP tool.

The current installed Codex path has three additional layers of responsibility:

1. A large `follow-dev-flow` Skill teaches the model how to construct and invoke a
   strict JSON CLI command, how to interpret every workflow action, and how to use
   optional drivers.
2. SessionStart and UserPromptSubmit Hooks discover active tasks from the current
   directory and inject a Controller locator plus current projection.
3. A PreToolUse Hook provides a bounded, fail-open guard against direct writes to the
   Controller data directory.

Those layers duplicate protocol knowledge outside the Controller. They also invite
source inspection when the model cannot confidently reconstruct the locator,
payload shape, action sequence, or optional-driver rules. MCP provides a better
adapter boundary: tools have stable names, typed schemas, structured results,
annotations, and server-wide instructions.

## Goals

1. Make MCP the normal installed interaction boundary for Dev Flow.
2. Preserve the existing Controller and `0.4.0` task model without migration.
3. Replace shell-command construction with typed tools and structured output.
4. Return only the current action's guidance and required context.
5. Keep the plugin as a thin Codex distribution shell while also supporting direct
   local STDIO registration.
6. Preserve macOS and Windows x64 support with native launchers.
7. Preserve CLI and Web UI as independent adapters.
8. Maintain all current lease, snapshot, binding, revision, assurance, review, and
   Dossier guarantees.
9. Make runtime errors recoverable without blind mutation replay.
10. Prove that normal installed journeys do not require reading plugin source.

## Non-goals

- Rewriting the Controller, Engine, Store, workflow language, or state model.
- Changing `MODEL_VERSION`, current schemas, or the `0.4.0` data namespace.
- Migrating, repairing, translating, merging, or copying retained task data.
- Having the MCP server edit application source or execute optional drivers itself.
- Turning Dev Flow into an MCP client or proxy for OpenSpec, codebase-memory, review,
  shell, filesystem, GitHub, CI, or other servers.
- Remote Streamable HTTP, OAuth, hosted multi-user operation, or cross-machine state.
- MCP sampling, elicitation, roots, subscriptions, server tasks, or task augmentation.
- Branch/worktree creation or deletion, Git publication, external CI/PR/release
  orchestration, or parallel task executors.
- Making the removed Hook guard an unbypassable security boundary through another
  mechanism.
- Claiming complete support for arbitrary MCP hosts. The server is protocol-correct,
  but the first end-to-end product claim remains documented Codex surfaces with local
  repository tooling.
- Adding MCP Resources or Prompts in the first interface. Tools and initialization
  instructions are sufficient and are the most consistently supported primitives for
  this workflow.

## Product invariants

The migration is valid only if these invariants remain true:

- The Controller remains the only task-state writer.
- One task owns one immutable exact set of one to eight user-prepared worktrees.
- One task has one current action and one executor.
- Repository membership, worktree identity, and active leases remain Controller
  authority.
- Every mutation uses complete repository-set capture, exact action binding, and
  revision CAS where currently required.
- Stale bindings, unstable snapshots, corrupt inventory, unsafe paths, and invalid
  schemas fail closed at the Controller boundary.
- The MCP adapter never edits task files directly and never treats files as an API.
- Optional-driver evidence remains caller-produced evidence validated by the
  Controller; the server never fabricates or upgrades its assurance status.
- Existing `0.4.0` tasks remain byte-for-byte in place.
- Release identity and compatibility-model identity remain separate.

## Target architecture

```text
                          ┌──────────────────────────┐
                          │ Codex plugin distribution │
                          │ plugin.json + .mcp.json   │
                          └─────────────┬────────────┘
                                        │ starts
                                        ▼
┌────────────────────────────────────────────────────────────────┐
│ dev-flow-mcp --stdio                                           │
│                                                                │
│ MCPServer / lifecycle / schemas / guidance / result mapping    │
│                         │                                      │
│                         ▼                                      │
│                 MCP application adapter                        │
│                         │                                      │
│                         ▼                                      │
│                     Controller                                 │
│            ┌────────────┼────────────┐                         │
│            ▼            ▼            ▼                         │
│          Engine        Store       GitClient                   │
└────────────────────────────────────────────────────────────────┘

Independent retained adapters:

  dev-flow CLI ───────────────► Controller
  local read-only Web UI ─────► Controller
```

The plugin is not the runtime authority. It identifies the product and bundles one
MCP server configuration. The server is also executable without the plugin.

## Decision 1: MCP-first, not plugin removal

### Decision

Keep `.codex-plugin/plugin.json`, marketplace registration, source verification, and
host installers. Replace the plugin's installed Skills and Hooks with a bundled MCP
server declared by `mcpServers: "./.mcp.json"`.

Use a direct server map:

```json
{
  "dev-flow": {
    "command": "dev-flow-mcp",
    "args": ["--stdio"]
  }
}
```

The server command is a PATH launcher installed and validated before plugin
activation.

### Rationale

- Existing users already install through the plugin lifecycle.
- A plugin can distribute a local MCP server without retaining Skills or Hooks.
- Marketplace identity, authoritative-source controls, and uninstall behavior are
  valuable and independent of the interaction protocol.
- Standalone registration remains available for Codex surfaces that do not use the
  plugin package.

### Rejected alternatives

**Delete all plugin packaging immediately.** This would discard a mature installer,
marketplace identity, cross-platform lifecycle tests, and Codex-native discovery.

**Keep the large Skill and add MCP tools beside it.** This creates two competing
normal paths, preserves source-reading pressure, and doubles protocol authority.

**Keep a small Hook for discovery and protection.** This would retain trust review,
host-specific event behavior, and a second context-injection authority. The MCP
server instructions and explicit discovery tool are sufficient for the first MCP
release; the loss of the Hook guard is documented as a residual risk.

## Decision 2: Local STDIO only

### Decision

The first interface supports only local STDIO. `dev-flow-mcp` accepts `--stdio`; any
HTTP, SSE, host, port, token, or OAuth option is rejected as unsupported.

### Rationale

- The Controller reads local worktrees and local task state.
- STDIO has the smallest attack surface and no listening socket.
- There is no user or tenant identity model to secure a remote service.
- Remote execution would introduce path mapping, authorization, secret management,
  lifecycle, and cross-machine consistency problems unrelated to this migration.

### Future boundary

A later change may add a remote architecture only after defining identity,
authorization, repository transport, state ownership, and deployment. It must not
reuse the local data directory through a network endpoint by default.

## Decision 3: Use the official Python MCP SDK v2

### Decision

Implement the adapter with the official `mcp` Python SDK stable v2 line and the
high-level `MCPServer` API. Declare an upper major bound and lock the exact resolved
runtime. Do not hand-roll JSON-RPC or protocol negotiation.

```python
from mcp.server import MCPServer
```

The SDK selects and negotiates supported MCP protocol revisions. Dev Flow does not
persist an external MCP protocol revision inside task state.

### Python boundary

- Public installed support becomes CPython `>=3.10,<3.15`.
- The MCP dependency is isolated to the MCP package and managed runtime.
- Controller, Engine, Store, GitClient, workflow, delivery, review, and snapshot
  modules must not import `mcp`, Pydantic, Starlette, or SDK transitive packages.
- Importing or testing the core package must remain possible without starting the
  MCP server.

### Rationale

Protocol lifecycle, initialization, cancellation, validation, structured output,
and future compatibility are safer in the official SDK. Raising the Python floor is
preferable to maintaining a custom protocol implementation.

## Decision 4: Add a dedicated MCP adapter package

Expected source layout:

```text
src/dev_flow_orchestrator/
  mcp/
    __init__.py
    server.py          # MCPServer construction and registration
    runtime.py         # stdio lifecycle, dependency/version checks
    application.py     # Controller-facing application adapter
    schemas.py         # typed input/output models and JSON schema controls
    tools.py           # stable tool implementations
    guidance.py        # bounded initialization and action guidance
    results.py         # success/error envelopes and text summaries
    concurrency.py     # in-process operation coordination/cancellation
    logging.py         # stderr-only structured diagnostics

scripts/
  dev_flow_mcp.py
  dev_flow_mcp_launcher
  dev_flow_mcp_launcher.cmd

.mcp.json
```

Shared data-directory resolution moves out of CLI/Hook-specific code into a neutral
module used by CLI, MCP, Web, and any retained tests. The MCP adapter calls only
public Controller methods. If a bounded inventory or compact current-action view is
missing, add it to the Controller rather than reaching into `TaskStore` from the
server.

## Decision 5: Stable tool catalog

### Catalog

| Tool | Class | Controller mapping | Purpose |
|---|---|---|---|
| `dev_flow_server_info` | read | product metadata | Prove server, interface, model, workflow, and capability identity. |
| `dev_flow_list_tasks` | read | bounded inventory view | Page task summaries without full records or live Git capture. |
| `dev_flow_find_tasks_for_path` | read | path discovery | Find active tasks covering a canonical current path and report isolated diagnostics. |
| `dev_flow_get_task` | read | stored task view | Inspect one stored task summary, contract, status, and terminal Dossier summary. |
| `dev_flow_get_next_action` | read/live | `Controller.next` plus compact adapter | Capture the complete set and return exactly one current action, exact binding, and current guidance. |
| `dev_flow_start_task` | mutation | `Controller.start` | Admit an immutable repository set and create revision-zero state. |
| `dev_flow_apply_action` | mutation | `Controller.apply` | Apply exactly the projected action with exact payload and binding. |
| `dev_flow_revise_contract` | destructive mutation | `Controller.revise_contract` | Replace the accepted delivery contract under existing authority. |
| `dev_flow_record_decision` | destructive mutation | `Controller.decide` | Persist one exact current governance decision. |
| `dev_flow_dispose_finding` | destructive mutation | `Controller.dispose_finding` | Persist an authorized finding disposition. |
| `dev_flow_cancel_task` | destructive mutation | `Controller.cancel` | Cancel at a workflow stage that declares cancellation. |

### Naming and compatibility

- Tool names are part of `dev-flow-mcp/1.0.0` and must not be renamed within major
  version 1.
- New optional output fields may be added within major version 1.
- Required input fields, enum meanings, mutation semantics, and result meanings may
  not change incompatibly within major version 1.
- A new tool is additive and requires metadata-budget and installed-journey coverage.
- A generic `dev_flow_command`, arbitrary CLI argv, or method-name multiplexer is
  prohibited.

### Why Web UI control is not a tool

Starting or stopping the local Web UI is an operator process-management concern, not
a workflow action. It remains in the CLI. Exposing it to the model would add process
side effects unrelated to task delivery.

## Decision 6: Strict input schemas

Every tool input schema:

- has root `type: object`;
- uses `additionalProperties: false` at each closed object boundary;
- declares all required fields explicitly;
- applies existing byte, count, path, enum, and collection limits before Controller
  invocation where they can be checked without duplicating domain authority;
- passes nested domain objects unchanged to the Controller after transport-level
  validation;
- rejects NaN, Infinity, duplicate JSON keys, non-UTF-8 text, and unsupported model
  schema identities through existing strict JSON/domain validation.

The adapter does not weaken Controller validation to make a tool easier to call.

### Representative inputs

```json
{
  "requirement": "Add MCP-first delivery",
  "workflow": "feature",
  "repositories": ["/absolute/worktree"],
  "task_id": "optional-stable-id",
  "contract": {
    "schema": "dev-flow-delivery-contract/0.4.0",
    "revision": 1,
    "summary": "Accepted outcome",
    "acceptance_criteria": [
      {"id": "C1", "statement": "Observable result"}
    ],
    "scope": [],
    "constraints": [],
    "risks": [],
    "non_goals": [],
    "open_questions": []
  }
}
```

```json
{
  "task_id": "task-id",
  "action": "implementation.record",
  "payload": {"summary": "Implemented current action"},
  "binding": {"schema": "dev-flow-action-binding/0.4.0"}
}
```

The real binding and payload contract come from `dev_flow_get_next_action`; examples
are not substitutes for the projection.

## Decision 7: Versioned structured result envelope

All successful and failed domain calls return `structuredContent` using one envelope:

```json
{
  "schema": "dev-flow-mcp-result/1.0.0",
  "ok": true,
  "tool": "dev_flow_get_next_action",
  "request_id": "mcp-uuid",
  "result": {},
  "error": null
}
```

```json
{
  "schema": "dev-flow-mcp-result/1.0.0",
  "ok": false,
  "tool": "dev_flow_apply_action",
  "request_id": "mcp-uuid",
  "result": null,
  "error": {
    "code": "ACTION_BINDING_STALE",
    "message": "The action binding is stale",
    "details": {},
    "recovery": {
      "kind": "refresh-current-action",
      "tool": "dev_flow_get_next_action"
    }
  }
}
```

Each result also includes one concise text content item for clients that do not use
structured output. The text summary must not duplicate large JSON structures.

### Error mapping

| Failure | MCP representation |
|---|---|
| Unknown tool or malformed MCP request | JSON-RPC/MCP protocol error handled by SDK. |
| Input fails generated transport schema | invalid parameters or SDK validation error; no Controller call. |
| `DevFlowError` | tool result with `isError: true` and normalized structured error. |
| Unexpected adapter failure | `INTERNAL_ERROR`, redacted message, request ID; traceback only on stderr. |
| Cancellation before commit | `REQUEST_CANCELLED`, no mutation claim. |
| Cancellation after commit is uncertain | read-after-write recovery directive; never claim rollback. |

Domain error codes remain unchanged. The adapter adds only transport/runtime codes
under a documented prefix or closed set.

## Decision 8: Compact current-action projection

`Controller.next` remains authoritative, but the MCP response is deliberately scoped
to the current obligation. The adapter creates `dev-flow-mcp-action/1.0.0` from the
current `dev-flow-agent/0.4.0` projection without changing or persisting the original.

Required inline fields:

```json
{
  "schema": "dev-flow-mcp-action/1.0.0",
  "task": {
    "task_id": "...",
    "status": "ACTIVE",
    "revision": 12,
    "workflow": "feature"
  },
  "contract": {},
  "repository_set": {
    "repository_set_id": "...",
    "repositories": [],
    "workspace_snapshot_digest": "..."
  },
  "action": {
    "id": "...",
    "kind": "...",
    "payload_schema": {},
    "binding": {},
    "retry_budget": {},
    "driver": null,
    "current_obligation": null,
    "review_contract": null
  },
  "inputs": [],
  "resources": [],
  "guidance": {},
  "source_projection_digest": "..."
}
```

The adapter may remove complete historical records, repeated product metadata, raw
state serialization, and repository snapshot internals that the current action does
not consume. It may not remove a field referenced by the current action's payload
schema, binding, driver contract, obligation, review contract, governing resources,
or guidance.

A parity test maintains an explicit field-use manifest. Every field consumed by
current guidance or required to construct an accepted payload must be either inline
or obtainable through a bounded read tool before execution. No hidden server-side
conversation state is required.

`dev_flow_get_task` returns stored summaries by default. It does not return the full
record ledger unless a future separately specified paginated interface is added.

## Decision 9: Action-specific guidance replaces Skills

### Initialization instructions

The server initialization `instructions` field begins with this self-contained text.
The complete authority rule below MUST fit in the first 512 UTF-8 bytes:

```text
The Controller is the only Dev Flow task-state writer. Discover or explicitly select
one task before start or resume, then call dev_flow_get_next_action and perform only
its one current action across the immutable repository set. Submit mutations with the
exact binding and closed payload. Never guess stale, ambiguous, unavailable, or
terminal authority. Reading or editing raw task-state files is unsupported.
```

The complete instruction string is bounded and contains only cross-tool invariants,
not action manuals.

### Guidance result

`dev_flow_get_next_action` returns:

```json
{
  "schema": "dev-flow-mcp-guidance/1.0.0",
  "action_id": "assurance.dispatch",
  "objective": "Execute the one projected assurance obligation",
  "must_read": [],
  "allowed_effects": "verifies-source",
  "required_evidence": [],
  "payload_notes": [],
  "driver": null,
  "stale_recovery": {
    "tool": "dev_flow_get_next_action",
    "blind_retry": false
  },
  "completion_rule": "Only a fresh Controller projection confirms progress.",
  "guidance_digest": "lowercase-sha256"
}
```

Guidance is selected by action ID/kind and enriched only from current projection
fields. The digest is computed over the canonical guidance object with the
`guidance_digest` field omitted. The required schema fields above are the sole
canonical guidance vocabulary; catalog entries may add bounded identifiers but may
not replace these fields with aliases. It covers:

- preflight;
- impact and codebase-memory fallback;
- OpenSpec-backed planning and governing resource binding;
- source-producing implementation/rework/documentation;
- current assurance obligation execution;
- independent review and causal findings;
- governance decisions and dispositions;
- terminal Dossier finalization;
- cancellation only when currently declared.

Guidance never replaces the projected schema. If guidance and projection disagree,
package validation must fail; runtime treats the projection as authority.

### Independent review guidance identity

The old review Skill is replaced by a canonical versioned guidance document in the
MCP package. The current review guidance content and stable labels participate in the
same review guidance snapshot/digest semantics currently required by review
contracts. The adapter returns the exact digest expected by the Controller and the
reviewer binds it in structured findings. Package validation fails if the review
guidance artifact, digest derivation, projected contract, or tests drift.

### Optional drivers

The server never calls OpenSpec, codebase-memory, a reviewer model, or another MCP
server. It returns the current driver's tool name, phase, required evidence, fallback,
and status rules. The Codex executor uses whatever declared capability is available
and submits the resulting current driver envelope. Unavailable or degraded evidence
continues to normalize conservatively in the Controller.

## Decision 10: Explicit discovery replaces Hook injection

`dev_flow_find_tasks_for_path` accepts one absolute or resolvable local path. It uses
the same canonical path comparison and inventory isolation as current Controller/Hook
discovery and returns:

```json
{
  "classification": "none|single|ambiguous|inventory-unavailable",
  "tasks": [
    {
      "task_id": "...",
      "status": "ACTIVE",
      "workflow_id": "feature"
    }
  ],
  "diagnostics": []
}
```

Behavior:

- no match: the caller may start a new task after normal admission checks;
- one match: call `dev_flow_get_next_action` for that task;
- multiple valid matches: require an explicit task ID and never choose by order;
- corrupt current entry: isolate it from implicit authority, return bounded
  diagnostics, and preserve fail-closed admission behavior;
- terminal tasks: excluded from active matches.

Server instructions make this the required first step for a new or resumed delivery
conversation. Unlike a Hook, the tool is explicit and observable; it does not claim
that every arbitrary host prompt triggers discovery automatically.

## Decision 11: Preserve data in place

Data-directory resolution precedence:

1. explicit `--data-dir` supplied to the launcher for tests or standalone operator
   control;
2. `DEV_FLOW_DATA_DIR` explicit environment override;
3. plugin-compatible writable root when a documented host environment provides one;
4. existing default under `CODEX_HOME` or `~/.codex`;
5. append the current product namespace and `0.4.0` model namespace exactly as today.

The resolver is shared by CLI and MCP. It canonicalizes a non-strict data root before
creation and preserves repository/data disjointness checks.

The MCP result never exposes the data root. `dev_flow_server_info` reports only the
model namespace and whether the root is available, not its filesystem path.

No migration step enumerates prior namespaces or rewrites current state. The MCP
adapter opens the same current Store and leaves retained older namespaces untouched.

## Decision 12: In-process concurrency and cancellation

MCP clients may issue overlapping calls even though the product model has one current
action. The adapter therefore classifies operations:

- **stored reads:** server info, inventory, stored task summary;
- **live captures:** path discovery when live metadata is required and current action
  projection;
- **mutations:** start, apply, contract revision, decision, disposition, cancellation.

Within one server process:

- live captures and mutations use a bounded coordinator to avoid unbounded concurrent
  Git snapshots;
- mutations for the same task are serialized before entering the Controller;
- separate task calls may execute concurrently only where the Controller and Git
  capture semantics already permit it;
- cross-process correctness remains Store locks, membership locks, snapshot
  stability, action bindings, and revision CAS—not the MCP adapter lock.

Cancellation is checked before expensive capture, between bounded capture phases
where possible, and before mutation commit. After the Controller commits, the server
never claims that client cancellation rolled the mutation back. It returns an
uncertain-completion recovery instruction when transport state cannot establish the
result.

MCP task augmentation is declared `forbidden`; Dev Flow task IDs are product workflow
identities, not MCP background-task handles.

## Decision 13: Tool annotations and approval

Every tool sets explicit annotations:

| Tool group | readOnly | destructive | idempotent | openWorld |
|---|---:|---:|---:|---:|
| server info, list, find, get task, get next | true | false | true | false |
| start task | false | false | false | false |
| apply action | false | false | false | false |
| revise contract, decision, disposition, cancel | false | true | false | false |

All tools set task support to forbidden.

`destructiveHint` describes whether a call can replace or terminate accepted task
state, not whether it edits application source. `apply_action` is non-idempotent even
when a stale binding prevents a second commit. The annotations do not replace input
validation, Codex approvals, or Controller authority.

Recommended plugin-scoped Codex policy is `writes`: read tools are available without
unnecessary prompts while mutations remain subject to host approval policy. The
installer must not silently grant blanket approval or rewrite unrelated user policy.

## Decision 14: Remove the Hook guard with an explicit residual boundary

MCP cannot reproduce a PreToolUse Hook that sees every shell, edit, or patch command.
This change therefore does not pretend to preserve that behavior.

Compensating controls:

- task data remains outside every admitted repository;
- the data root is not returned by tools or normal diagnostics;
- no MCP tool exposes file-level state operations;
- all model-facing mutations use closed schemas and Controller validation;
- server instructions and public guidance explicitly prohibit direct access;
- package tests prove normal journeys never need the path;
- unexpected traces are written to stderr and redact the data root;
- installation and uninstallation preserve or remove only validated owned assets.

Residual risk:

A user or model with unrestricted local shell access can still search for and modify
files outside the MCP server. This was also possible around a fail-open, bounded Hook.
The product describes MCP and Controller validation as the supported authority, not as
an operating-system sandbox.

## Decision 15: Managed MCP runtime outside source and task data

The verified source checkout must remain a clean attached authoritative `main`, and
uninstall must distinguish source from task data. The installer therefore creates an
owned runtime at a separate product path, for example:

```text
<CODEX_HOME>/plugins/runtime/dev-flow-orchestrator-personal/<release>/
```

The exact host path is centralized and recorded by an installer marker. It contains:

- a venv built from supported 64-bit CPython;
- the locked official MCP SDK and transitive dependencies;
- an import path or installed wheel that points to the verified release source;
- a runtime receipt containing release, source commit, Python, lock digest, and
  launcher identity.

The installer:

1. verifies/fetches the authoritative source under existing rules;
2. validates the candidate before executing its lifecycle code;
3. selects a supported Python 3.10–3.14 interpreter;
4. builds a new temporary runtime from locked metadata;
5. runs unit-level import and MCP initialize/tool-catalog smoke tests;
6. atomically activates the runtime marker/launcher;
7. registers and activates the plugin;
8. verifies the bundled server is visible and healthy.

A failed runtime build leaves the prior active runtime and plugin untouched. An
eligible upgrade builds a new release runtime before switching. Uninstall removes
only a marker-validated runtime and launchers, preserving task data.

## Decision 16: Bundled and standalone modes are mutually exclusive

### Bundled mode

The normal install activates the plugin and its `dev-flow` bundled server. User policy
is under:

```toml
[plugins."dev-flow-orchestrator".mcp_servers.dev-flow]
enabled = true
default_tools_approval_mode = "writes"
```

Documentation presents this as an example, not an installer-forced edit.

### Standalone mode

The same launcher may be registered directly:

```text
codex mcp add dev-flow-orchestrator -- dev-flow-mcp --stdio
```

### Conflict behavior

The installer never creates standalone registration. Validation detects an enabled
standalone registration pointing to Dev Flow while bundled mode is enabled and
reports `DUPLICATE_MCP_REGISTRATION`. It does not claim success until one mode is
disabled or removed. Runtime tool names remain identical in both modes.

## Decision 17: STDOUT purity and observability

STDIO stdout is protocol-only. Import banners, progress output, warnings, tracebacks,
and installer messages may never be written by the running server to stdout.

Diagnostics use stderr as one-line structured JSON or a bounded human-readable form:

```json
{
  "level": "error",
  "event": "tool_failed",
  "request_id": "...",
  "tool": "dev_flow_apply_action",
  "code": "ACTION_BINDING_STALE"
}
```

Rules:

- no contract content, requirement text, repository file content, secrets, raw
  environment, full bindings, or data-root paths in default logs;
- request IDs correlate model-visible errors with stderr diagnostics;
- log level is configured at server startup, not through an MCP mutation tool;
- telemetry or network export is absent in the first release;
- tests capture file descriptors and fail on non-protocol stdout bytes.

## Decision 18: Context budgets are release gates

The MCP interface is intended to reduce context consumption, so size is a tested
product property.

Initial limits:

- server instructions: at most 4 KiB UTF-8, with first 512 characters self-contained;
- each tool description: at most 512 UTF-8 bytes;
- complete serialized `tools/list`: at most 32 KiB for the stable catalog;
- action-specific guidance: at most 8 KiB UTF-8;
- complete compact current action: at most 128 KiB UTF-8;
- complete structured result envelope: at most 512 KiB UTF-8;
- server-info text summary: at most 1 KiB;
- list/find task item summary: at most 2 KiB per item and paginated at a default of 20,
  maximum 100;
- complete list/discovery page: at most 256 KiB UTF-8;
- human-readable text content for any structured result: at most 4 KiB unless an
  existing smaller domain bound applies;
- one default stderr diagnostic event: at most 4 KiB UTF-8;
- at most four process-local live-capture or mutation calls may be inside the MCP
  coordinator at once; excess calls are rejected immediately and are not queued;
- no full ledger, raw snapshot path inventory, or duplicate structured JSON in text
  content.

Existing domain payload and action limits continue to apply. If the exact current
projection exceeds a safe MCP response bound, the tool fails with a bounded
`MCP_RESULT_LIMIT` rather than truncating an action binding or silently omitting
required context. A future paginated context capability requires its own spec.

## Decision 19: CLI and Web remain separate adapters

The CLI continues to expose strict JSON commands for recovery, scripting, package
validation, and operator use. It is not called by the MCP server. Both adapters call
the Controller directly and share:

- data-directory resolution;
- result/error normalization concepts;
- application inspection methods;
- release/model identity;
- tests that compare domain behavior.

The Web UI remains local and read-only. MCP does not proxy Web requests or manage the
Web process.

## Decision 20: Release and interface versioning

Target release:

- `RELEASE_VERSION = 0.5.0`
- `MODEL_VERSION = 0.4.0`
- MCP interface schema = `dev-flow-mcp/1.0.0`
- result schema = `dev-flow-mcp-result/1.0.0`
- action view schema = `dev-flow-mcp-action/1.0.0`
- guidance schema = `dev-flow-mcp-guidance/1.0.0`

The release bump updates only release authority and derived package/lock/manifest
metadata. Existing model-bearing files remain `0.4.0`. MCP interface constants are
separate from product model constants so a tool metadata change does not imply task
state migration.

## Detailed call flows

### Start a new task

```text
Codex            MCP server         Controller          Store/Git
  │ find(path)       │                  │                  │
  ├─────────────────►│ discover         │                  │
  │                  ├─────────────────►│                  │
  │                  │                  ├─────────────────►│
  │ no active match  │◄─────────────────┤                  │
  │◄─────────────────┤                  │                  │
  │ start(...)       │                  │                  │
  ├─────────────────►│ validate schema  │                  │
  │                  ├─────────────────►│ admission/start  │
  │                  │                  ├─────────────────►│ lock/capture/write r0
  │ task summary     │◄─────────────────┤                  │
  │◄─────────────────┤                  │                  │
  │ get_next(id)     │                  │                  │
  ├─────────────────►│                  ├─────────────────►│ complete capture
  │ action+binding   │◄─────────────────┤                  │
  │◄─────────────────┤                  │                  │
```

`start_task` does not combine start and next into one transaction. If the post-start
capture cannot stabilize, the task still exists and the response truthfully reports
start success; the caller obtains the next action separately.

### Apply a current action

```text
Codex              MCP server             Controller
  │ get_next(id)        │                      │
  ├────────────────────►│ next                 │
  │ exact binding       │◄─────────────────────┤
  │◄────────────────────┤                      │
  │ perform action outside server              │
  │ apply(id, action, payload, binding)         │
  ├────────────────────►│ transport validate   │
  │                     ├─────────────────────►│ snapshot/binding/CAS/apply
  │ fresh result or     │◄─────────────────────┤
  │ structured domain error                    │
  │◄────────────────────┤                      │
```

The server never caches or repairs a stale binding. On `REVISION_CONFLICT`, the error
may include the fresh bounded projection already produced by the Controller; otherwise
recovery directs the caller to `dev_flow_get_next_action`.

### Resume after transport uncertainty

```text
1. Do not blindly repeat the mutation.
2. Call dev_flow_get_task for the stored revision/status.
3. Call dev_flow_get_next_action for the current binding.
4. If the original action is no longer current, treat the mutation as committed.
5. If it remains current, reassess the exact current projection before retry.
```

## Tool output details

### `dev_flow_server_info`

Returns release, model version, MCP interface version, supported workflows, tool
catalog digest, guidance catalog digest, supported transport, supported Python range,
and health of the current data namespace. It does not return source or data paths.

### `dev_flow_list_tasks`

Inputs:

- optional statuses;
- optional workflow;
- optional terminal inclusion;
- opaque cursor;
- limit 1–100.

Returns stable task summaries sorted by current product ordering plus isolated
inventory diagnostics and next cursor. It does not perform complete live repository
capture.

### `dev_flow_find_tasks_for_path`

Canonicalizes one path with platform rules and matches any active repository member.
It never starts a task. It returns at most one item per task even if multiple member
paths could match corrupt state.

### `dev_flow_get_task`

Returns stored status, revision, workflow, immutable repository inventory, effective
contract summary, current node, outstanding decision/finding summary, and terminal
Dossier summary when present. It does not expose raw records or filesystem state.

### `dev_flow_get_next_action`

Performs current live capture and returns the compact action view, exact binding,
projected payload schema, current resources/obligation/review contract, and current
guidance. Terminal tasks return a terminal action view or explicit `done: true`
summary according to existing Controller semantics.

### `dev_flow_start_task`

Uses repeatable repositories represented as a JSON array. Caller order has no
priority meaning. The Controller derives repository IDs and repository-set identity.
An explicit task ID is recommended for recovery-safe automation; duplicate IDs obey
current Store/controller conflict semantics.

### `dev_flow_apply_action`

Accepts no unknown fields and does not infer action or binding from server memory.
Every call supplies the exact action ID, payload, and complete binding returned by the
current projection.

### Governance mutations

Contract revision, decision, finding disposition, and cancellation remain separate
tools because they have different authorization, schemas, destructive meaning, and
recovery behavior. They are not accepted through `apply_action` unless the existing
Controller already models the operation that way.

## Security analysis

### Assets

- task state and append-only record history;
- immutable repository membership and active leases;
- repository contents and Git identity;
- accepted delivery contract and decisions;
- action bindings, snapshots, evidence, findings, and Dossiers;
- verified source checkout and installer-owned runtime;
- user Codex/MCP configuration.

### Trust boundaries

- model-to-MCP tool request;
- MCP adapter-to-Controller call;
- Controller-to-filesystem/Git process;
- installer-to-network/source/runtime dependency resolution;
- plugin configuration-to-host process launch;
- user shell access outside the MCP server.

### Threats and controls

| Threat | Control |
|---|---|
| Model invents or alters a binding | Exact binding required; Controller validates digest, snapshot, revision, action, and resource freshness. |
| Model calls a generic command | No generic tool exists; schemas are closed. |
| Model reads/writes raw task state | No path is exposed; no file tool exists; direct access remains unsupported. |
| MCP stdout is corrupted | Protocol-only stdout tests; all diagnostics to stderr. |
| Tool metadata understates side effects | Explicit annotations plus package tests; Controller remains authority. |
| A dependency is replaced unexpectedly | Major bound, exact lock, candidate validation, managed runtime receipt. |
| Installer upgrades source but not runtime | Runtime receipt binds source commit and release; activation requires equality. |
| Duplicate server registrations create ambiguous tools | Install validation detects enabled bundled + standalone registrations. |
| Unexpected exception leaks data | Redacted `INTERNAL_ERROR`; traceback only on stderr under bounded diagnostics. |
| Host cancels after mutation commit | No rollback claim; read-after-write recovery. |
| Optional driver is unavailable | Guidance requires truthful degraded/unavailable envelope; Controller selects conservative assurance. |
| Stale guidance diverges from workflows | Guidance catalog digest and action-coverage validation; installed journeys for every official workflow. |

## File-level implementation map

| Area | Expected change |
|---|---|
| `product.py` | Add MCP interface/result/action/guidance constants and metadata limits; keep model constants unchanged. |
| neutral runtime paths | Extract data-root and managed-runtime resolution shared by adapters/installers. |
| `controller.py` | Add only bounded public inspection/compact projection methods needed by MCP; no MCP imports. |
| `mcp/*` | New protocol adapter, schemas, guidance, result mapping, coordination, and logging. |
| `pyproject.toml` | Target 0.5.0, Python 3.10+, MCP dependency group/entry point. |
| `uv.lock` | Exact MCP SDK and transitive runtime lock. |
| launchers | Add native `dev-flow-mcp` POSIX and `.cmd` entry points. |
| plugin manifest | Remove `skills`; add `mcpServers`; do not declare Hooks. |
| `.mcp.json` | Declare one local STDIO server using PATH launcher. |
| installers | Build/validate/activate managed runtime, launcher, plugin, and server health atomically. |
| uninstallers | Remove validated MCP runtime/launcher/registration; preserve task data. |
| Skills/Hooks | Remove from release package after parity; delete stale authority and tests. |
| validation | Add tool catalog, schema, context budget, stdout, lock, installed journey, and no-source-reading checks. |
| docs | Rewrite usage around MCP tools and explain migration/residual boundary. |

## Validation strategy

### Unit tests

- construction and identity of MCP server;
- every input and output schema, including unknown fields and bounds;
- tool-to-Controller mapping with fake Controller;
- success and every domain/runtime error mapping;
- annotations and task-support metadata;
- instruction and metadata size budgets;
- action guidance selection and coverage;
- review guidance digest stability;
- data-root precedence and non-disclosure;
- stdout purity and stderr redaction;
- concurrency coordinator and cancellation checkpoints;
- cursor behavior for bounded inventory;
- duplicate registration detection;
- managed-runtime receipt validation.

### Protocol tests

Use the official in-process client/stdio harness and MCP Inspector-compatible checks:

- initialize and negotiated protocol;
- server name/version/instructions;
- tools capability and exact `tools/list` catalog;
- successful read and mutation call;
- structured output conformance;
- domain error with `isError: true`;
- malformed params without Controller call;
- cancellation and client disconnect;
- clean EOF/shutdown/restart;
- no stdout contamination.

### Controller parity tests

For each mapped operation, execute equivalent CLI and MCP calls against isolated
repositories/data roots and compare:

- resulting task state bytes or canonical state objects;
- revision and record history;
- projection/binding identity;
- error code/details where transport-neutral;
- no partial mutation on failure.

MCP-specific wrappers and text summaries are excluded from state equivalence.

### Installed journeys

Run from the actual installed plugin/runtime, not source imports:

- one-member and multi-repository tasks;
- resume from a secondary member;
- every official workflow;
- source-confirmed focused assurance and one closed risk-trigger path per profile;
- OpenSpec available and unavailable/degraded planning;
- codebase-memory available and degraded impact;
- independent review approved, unavailable, causal rework, and triage-required paths;
- stale binding, revision conflict, workspace drift, corrupt inventory, missing member,
  and cancellation;
- existing 0.4.x-created active task resumed through MCP;
- terminal Dossier inspection;
- restart mid-task;
- model-facing journey instrumented to fail if it reads package source, Skill, Hook,
  CLI source, or task-state files.

### Lifecycle tests

macOS and Windows suites cover:

- fresh install;
- idempotent repair;
- eligible fast-forward upgrade;
- ineligible source refusal;
- Python below 3.10 refusal;
- locked runtime build and receipt;
- launcher paths with spaces/Unicode;
- plugin activation failure;
- MCP initialize/catalog failure;
- duplicate standalone registration;
- old runtime retained on failed upgrade;
- uninstall with source kept/removed;
- task data preserved in every path.

## Rollout plan

### Phase A: Adapter behind development activation

- Add MCP package, dependency lock, launchers, schemas, guidance, and tests.
- Keep existing Skills/Hooks installed in normal packages temporarily.
- Make MCP activation opt-in for developer validation only.
- Run CLI/MCP parity and installed journeys.

Exit: every mapped operation and all official workflows pass through MCP.

### Phase B: MCP becomes default, old path remains rollback-only

- Add `.mcp.json` and manifest `mcpServers`.
- Default installers provision and validate the MCP runtime.
- Stop presenting Skills/Hooks as the normal path.
- Keep old assets only in test fixtures or a rollback branch, not as simultaneous
  runtime authority.

Exit: installed user journeys complete without old assets or source reads.

### Phase C: Remove installed Skills and Hooks

- Remove `skills/`, `hooks/`, Hook runtime code, Hook-specific launchers, trust guidance,
  and package expectations.
- Update all current specs, docs, architecture diagrams, and validation.
- Release 0.5.0.

Exit: package validation rejects reintroduction of stale Skill/Hook authority.

### Rollback

- Reinstall the last verified 0.4.x release through the authoritative installer.
- Do not delete the 0.5.0 managed runtime until rollback activation succeeds.
- Preserve the same `0.4.0` task data.
- Remove or disable the 0.5.0 bundled MCP registration as part of rollback.
- Report that the old Hook trust step returns and must be reviewed again.

## Risks and mitigations

### Risk: loss of automatic Hook discovery

**Effect:** Codex may not discover an active task unless it follows server
instructions.

**Mitigation:** put the complete discovery sequence in the first 512 instruction
characters, make discovery read-only and cheap, add default plugin prompts, test new
and resumed conversations, and clearly avoid claiming event-level enforcement.

### Risk: loss of PreToolUse guard

**Effect:** unrestricted shell/edit capability can still target task files.

**Mitigation:** do not expose the path, keep data outside repositories, remove every
normal need for file access, use Controller-only tools, document the residual, and do
not market annotations as enforcement.

### Risk: MCP dependency increases installer complexity

**Effect:** runtime build or dependency resolution can fail and the source checkout is
no longer sufficient by itself.

**Mitigation:** isolated managed runtime, exact lock, build-before-switch, receipt
binding, rollback retention, explicit Python requirement, and lifecycle tests.

### Risk: tool metadata becomes another large context source

**Effect:** a large catalog could recreate the Skill problem.

**Mitigation:** exact small catalog, short descriptions, strict size gates, global
instructions only, and current-action guidance returned on demand.

### Risk: compact projection omits a required field

**Effect:** executor invents data or cannot construct a valid payload.

**Mitigation:** explicit field-use manifest, controller/projection parity tests, all
workflow installed journeys, fail rather than truncate, and keep the source projection
digest for diagnostics.

### Risk: duplicate registrations

**Effect:** Codex sees two indistinguishable tool sets or starts two server processes.

**Mitigation:** mutually exclusive documented modes, installer detection, stable
server identity, and health checks.

### Risk: transport retry duplicates mutation

**Effect:** caller replays a committed non-idempotent operation after losing response.

**Mitigation:** no automatic retry of mutations, exact binding/CAS, explicit task IDs
for start, read-after-write recovery, and uncertain-completion errors.

### Risk: action guidance drifts from Controller semantics

**Effect:** model follows stale procedural text even though schemas are current.

**Mitigation:** guidance generated from current projection plus a versioned catalog,
coverage tests for every action template, digest checks, and package validation.

## Resolved questions

1. **Pure MCP repository or plugin-wrapped MCP?** Plugin-wrapped MCP by default, with
   standalone registration supported. The interaction boundary is MCP in both modes.
2. **Keep Hooks for guard/discovery?** No. Their absence is explicit and validated.
3. **Use CLI subprocess from MCP?** No. MCP calls the Controller directly.
4. **Use remote HTTP?** No, local STDIO only.
5. **Change the persisted model?** No, retain `0.4.0`.
6. **Use official SDK or custom JSON-RPC?** Official SDK v2.
7. **Preserve Python 3.9?** No public installed support; require 3.10–3.14.
8. **Expose Resources/Prompts?** Not in interface 1.0. Tools and instructions only.
9. **Server executes source changes or drivers?** No. Codex remains the executor.
10. **CLI and Web UI removed?** No, both remain independent adapters.

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/tasks.md`

# Tasks: Introduce an MCP-first runtime

## 0. Change controls and baseline

- [x] 0.1 Pin the implementation baseline to the reviewed authoritative `main`
  commit and record its current `RELEASE_VERSION`, `MODEL_VERSION`, workflow catalog,
  package manifest, Python range, and installed lifecycle assets.
- [ ] 0.2 Run the complete pre-change test suite on macOS and the focused native
  Windows suite; preserve the command, environment, and results as baseline evidence.
- [x] 0.3 Run `openspec validate dev-flow-orchestrator-mcp --strict` and resolve all
  proposal/spec structural issues before production code changes.
- [x] 0.4 Create a traceability table from every Requirement/Scenario in this change
  to one or more tests; fail package validation when a stable MCP tool or lifecycle
  requirement lacks coverage.
- [x] 0.5 Confirm that no concurrent OpenSpec change modifies the same plugin manifest,
  installer authority, Hook removal, Python floor, or release-version authority.

## 1. Version and product authorities

- [x] 1.1 Set the target release authority to `0.5.0` using the existing release-bump
  mechanism.
- [x] 1.2 Keep `MODEL_VERSION` exactly `0.4.0` and add tests proving the release bump
  does not modify model schemas, namespaces, workflow documents, policy documents,
  bindings, records, findings, or Dossier identities.
- [x] 1.3 Add constants for `dev-flow-mcp/1.0.0`,
  `dev-flow-mcp-result/1.0.0`, `dev-flow-mcp-action/1.0.0`, and
  `dev-flow-mcp-guidance/1.0.0` outside the persisted-model identity.
- [x] 1.4 Raise the supported Python metadata and public runtime boundary to
  `>=3.10,<3.15`; update classifiers and all platform matrices.
- [x] 1.5 Add the official MCP Python SDK v2 with an upper major bound and update the
  exact dependency lock.
- [x] 1.6 Add validation that Controller, Engine, Store, GitClient, workflow, delivery,
  review, snapshot, and model modules do not import the MCP SDK or its transitive
  framework packages.

## 2. Shared runtime paths and ownership

- [x] 2.1 Extract data-directory resolution from CLI/Hook-specific code into a neutral
  module with documented precedence for explicit argument, environment override,
  plugin-compatible root, and existing `CODEX_HOME` default.
- [x] 2.2 Preserve the exact current `0.4.0` data namespace and repository/data
  disjointness checks.
- [x] 2.3 Add a managed-runtime path resolver outside both the verified source checkout
  and task-data root for POSIX and Windows.
- [x] 2.4 Define and validate a runtime receipt containing release version, source
  commit, Python executable/version/architecture, dependency-lock digest, MCP launcher
  identity, and activation timestamp.
- [x] 2.5 Add tests for paths with spaces, valid Unicode, apostrophes, different drives,
  symlinks/reparse points within the supported boundary, and absent-yet-creatable
  runtime/data roots.
- [x] 2.6 Add tests proving no MCP result, normal stderr diagnostic, or installation
  receipt presented to the model exposes the Controller data-root path.

## 3. MCP package skeleton and lifecycle

- [x] 3.1 Add `src/dev_flow_orchestrator/mcp/` with `server`, `runtime`, `application`,
  `schemas`, `tools`, `guidance`, `results`, `concurrency`, and `logging` modules.
- [x] 3.2 Construct one `MCPServer` with stable server name, release version, bounded
  initialization instructions, tools capability, and no Resources, Prompts, sampling,
  elicitation, task augmentation, or remote transports.
- [x] 3.3 Add `scripts/dev_flow_mcp.py` and native POSIX/Windows launchers supporting
  `--stdio`, `--data-dir`, and bounded logging configuration only.
- [x] 3.4 Reject HTTP/SSE/host/port/token/OAuth options with an explicit unsupported
  runtime error and no listening socket.
- [x] 3.5 Ensure stdout remains protocol-only from import through shutdown; route all
  diagnostics to stderr.
- [x] 3.6 Add clean startup, initialize, EOF, disconnect, cancellation, shutdown, and
  restart behavior.
- [x] 3.7 Add a startup self-check for supported Python, compatible MCP SDK major,
  current release/model/interface identities, data namespace availability, and tool
  catalog/guidance digests.
- [x] 3.8 Add protocol tests using the official client/stdio harness and an
  MCP-Inspector-compatible test command.

## 4. Transport schemas and result contracts

- [x] 4.1 Define closed input models for all eleven stable tools with explicit required
  fields, enums, count/byte limits, and `additionalProperties: false` semantics.
- [x] 4.2 Reuse current domain validators for contract, payload, binding, decision,
  finding disposition, and repository semantics instead of duplicating or weakening
  them in Pydantic/SDK models.
- [x] 4.3 Define the common structured success/error envelope and per-tool output
  schemas.
- [x] 4.4 Return one concise text content item in addition to structured content; add
  tests preventing full JSON duplication in text.
- [x] 4.5 Map every `DevFlowError` to `isError: true` with unchanged domain code,
  bounded details, and deterministic recovery kind where applicable.
- [x] 4.6 Map malformed protocol/unknown tool/transport-schema failures to SDK/MCP
  protocol errors without calling the Controller.
- [x] 4.7 Map unexpected exceptions to redacted `INTERNAL_ERROR` results with request
  IDs and stderr-only tracebacks.
- [x] 4.8 Add uncertain-completion recovery for disconnect/cancellation after a
  mutation may have committed; prohibit automatic mutation retries.
- [x] 4.9 Test duplicate keys, unsupported schema versions, NaN/Infinity, invalid UTF-8,
  first-excess limits, unknown fields, and nested invalid domain values.

## 5. Bounded Controller inspection APIs

- [x] 5.1 Add or formalize a bounded Controller server-info/product view that exposes no
  source/data paths.
- [x] 5.2 Add or formalize a paginated task-summary inventory view that isolates corrupt
  entries and does not perform full live Git capture.
- [x] 5.3 Add or formalize a stored single-task summary view with immutable repository
  membership, effective contract summary, current node, outstanding governance
  summary, and terminal Dossier summary.
- [x] 5.4 Add an MCP compact current-action projection derived from the authoritative
  `dev-flow-agent/0.4.0` projection without persisting a new model object.
- [x] 5.5 Maintain an explicit field-use manifest proving that every field required by
  current action guidance, payload construction, binding, driver, obligation, review
  contract, and governing resource is retained.
- [x] 5.6 Fail with `MCP_RESULT_LIMIT` rather than truncating a binding or omitting
  required action context.
- [x] 5.7 Add tests proving the new Controller methods are MCP-independent and remain
  callable by CLI/Web tests without importing the SDK.

## 6. Read-only MCP tools

- [x] 6.1 Implement `dev_flow_server_info` with release/model/interface identity,
  workflow IDs, transport, Python range, catalog digests, and bounded health.
- [x] 6.2 Implement `dev_flow_list_tasks` with status/workflow/terminal filters, opaque
  cursor, default limit 20, maximum 100, stable ordering, and inventory diagnostics.
- [x] 6.3 Implement `dev_flow_find_tasks_for_path` using the existing canonical path,
  active-task, lease-conflict, corrupt-entry, multi-member, and terminal exclusion
  semantics.
- [x] 6.4 Implement `dev_flow_get_task` using only the bounded stored view.
- [x] 6.5 Implement `dev_flow_get_next_action` using complete repository-set capture,
  exact current binding, compact current-action projection, and current guidance.
- [x] 6.6 Mark all read tools read-only, non-destructive, idempotent, closed-world, and
  task-augmentation-forbidden.
- [x] 6.7 Add read-tool tests for one/multiple/no task, secondary-member discovery,
  terminal exclusion, corrupt inventory isolation, overlapping invalid inventory,
  Windows equivalent path spelling, stale workspace, and result bounds.

## 7. Mutation MCP tools

- [x] 7.1 Implement `dev_flow_start_task` by calling `Controller.start` directly with
  immutable repository array, workflow, requirement, optional task ID, and optional
  accepted contract.
- [x] 7.2 Ensure start does not silently combine creation with a second live projection
  mutation or report rollback when a later read fails.
- [x] 7.3 Implement `dev_flow_apply_action` with exact task ID, action ID, payload, and
  unmodified current binding; do not infer any value from server memory.
- [x] 7.4 Implement `dev_flow_revise_contract` with current ownership claims, reason,
  actor label, and existing Controller revision/snapshot authority.
- [x] 7.5 Implement `dev_flow_record_decision` as a separate exact decision mutation.
- [x] 7.6 Implement `dev_flow_dispose_finding` with exact disposition and explicit
  actor authorization input required by the current Controller.
- [x] 7.7 Implement `dev_flow_cancel_task` only through current stage-declared
  cancellation semantics.
- [x] 7.8 Mark start/apply as non-read-only, non-idempotent, non-destructive hints and
  governance/cancel tools as non-read-only, non-idempotent, destructive hints; mark all
  closed-world and task-augmentation-forbidden.
- [x] 7.9 Add parity tests comparing each CLI and MCP mutation's canonical state,
  revision, records, bindings, domain errors, and atomic failure behavior.
- [x] 7.10 Add stale binding, revision conflict, unstable snapshot, missing member,
  invalid repository set, active lease, exhausted budget, invalid decision,
  unauthorized disposition, unavailable cancellation, and terminal-task tests.

## 8. Guidance catalog and context controls

- [x] 8.1 Implement the exact server initialization instruction with the complete
  discovery/get-next/execute/apply sequence in the first 512 characters.
- [x] 8.2 Keep total server instructions at or below 4 KiB UTF-8 and prohibit workflow
  manuals or examples that belong in current-action guidance.
- [x] 8.3 Create a versioned guidance catalog for every official current action kind,
  including preflight, impact, planning, implementation/rework/documentation,
  assurance, review, governance, finalization, and cancellation.
- [x] 8.4 Generate `dev-flow-mcp-guidance/1.0.0` from the current projection and only the
  applicable catalog entry.
- [x] 8.5 Include objective, must-read fields, allowed effects, required evidence,
  payload notes, driver rules, stale recovery, completion rule, and canonical guidance
  digest while staying at or below 8 KiB.
- [x] 8.6 Replace impact Skill guidance with current action guidance that keeps
  baseline/current codebase-memory projects separate and requires source confirmation.
- [x] 8.7 Replace follow Skill OpenSpec guidance with current machine-readable status,
  instruction, concrete path/digest, source-stage, and fallback rules.
- [x] 8.8 Replace review Skill guidance with a canonical package artifact and preserve
  review guidance snapshot/digest binding semantics.
- [x] 8.9 Add validation that every official/custom action template maps to one safe
  guidance entry or a closed generic fallback and that no guidance contradicts its
  payload schema or workflow authority.
- [x] 8.10 Add package tests rejecting instructions/guidance that tell the model to read
  MCP source, CLI source, Skills, Hooks, state files, or raw data directories.
- [x] 8.11 Enforce the 512-byte per-tool-description, 32-KiB tools-list, 128-KiB
  compact action, 512-KiB structured result, 256-KiB inventory/discovery page,
  4-KiB text summary and stderr-event, and other context budgets defined in design.

## 9. Concurrency, cancellation, and logging

- [x] 9.1 Add an in-process coordinator with four immediate-admission live/mutation
  slots and no request queue, without replacing Store/membership/CAS authority.
- [x] 9.2 Serialize same-task mutations and define bounded behavior when another live
  capture or mutation is in progress.
- [x] 9.3 Add cancellation checkpoints before capture, between bounded capture phases
  where supported, and before Controller commit.
- [x] 9.4 Ensure cancellation after commit never reports rollback; return read-after-write
  recovery.
- [x] 9.5 Add request IDs to all tool calls and stderr events.
- [x] 9.6 Redact data roots, environment values, contracts, bindings, repository file
  contents, and secrets from default logs.
- [x] 9.7 Add file-descriptor-level tests that fail on any non-protocol stdout byte and
  verify bounded stderr under expected and unexpected failures.

## 10. Plugin and standalone packaging

- [x] 10.1 Add root `.mcp.json` with exactly one `dev-flow` STDIO server invoking the
  installed `dev-flow-mcp --stdio` launcher.
- [x] 10.2 Update `.codex-plugin/plugin.json` to reference `./.mcp.json` through
  `mcpServers`, remove `skills`, and ensure no default/explicit Hook asset is packaged.
- [x] 10.3 Keep plugin identity, author, repository, license, release version, and
  interface capabilities synchronized with release authority.
- [x] 10.4 Add validation that all manifest paths are relative, inside the plugin root,
  and point to present candidate content.
- [x] 10.5 Document bundled mode and direct standalone registration using the same PATH
  launcher.
- [x] 10.6 Add duplicate detection for an enabled standalone Dev Flow registration plus
  enabled bundled mode; report deterministic recovery and do not claim healthy
  activation.
- [x] 10.7 Ensure the installer never creates both registration modes or silently edits
  unrelated MCP/plugin policy.
- [x] 10.8 Add plugin-scoped approval examples while preserving user authority over
  approvals and never granting blanket mutation approval automatically.

## 11. Managed runtime installation and uninstallation

- [x] 11.1 Extend candidate package validation to verify the MCP source, dependency lock,
  launchers, `.mcp.json`, manifest, guidance catalog, tests, and runtime bootstrap
  before any candidate code executes.
- [x] 11.2 Extend macOS and Windows installers to locate supported 64-bit CPython
  3.10–3.14 and fail before activation on unsupported versions/architecture.
- [x] 11.3 Build a temporary isolated MCP runtime outside source and task data using the
  exact lock; bind it to verified source commit and release.
- [x] 11.4 Run import, initialize, instructions, tool catalog, one read call, and one
  isolated mutation smoke before activating the runtime.
- [x] 11.5 Switch runtime/launcher/plugin activation atomically enough that a failed
  upgrade leaves the previous valid runtime and plugin usable.
- [x] 11.6 Verify bundled server visibility and health after plugin activation; treat
  initialization/catalog failure as installation failure with explicit recovery.
- [x] 11.7 Preserve existing authoritative `main`, clean attached checkout,
  fast-forward-only, origin, ignored-collision, marketplace isolation, and plugin
  activation rules.
- [x] 11.8 Extend uninstallers to remove only marker-validated MCP runtime, launchers,
  and Dev Flow registration while preserving task data and unrelated MCP/plugin
  configuration.
- [x] 11.9 Add keep-source behavior and fail-closed source/runtime deletion when identity
  or cleanliness is uncertain.
- [x] 11.10 Add rollback tests proving the previous runtime remains available after a
  failed runtime build or plugin activation.

## 12. Remove legacy installed authority

- [x] 12.1 Remove `skills/follow-dev-flow`, `skills/analyze-change-impact`, and
  `skills/review-dev-flow-change` from the release package after MCP installed journeys
  pass.
- [x] 12.2 Remove `hooks/hooks.json`, Hook bootstrap, package Hook adapter, Hook-specific
  launcher paths, and Hook trust instructions from release assets.
- [x] 12.3 Remove or rewrite tests that assert Hook injection, Controller locator text,
  `/hooks` trust, command matching, or PreToolUse data-directory denial.
- [x] 12.4 Preserve relevant domain discovery and path-guard test coverage at the
  Controller/path layer even though Hook behavior is removed.
- [x] 12.5 Add package validation that fails if legacy Skills/Hooks or source-reading
  instructions reappear in current executable assets.
- [x] 12.6 Ensure retained archive OpenSpec files and historical documentation remain
  historical evidence and are not treated as current package authority.

## 13. Installed workflow journeys

Task 13.10 is a harness precondition and SHALL be enabled before executing 13.2–13.9;
the numbered list preserves historical references rather than execution order.

- [x] 13.1 Build an installed MCP journey harness that connects over the real launcher
  and never imports source test helpers into the server process.
- [x] 13.2 Run one-member and multi-repository `lite` journeys through discovery, start,
  next, apply, assurance, and Dossier.
- [x] 13.3 Run focused and closed-trigger installed journeys for all six official
  workflows, including both `lite` paths, preserving exact profile floors,
  allowances, ceilings, not-required decisions, and final Dossiers.
- [x] 13.4 Resume an active task from a non-first repository member after server restart.
- [x] 13.5 Resume a task created by a 0.4.x CLI/plugin installation with the new MCP
  server and finalize without state migration.
- [x] 13.6 Exercise OpenSpec available, stale, unavailable, source-producing, and
  governing-resource paths through action guidance.
- [x] 13.7 Exercise codebase-memory current/baseline separation and conservative degraded
  fallback.
- [x] 13.8 Exercise independent review approval, unavailable self-review, introduced/
  affected finding rework, unknown-causality triage, impact-gap re-planning, and
  authorized disposition.
- [x] 13.9 Exercise transport disconnect/uncertainty recovery without blind mutation
  replay.
- [x] 13.10 Instrument journeys to fail if the executor reads `skills/`, `hooks/`, MCP
  adapter source, CLI source, raw Store files, or the Controller data root.
- [x] 13.11 Exercise contract revision carry-forward with exact adopted-drift claims,
  corrupt-inventory admission failure, and concurrent admission from distinct linked
  worktrees without bypassing membership authority.

## 14. Package and boundary validation

- [x] 14.1 Update package validation to inspect candidate content rather than imported
  invoking-checkout modules for every MCP asset and identity.
- [x] 14.2 Validate exact stable tool names, input/output schemas, annotations,
  task-support setting, instructions, guidance digests, and context budgets.
- [x] 14.3 Validate all official workflows/actions against the MCP guidance coverage
  manifest.
- [x] 14.4 Validate current model schemas remain exactly `0.4.0` and reject any attempt
  to treat MCP interface versions as persisted model versions.
- [x] 14.5 Validate lock metadata equals package metadata and that the managed runtime
  receipt equals verified source/release/lock/Python identity.
- [x] 14.6 Validate no remote transport, generic command, raw state, branch/worktree,
  publication, CI/PR/release, or parallel-executor tool is exposed.
- [x] 14.7 Validate first-excess behavior for all new MCP metadata, result, inventory,
  and guidance bounds without truncation or partial mutation.
- [x] 14.8 Run the existing workflow, controller, store-integrity, adaptive-assurance,
  multi-repository, Web UI, release-bump, package, and platform suites to prove no
  core regression.

## 15. Documentation and architecture

- [x] 15.1 Rewrite README and README_CN around MCP discovery, start/resume, current
  action, apply, governance, and Dossier inspection.
- [x] 15.2 Rewrite INSTALL and INSTALL_CN with Python 3.10+, bundled/standalone mode,
  duplicate registration, MCP health verification, approvals, runtime ownership,
  uninstall, preserved data, and rollback.
- [x] 15.3 Update ARCHITECTURE and ARCHITECTURE_CN diagrams to show MCP/CLI/Web adapters
  over the Controller and remove current Skill/Hook authority.
- [x] 15.4 Update CONTRIBUTING documents with SDK isolation, protocol tests, stdout
  discipline, context budgets, schema compatibility, and tool-addition rules.
- [x] 15.5 Update promotion/release docs and roadmap to describe 0.5.0 as an interface
  migration with unchanged model 0.4.0.
- [x] 15.6 Document the explicit residual boundary from removing the fail-open Hook
  guard and avoid describing MCP annotations as enforcement.
- [x] 15.7 Document that other MCP hosts may connect at protocol level but are outside
  the first complete delivery support claim unless they provide the required local
  repository executor behavior.

## 16. Final release evidence

- [x] 16.1 Run strict OpenSpec validation and reconcile every changed current spec.
- [ ] 16.2 Run complete source tests on every supported Python version/host matrix and
  focused unsupported-version refusal tests.
- [x] 16.3 Run package validation against a copied candidate from outside the invoking
  checkout.
- [x] 16.4 Run fresh install, idempotent repair, fast-forward upgrade, failed runtime
  build, failed plugin activation, duplicate registration, rollback, and uninstall on
  macOS.
- [ ] 16.5 Run the corresponding focused native Windows x64 lifecycle matrix without
  POSIX compatibility tooling.
- [x] 16.6 Run the complete installed MCP workflow journey suite from the activated
  artifact.
- [x] 16.7 Capture `codex mcp list` or equivalent plugin-scoped health evidence showing
  one enabled Dev Flow server and the expected catalog.
- [x] 16.8 Confirm existing current task data and retained prior-version namespace bytes
  are unchanged by install, server startup, discovery, and uninstall.
- [x] 16.9 Confirm the release package contains no current Skills or Hooks and normal
  executor transcripts contain no package-source reads.
- [ ] 16.10 Publish the Delivery Dossier for this change only after all MCP, platform,
  package, compatibility, documentation, and rollback evidence is current.
- [x] 16.11 Regenerate the non-authoritative consolidated OpenSpec reading snapshot,
  readable traceability table, and `CHECKSUMS.sha256` after the final authoritative
  proposal, design, tasks, specs, baseline, and validation report are stable.

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-server-runtime/spec.md`

## Purpose

Define the local MCP process, protocol, lifecycle, dependency, concurrency, logging,
and compatibility boundary that exposes the existing Dev Flow Controller without
creating a second workflow runtime or persisted authority.

## ADDED Requirements

### Requirement: The product provides one local STDIO MCP server

The product SHALL provide a local executable MCP server named `dev-flow-mcp` whose
stable Dev Flow interface identity is `dev-flow-mcp/1.0.0`. The first supported
transport SHALL be STDIO. The server SHALL implement MCP initialization,
server instructions, tool discovery, and tool calls through the official Python MCP
SDK stable v2 line and SHALL negotiate the MCP protocol revision through that SDK.

The public launcher SHALL accept `--stdio` and the documented data-root and logging
configuration only. It SHALL reject HTTP, SSE, host, port, OAuth, token, or listening
socket options as unsupported. The first release SHALL NOT expose Streamable HTTP,
server-side sampling, elicitation, MCP task augmentation, remote repository access,
or cross-machine Controller state.

#### Scenario: A compatible client initializes the server

- **WHEN** a client starts the installed launcher over STDIO and sends a valid MCP initialize request
- **THEN** the server returns its stable name and release version, bounded global instructions, and the capabilities required for the approved tool catalog

#### Scenario: The client requests the tool catalog

- **WHEN** an initialized client invokes `tools/list`
- **THEN** the server returns exactly the stable `dev-flow-mcp/1.0.0` catalog with generated input schemas, declared output schemas, and explicit tool annotations

#### Scenario: A network transport is requested

- **WHEN** an operator starts the first-release server with an HTTP, SSE, host, port, OAuth, or remote-mode option
- **THEN** startup fails before opening a socket or constructing a Controller and reports that only local STDIO is supported

#### Scenario: The STDIO client disconnects

- **WHEN** the server receives clean EOF after initialization or tool use
- **THEN** it stops without mutating task state merely because the transport ended and leaves every persisted lease and task governed by the Controller

### Requirement: MCP and existing adapters share one Controller authority

Every MCP tool that inspects or mutates Dev Flow state SHALL call the existing
`Controller` application boundary directly or a bounded application adapter that
itself delegates to that Controller. The MCP server SHALL NOT invoke the JSON CLI,
parse CLI output, call the Web UI, write task files directly, or implement a parallel
workflow state machine.

The server SHALL resolve the same current data root and `0.4.0` model namespace as
the CLI. It SHALL preserve current task IDs, immutable repository membership,
membership leases, workflow identities, records, artifacts, action bindings,
revision compare-and-swap behavior, replay validation, assurance budgets, findings,
decisions, and Delivery Dossiers. The MCP result SHALL NOT expose the physical data
root.

#### Scenario: An existing task is read through MCP

- **WHEN** a valid model `0.4.0` task created by a `0.4.x` CLI or plugin installation is inspected through MCP
- **THEN** the server reads the same task without migration, translation, copying, or a new MCP-specific task record

#### Scenario: MCP applies an action

- **WHEN** `dev_flow_apply_action` receives a current action ID, payload, and exact binding
- **THEN** the existing Controller performs snapshot capture, validation, mutation, record sealing, and fresh projection generation exactly as it does for the CLI boundary

#### Scenario: Direct state access is attempted

- **WHEN** an MCP implementation path attempts to enumerate raw task files, replace task JSON, or bypass Controller validation
- **THEN** package validation or tests fail and the operation is not part of the supported MCP interface

### Requirement: The MCP dependency remains isolated from the core runtime

The supported installed runtime SHALL be 64-bit CPython `>=3.10,<3.15`. The MCP
adapter SHALL use the official `mcp` Python SDK stable v2 line with an upper major
bound and an exact resolved lock. SDK and transitive packages SHALL be installed in
an installer-owned isolated runtime outside the verified source checkout and outside
all Controller task-data roots.

Only modules below `src/dev_flow_orchestrator/mcp/` and their launch bootstrap MAY
import the MCP SDK or its transitive framework types. Controller, Engine, Store,
GitClient, workflow, delivery, review, snapshot, platform, CLI, and Web modules SHALL
remain importable without importing or starting MCP. No task schema or product model
identity SHALL include an MCP protocol or SDK version.

#### Scenario: Core modules are imported without the MCP runtime

- **WHEN** a core-only test environment imports Controller, Store, Engine, GitClient, CLI, and Web modules without installing the MCP dependency
- **THEN** those imports remain available and no MCP module is loaded as a side effect

#### Scenario: The installed Python is 3.9

- **WHEN** an installer finds only CPython 3.9
- **THEN** MCP installation fails before plugin activation with a bounded requirement for supported CPython 3.10–3.14 and does not modify existing task data

#### Scenario: The resolved MCP dependency drifts

- **WHEN** package validation detects a missing lock, an unsupported SDK major, or installed runtime metadata that differs from the candidate lock
- **THEN** validation or activation fails rather than running an unverified dependency set

### Requirement: STDOUT remains protocol-only

While the MCP server is running, every byte written to standard output SHALL belong
to the MCP transport selected by the SDK. Startup banners, progress text, warnings,
debug output, tracebacks, installer receipts, and application logs SHALL NOT be
written to standard output.

Diagnostics SHALL use standard error only. Default diagnostics SHALL be bounded and
SHALL NOT include task requirements, contract text, repository file content, raw
environment values, secrets, complete action bindings, complete payloads, or the
Controller data-root path. Each visible tool result and matching diagnostic SHALL use
a request ID where correlation is needed. The first release SHALL emit no telemetry
or network log export. One default diagnostic event SHALL be no larger than 4 KiB
UTF-8.

#### Scenario: A tool returns a domain failure

- **WHEN** a Controller operation raises a current `DevFlowError`
- **THEN** the MCP response is written through the protocol on stdout and a bounded optional diagnostic is written only to stderr

#### Scenario: An unexpected adapter exception occurs

- **WHEN** the MCP adapter raises an exception not classified as a current domain error
- **THEN** the client receives a redacted `INTERNAL_ERROR` with a request ID, the traceback is confined to stderr, and stdout remains parseable MCP traffic

#### Scenario: Protocol purity is validated

- **WHEN** the protocol test suite captures the server's raw stdout file descriptor across initialization, success, error, cancellation, and shutdown
- **THEN** any non-protocol byte fails the candidate

### Requirement: Concurrent MCP calls remain bounded and preserve Controller correctness

The server SHALL classify operations as stored reads, live captures, or mutations.
It SHALL bound process-local live Git captures, SHALL serialize mutations for the
same task before entering the Controller, and SHALL prevent unbounded queues or
thread creation. Calls for distinct tasks MAY overlap only where current Controller,
Store, Git, and repository-set semantics permit them.

The first interface SHALL admit at most four process-local live-capture or mutation
calls to the coordinator at once. Admission SHALL be immediate: excess calls SHALL
fail with the closed runtime-unavailable result and SHALL NOT wait in a request
queue. Stored reads that do not enter Git or mutation authority remain outside this
live-operation limit.

Process-local coordination SHALL NOT replace cross-process authority. Cross-process
correctness SHALL continue to come from the current task locks, membership lock,
repository snapshot stability, exact action binding, and revision compare-and-swap
rules. The server SHALL NOT claim multi-executor or parallel-action support merely
because MCP clients can issue concurrent requests.

#### Scenario: Two calls mutate the same task

- **WHEN** two MCP requests concurrently attempt mutations against one task revision
- **THEN** at most one current mutation commits and the other receives the current Controller conflict or stale-binding behavior with no partial record

#### Scenario: Two calls race to start overlapping tasks

- **WHEN** separate MCP processes request repository sets that share an active member
- **THEN** the existing membership lock admits at most one task and returns the committed owner identity to the rejected request

#### Scenario: Live requests exceed the process bound

- **WHEN** more live capture requests arrive than the configured bounded coordinator permits
- **THEN** excess work is rejected or bounded according to the documented runtime policy without creating an unbounded queue or mutating task state

### Requirement: Cancellation never fabricates rollback

The MCP adapter SHALL observe cooperative cancellation before an expensive capture,
between bounded capture phases where the Controller exposes a safe checkpoint, and
before entering a mutation commit where possible. Cancellation before a commit SHALL
return `REQUEST_CANCELLED` and SHALL NOT claim a mutation.

Once the Controller has committed, the server SHALL NOT represent transport
cancellation or disconnect as rollback. When completion cannot be established, the
result SHALL be `MCP_COMPLETION_UNCERTAIN` with a read-after-write recovery directive
that identifies the exact read tool and task identity needed to determine the
current authoritative state. MCP task augmentation SHALL be declared unsupported for
all tools.

#### Scenario: Cancellation occurs before Controller entry

- **WHEN** a request is cancelled before a mutation enters the Controller
- **THEN** the server returns `REQUEST_CANCELLED` and no task revision or record is added

#### Scenario: Cancellation occurs during a bounded Git capture

- **WHEN** a live capture observes cancellation before the Controller commit boundary
- **THEN** the capture is stopped through current process-cancellation behavior and no partial snapshot or task record is accepted

#### Scenario: The transport disappears after a possible commit

- **WHEN** the client disconnects after the Controller may have committed but before it receives the response
- **THEN** the server and documentation require a fresh task read or next-action read and never instruct blind replay of the mutation

### Requirement: MCP transport failures use a closed error boundary

Unknown tools and malformed MCP messages SHALL use SDK-managed protocol errors.
Transport input that fails the generated tool schema SHALL fail before Controller
entry. Current `DevFlowError` values SHALL retain their existing code, message, and
bounded details inside the MCP error envelope. Unexpected adapter failures SHALL use
a closed MCP runtime code rather than a fabricated domain code.

The MCP runtime code set SHALL initially be limited to `MCP_RUNTIME_UNAVAILABLE`,
`MCP_DEPENDENCY_INVALID`, `MCP_RESULT_LIMIT`, `REQUEST_CANCELLED`,
`MCP_COMPLETION_UNCERTAIN`, and `INTERNAL_ERROR`. Adding or changing a code SHALL
require an MCP interface version review.

#### Scenario: Tool arguments are malformed

- **WHEN** a caller omits a required field, supplies an unknown field, violates a declared bound, or uses the wrong JSON type
- **THEN** schema validation rejects the call before Controller construction or mutation

#### Scenario: A Controller error is returned

- **WHEN** a current domain operation raises `ACTION_BINDING_STALE`, `REVISION_CONFLICT`, `WORKSPACE_CHANGED`, or another `DevFlowError`
- **THEN** the client receives that exact domain code with a bounded recovery directive and no protocol-level success claim

#### Scenario: An unrecognized internal condition occurs

- **WHEN** an adapter condition cannot be mapped to the closed runtime or domain code set
- **THEN** the response uses `INTERNAL_ERROR`, redacts implementation detail, and records a request ID for stderr correlation

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-controller-tools/spec.md`

## Purpose

Define the stable typed MCP tools that map model-facing Dev Flow operations to the
existing Controller while preserving strict schemas, current bindings, domain errors,
and one-action-at-a-time workflow authority.

## ADDED Requirements

### Requirement: The MCP server exposes one closed stable tool catalog

Interface `dev-flow-mcp/1.0.0` SHALL expose exactly these tools:

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
raw state read/write, generic Controller method invocation, Web UI lifecycle control,
branch/worktree management, Git publication, external CI/PR/release effects, or an
unversioned experimental tool in the stable catalog. A catalog addition, removal,
rename, or incompatible schema change SHALL require a new MCP interface version.

#### Scenario: The stable catalog is listed

- **WHEN** a client invokes `tools/list` against interface `dev-flow-mcp/1.0.0`
- **THEN** the response contains all and only the eleven approved tool names

#### Scenario: A generic command tool is proposed

- **WHEN** implementation adds a tool that accepts arbitrary CLI arguments, Python call names, shell commands, or task-state paths
- **THEN** package validation rejects the candidate as bypassing the closed Controller interface

### Requirement: Tool schemas are closed, generated, and bounded

Every tool SHALL have a generated JSON input schema with `additionalProperties:
false` at every closed object boundary. Required and optional fields SHALL be
explicit, strings and collections SHALL carry current product bounds, enums SHALL be
closed where the domain is closed, and numeric pagination SHALL have minimum and
maximum values. Tool implementations SHALL receive typed validated values rather
than reparsing JSON strings.

Every tool SHALL declare an output schema for `dev-flow-mcp-result/1.0.0`. The
adapter SHALL additionally validate each produced structured result before returning
it. Existing embedded Controller values such as delivery contracts, action payloads,
bindings, decisions, dispositions, and findings SHALL remain subject to their current
strict domain validators; wrapping them in MCP SHALL NOT weaken or duplicate those
validators. A complete structured result envelope SHALL be no larger than 512 KiB
UTF-8.

#### Scenario: An unknown input field is supplied

- **WHEN** a caller supplies an undeclared field to any stable tool
- **THEN** transport schema validation rejects the call before Controller entry

#### Scenario: A nested domain object is structurally invalid

- **WHEN** a tool receives a JSON object that passes its outer transport type but violates the current delivery-contract, action-payload, binding, decision, or disposition contract
- **THEN** the Controller or existing domain validator returns the current structured domain error and commits no partial record

#### Scenario: Adapter output violates its schema

- **WHEN** an implementation produces a result missing a required envelope or tool-specific field
- **THEN** the adapter treats it as an internal failure and does not return malformed structured success

### Requirement: Every tool returns one versioned result envelope

Every successful or domain-failed tool call SHALL return structured content with
exactly these top-level fields:

```json
{
  "schema": "dev-flow-mcp-result/1.0.0",
  "ok": true,
  "tool": "dev_flow_get_next_action",
  "request_id": "mcp-<uuid>",
  "result": {},
  "error": null
}
```

On a domain or runtime tool failure, `ok` SHALL be false, `result` SHALL be null,
`error` SHALL contain `code`, `message`, bounded `details`, and either null or a
closed `recovery` object, and the MCP tool result SHALL be marked as an error. Every
call SHALL also return one concise text content item for clients that cannot consume
structured content. Text SHALL summarize rather than duplicate the JSON structure.

#### Scenario: A read tool succeeds

- **WHEN** a valid read tool completes
- **THEN** the envelope identifies its tool and request, sets `ok: true`, validates its tool-specific result, and sets `error: null`

#### Scenario: A domain operation fails

- **WHEN** the Controller raises a current domain error
- **THEN** the envelope sets `ok: false`, retains the exact domain code, marks the tool result as an error, and includes only a bounded applicable recovery directive

#### Scenario: A client consumes text only

- **WHEN** a client ignores structured content
- **THEN** the text item states the outcome, task identity when applicable, current action or error code, and next safe operation without embedding complete bindings or snapshots

### Requirement: Server information reports capability without exposing local secrets

`dev_flow_server_info` SHALL be a stored read. It SHALL report release version,
`dev-flow-mcp` interface version, current `MODEL_VERSION`, current namespace,
official workflow IDs, supported repository-count bounds, registration mode when
known, supported transport, runtime health, and whether the current data root is
available. It SHALL NOT return the data-root path, environment values, source
checkout path, managed-runtime path, access tokens, raw dependency metadata, or task
content.

#### Scenario: Server information is requested

- **WHEN** an initialized client calls `dev_flow_server_info`
- **THEN** it can determine interface compatibility and health without learning any protected local path

#### Scenario: The data root is unavailable

- **WHEN** the current data root cannot be prepared or read
- **THEN** server information reports bounded unavailable health and the relevant domain/runtime code without inventing an empty healthy inventory

### Requirement: Task inventory reads are bounded and do not run Git

`dev_flow_list_tasks` SHALL use the current stored inventory path and SHALL NOT run
Git or create task bindings. It SHALL support stable pagination with default limit
20 and maximum limit 100, optional current/terminal status filtering, and a stable
continuation token or offset contract. Each item SHALL include only bounded task ID,
status, workflow, revision, current node, repository-count and safe repository labels,
contract summary, and updated timestamp. It SHALL NOT include the raw ledger,
complete contract, full repository snapshot, action binding, or absolute Controller
data path.

`dev_flow_get_task` SHALL return the existing bounded stored task view by task ID,
including contract, decisions, current plan/obligation summaries, timeline summary,
terminal Dossier when present, and recovery-relevant state. It SHALL not run Git
unless a future separately named live option is specified by another interface
version. Each inventory or discovery item SHALL be no larger than 2 KiB UTF-8 and a
complete inventory or discovery page SHALL be no larger than 256 KiB UTF-8.

#### Scenario: Inventory is listed while a repository is missing

- **WHEN** one task member is temporarily unavailable but stored task state is valid
- **THEN** inventory and stored task detail remain readable without Git and accurately distinguish stored state from live readiness

#### Scenario: Inventory contains an invalid entry

- **WHEN** one current-namespace candidate task entry is invalid and another is healthy
- **THEN** the read returns healthy items plus bounded inventory diagnostics and does not represent the invalid entry as terminal or unleased

#### Scenario: A page exceeds the maximum

- **WHEN** a caller requests more than 100 inventory items
- **THEN** input validation rejects the request rather than returning an unbounded result

### Requirement: Repository-path discovery returns explicit current authority

`dev_flow_find_tasks_for_path` SHALL canonicalize one caller-supplied local path
through the same host comparison rules used by admission and current discovery. It
SHALL return matching non-terminal tasks at most once each, inventory diagnostics,
and a closed classification of `none`, `single`, `ambiguous`, or
`inventory-unavailable`. It SHALL NOT start a task, select an ambiguous task, create
an action binding, or imply that an invalid task released its membership lease.

When exactly one healthy active task matches and the caller explicitly requests the
current action in the same call, the tool MAY return the same live compact action
result as `dev_flow_get_next_action`; otherwise discovery SHALL remain a stored
identity operation. The default SHALL avoid live Git capture.

#### Scenario: One active task covers a secondary repository

- **WHEN** a path is at or below any member of one healthy active task
- **THEN** discovery returns that task once regardless of member order

#### Scenario: Multiple valid tasks match

- **WHEN** persisted current state contains multiple matching active tasks
- **THEN** discovery returns `ambiguous` with all bounded task identities and selects none implicitly

#### Scenario: No current task matches

- **WHEN** the path is outside every valid active member
- **THEN** discovery returns `none` and performs no task mutation

### Requirement: Current-action reads preserve the exact action binding

`dev_flow_get_next_action` SHALL call the authoritative current Controller projection
for one explicit task ID and SHALL return `dev-flow-mcp-action/1.0.0`. The compact
MCP action SHALL include the task ID, status, revision, workflow, effective contract,
complete repository-set identity and safe member inventory, aggregate current
snapshot digest, current action ID and kind, exact payload schema, exact unmodified
action binding, retry/budget state, current obligation when present, driver contract
when present, review contract when present, bounded input and governing-resource
manifests, completion state, and action-specific guidance.

The adapter SHALL NOT synthesize, trim, normalize, reorder, or reuse a binding. It
SHALL fail with `MCP_RESULT_LIMIT` rather than truncate the binding or omit a field
required to execute the action safely. A terminal task SHALL return terminal status
and its Dossier/recovery summary without fabricating another action.
A complete `dev-flow-mcp-action/1.0.0` object SHALL be no larger than 128 KiB UTF-8.

#### Scenario: An active task is projected

- **WHEN** a caller requests the next action for a healthy active task
- **THEN** the result describes exactly one current action and supplies the exact binding required by `dev_flow_apply_action`

#### Scenario: The repository set changes during capture

- **WHEN** any member or relevant Git evidence changes between current complete capture passes
- **THEN** the tool returns the current instability error and no action binding is presented as usable

#### Scenario: The task is terminal

- **WHEN** a task is `DONE`, `INCOMPLETE`, or `CANCELLED`
- **THEN** the result reports terminal authority and no executable current action

### Requirement: Task creation maps directly to Controller admission

`dev_flow_start_task` SHALL accept a non-empty requirement, one official workflow ID
or absolute current custom workflow path, one to eight repository roots, an optional
explicit task ID, and either a complete initial `dev-flow-delivery-contract/0.4.0`
or the currently permitted minimal-contract path. It SHALL preserve caller-supplied
repository membership as an exact set subject to current canonicalization,
admission, stable two-pass capture, overlap, Git-identity, data-root separation, and
active-lease rules.

A successful result SHALL include task identity, immutable canonical membership,
revision-zero state summary, and the fresh preflight action or an explicit directive
to call `dev_flow_get_next_action`. It SHALL NOT create branches, worktrees, commits,
marketplace entries, or external delivery effects.

#### Scenario: A one-member task starts

- **WHEN** a valid requirement, official workflow, and one prepared worktree are supplied
- **THEN** the Controller creates one current task using the same repository-set model as a larger set and returns its first current action

#### Scenario: A repository set is invalid

- **WHEN** roots are missing, bare, duplicate, overlapping, share an invalid in-task Git identity, overlap the data root, or are leased by another active task
- **THEN** the entire start fails before revision-zero state is written

#### Scenario: Task creation is retried after uncertain transport completion

- **WHEN** the caller cannot determine whether a previous non-idempotent start committed
- **THEN** guidance requires discovery or explicit task-ID lookup before any retry and never treats start as safely replayable

### Requirement: Action application records exactly the projected current action

`dev_flow_apply_action` SHALL require `task_id`, exact `action_id`, one JSON object
`payload`, and the exact JSON object `binding` returned by the current action read.
It SHALL pass those values to `Controller.apply` without shell escaping or JSON string
round-tripping. It SHALL perform no model-side retry and SHALL return the mutation
receipt plus the fresh next or terminal compact action produced after the commit.

The tool SHALL remain non-idempotent. A repeated call with a consumed or stale
binding SHALL receive current Controller stale-binding or revision-conflict behavior
and SHALL NOT append the same action twice. The adapter SHALL not infer missing
payload fields, add unknown fields, or turn a failed obligation into a pass.

#### Scenario: A current action is applied

- **WHEN** action ID, payload, and binding exactly match the current Controller projection
- **THEN** one Controller record commits and the result returns the authoritative fresh projection

#### Scenario: The binding is stale

- **WHEN** task revision, contract, input, predecessor, or workspace evidence no longer matches the supplied binding
- **THEN** the call commits no record and directs the caller to `dev_flow_get_next_action`

#### Scenario: The same mutation is replayed

- **WHEN** a caller repeats a previously successful apply with the old binding
- **THEN** current Controller validation rejects it rather than treating the tool annotation or transport retry as idempotence

### Requirement: Governance tools preserve explicit task authority

`dev_flow_revise_contract` SHALL map to current contract revision with the complete
next contract, optional exact ownership claims, non-empty reason, and actor label.
`dev_flow_record_decision` SHALL accept one current decision object and preserve all
current criterion-waiver and assurance-waiver constraints. `dev_flow_dispose_finding`
SHALL accept one current disposition object and an explicit actor-authorized boolean.
`dev_flow_cancel_task` SHALL require task ID and non-empty reason and SHALL succeed
only at a workflow stage that currently declares cancellation.

Each governance mutation SHALL preserve current snapshot, binding, revision,
contract-digest, finding, actor, budget, and one-record rules. The server SHALL NOT
infer user authority from a model statement, default actor authorization to true,
or report cancellation complete until the Controller returns terminal
`CANCELLED` authority.

#### Scenario: A contract revision is accepted

- **WHEN** the complete next contract and ownership evidence satisfy the current revision boundary
- **THEN** one revision record commits, prior history remains, and the fresh MCP action reflects the new effective contract

#### Scenario: Finding disposition lacks actor authority

- **WHEN** `dev_flow_dispose_finding` is called without explicit actor authorization
- **THEN** the current forbidden error is returned and no disposition record is appended

#### Scenario: Cancellation is unavailable at the current stage

- **WHEN** the workflow does not declare cancellation from the current node
- **THEN** `dev_flow_cancel_task` returns the current workflow error and preserves the task and its leases

#### Scenario: Cancellation commits

- **WHEN** the current stage permits cancellation and the Controller returns `done: true`, `status: CANCELLED`, and `current_node: cancelled`
- **THEN** the MCP result reports terminal cancellation and only then represents the task as ended

### Requirement: Tool annotations describe but do not grant authority

Read tools SHALL declare `readOnlyHint: true`, `destructiveHint: false`,
`idempotentHint: true`, and `openWorldHint: false`. `dev_flow_start_task` and
`dev_flow_apply_action` SHALL declare non-read-only, non-idempotent, closed-world
behavior; start SHALL be non-destructive and apply SHALL be classified according to
its Controller-state effect without claiming source-file authority.
Contract revision, decision, finding disposition, and cancellation SHALL declare
non-read-only, destructive, non-idempotent, closed-world behavior. All tools SHALL
declare MCP task support forbidden.

Annotations SHALL NOT bypass Codex approval, Controller validation, actor authority,
leases, bindings, or revision CAS. Installation SHALL NOT silently grant blanket
mutation approval or rewrite unrelated user MCP policy.

#### Scenario: A host uses annotations for approval

- **WHEN** a supporting host distinguishes read tools from mutations
- **THEN** the stable annotations allow that distinction while the Controller remains the only mutation authority

#### Scenario: A caller treats idempotent metadata as a retry guarantee

- **WHEN** a non-idempotent mutation response is lost
- **THEN** documentation requires read-after-write recovery and does not authorize blind replay based on tool metadata

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-guidance-and-context/spec.md`

## Purpose

Define how the MCP server supplies sufficient, versioned, bounded guidance for the
current Dev Flow action without requiring Codex to read packaged Skills, Hook source,
CLI source, MCP implementation source, or raw task state.

## ADDED Requirements

### Requirement: Initialization instructions establish the complete global authority rule

The MCP server SHALL publish one initialization instruction string no larger than
4 KiB UTF-8. Its first 512 characters SHALL be self-contained and SHALL state that:

- the Controller is the only Dev Flow task-state writer;
- the client must discover or select one task before starting or resuming;
- the client must obtain exactly one current action;
- only that action may be performed across the immutable repository set;
- a mutation must submit the exact current binding and closed payload;
- stale, ambiguous, unavailable, or terminal authority must not be guessed;
- direct task-state file access is unsupported.

The remaining instruction text MAY explain the stable tool sequence and residual
local-shell boundary, but SHALL NOT embed the full workflow manuals, payload examples
for every action, implementation details, or content already available through tool
schemas.

#### Scenario: A client reads only the first 512 characters

- **WHEN** a host surfaces only the bounded leading server instructions
- **THEN** the client still receives the complete authority and sequencing rule needed to avoid starting, selecting, or applying work implicitly

#### Scenario: Instructions exceed the budget

- **WHEN** candidate instructions exceed 4 KiB or require text after byte 512 to understand the authority rule
- **THEN** package validation fails

### Requirement: Current-action guidance is generated only for the live projected action

`dev_flow_get_next_action` and successful mutation results SHALL include a bounded
action guidance object with schema `dev-flow-mcp-guidance/1.0.0`. Guidance SHALL be
selected from a versioned package catalog by the current action kind, projected
payload contract, workspace role, optional driver, obligation kind, and review
contract. It SHALL be generated only after the live Controller projection is valid.

Guidance SHALL include:

- `objective`: the exact outcome of the current action;
- `must_read`: projected contract, repositories, inputs, resources, obligations, and
  other current fields that must be inspected;
- `allowed_effects`: whether the action is read-only, source-producing, or
  source-verifying;
- `required_evidence`: the projected evidence and provenance that must be returned;
- `payload_notes`: semantic rules not expressible in JSON Schema;
- `driver`: exact optional-tool and fallback rules when applicable;
- `stale_recovery`: the safe refresh behavior;
- `completion_rule`: how to recognize Controller-confirmed progress or terminal state;
- `guidance_digest`: a lowercase SHA-256 over the canonical guidance object excluding
  its digest field.

Guidance SHALL NOT describe a different workflow phase, include another action's
payload, authorize unprojected retries, or substitute for the exact action binding.

#### Scenario: The current action is preflight

- **WHEN** the Controller projects `task.preflight`
- **THEN** guidance instructs only the bounded read-only preflight and an empty payload and does not include implementation or review procedures

#### Scenario: The current action changes source

- **WHEN** the projected workspace role is `produces-source`
- **THEN** guidance states the exact starting snapshot, change-ownership claims, repository scope, governing resources, and successor evidence required by that action

#### Scenario: The current action changes concurrently

- **WHEN** the task advances after guidance is returned
- **THEN** the guidance and binding are treated as stale together and the caller must refresh rather than reuse guidance against a new action

### Requirement: Normal MCP journeys do not require package-source reading

For every official workflow action, the combination of initialization instructions,
tool descriptions, generated input schema, compact current-action projection, and
action guidance SHALL contain enough information for a capable Codex executor to
perform and submit the action correctly. Public guidance SHALL explicitly state that
reading `skills/`, `hooks/`, `src/dev_flow_orchestrator/cli.py`, MCP adapter source,
launcher scripts, or Controller task-state files is neither required nor an accepted
normal step.

Installed journey validation SHALL observe model-facing file reads or equivalent
instrumented access and SHALL fail when a normal workflow reads package source to
discover invocation syntax, payload fields, sequencing, fallback behavior, or task
state. Repository source reads required to implement, verify, or review the user's
actual task remain allowed.

#### Scenario: Codex starts an installed feature journey

- **WHEN** the server and tools are available and the user supplies a requirement and prepared repositories
- **THEN** the journey can discover/start, obtain, execute, and apply every action without opening legacy Skill, Hook, CLI, MCP, or state implementation files

#### Scenario: Required semantics are absent from guidance

- **WHEN** an installed journey must inspect package source to determine a required payload field or workflow rule
- **THEN** validation fails and the missing semantic must be moved into schema, projection, or bounded guidance

### Requirement: Action guidance preserves task-change ownership rules

For every source-producing action, guidance SHALL require the executor to compare the
bound starting snapshot with the current complete repository-set evidence and submit
current `dev-flow-task-change-claims/0.4.0` for every and only task-owned observed
changed path. It SHALL require repository ID, relative path, classification,
criterion IDs, and purpose as defined by the current model. It SHALL prohibit silent
adoption of ambient drift, omission of a changed member, and direct editing of
Controller state.

For context and source-verifying actions, guidance SHALL prohibit source mutation.
For source-producing planning, guidance SHALL preserve the current governing and
reported resource rules, including repository-scoped identity and the semantic
OpenSpec tasks normalizer where applicable.

#### Scenario: Ambient drift exists

- **WHEN** a source-producing action observes a changed path not owned by the current task
- **THEN** guidance requires explicit current ownership handling or a fresh Controller path and does not authorize claiming the drift silently

#### Scenario: A verification action changes a repository

- **WHEN** a `verifies-source` action causes a member snapshot change
- **THEN** the action binding becomes invalid and the result cannot be recorded as current verification evidence

### Requirement: Optional-driver guidance is explicit and truthful

When the current action declares OpenSpec, codebase-memory, or independent-review as
an optional driver, guidance SHALL identify the exact tool, phase, required output or
evidence type, source-confirmation rules, current binding inputs, and declared
fallback. The executor SHALL use the named driver only when available and SHALL
record `available`, `degraded`, or `unavailable` truthfully in the current
`dev-flow-driver-result/0.4.0` envelope.

Guidance SHALL never describe fallback evidence as the named driver's result. Missing,
stale, partial, degraded, unavailable, unconfirmed, or internally inconsistent impact
evidence SHALL remain `unknown` for current assurance planning. The MCP server SHALL
not dynamically load or execute those external drivers itself in this change.

#### Scenario: OpenSpec is available

- **WHEN** a planning action declares OpenSpec and the tool is available
- **THEN** guidance requires current machine-readable status and instructions, concrete returned paths, governing resource bindings, and truthful driver provenance

#### Scenario: Codebase-memory is stale for one member

- **WHEN** a current graph generation cannot be matched to the member workspace
- **THEN** guidance requires degraded status, direct source confirmation as fallback, and conservative impact rather than focused assurance based on stale graph output

#### Scenario: The optional driver is unavailable

- **WHEN** a declared tool cannot be invoked
- **THEN** guidance identifies the exact fallback and limitations and never fabricates named-tool evidence

### Requirement: Assurance guidance executes only the current obligation

At assurance dispatch, guidance SHALL identify exactly the projected
`current_obligation`, its fingerprint, evidence contract, repository and integration
scope, task-change slice, prerequisites, remaining per-obligation attempts, applicable
class ceilings, and total-action authority. It SHALL direct the executor to run only
the smallest command or manual check required by that obligation and SHALL prohibit
undeclared retries or aggregate verdict submission.

Passing evidence MAY be reused only when the Controller projects current reuse for an
unchanged governing fingerprint and disjoint task-change slice. Intersecting or
ambiguous source changes, governing-resource changes, impact-closure changes, or
prerequisite changes SHALL require fresh projected evidence. A `not-required`
dimension SHALL remain a Controller decision.

#### Scenario: One focused repository obligation is current

- **WHEN** the plan projects one member-local repository check and no integration or review action
- **THEN** guidance requests only that check and preserves the Controller's not-required reasons for all other dimensions

#### Scenario: An attempt fails

- **WHEN** the current obligation execution fails, is incomplete, or is unavailable
- **THEN** guidance requires recording that actual result once and following the fresh projection rather than running an undeclared retry

#### Scenario: Existing evidence intersects later source change

- **WHEN** later task-owned changes intersect the evidence slice or invalidate a prerequisite
- **THEN** guidance treats the evidence as stale unless the Controller explicitly projects current reuse

### Requirement: Independent-review guidance has a stable package identity

When the current action requires independent review, guidance SHALL bind the exact
review contract, task ID, contract digest, plan digest, manifest digest, repository
set, per-member base/current evidence, aggregate workspace digest, current input
artifact manifest, and governing guidance/resource manifest. The package guidance
catalog used for review SHALL have a stable canonical digest. The projected review
contract SHALL expose that digest so current `dev-flow-review-finding/0.4.0` values
can bind the actual guidance reviewed without requiring a Skill file.

Guidance SHALL require one genuinely separate reviewer context for independent
assurance, complete task-wide review over every member and cross-repository behavior,
structured causal findings, and a fresh aggregate snapshot. Self-review MAY report
truthful findings but SHALL NOT claim independent approval. The Controller SHALL
remain verdict authority.

#### Scenario: A stable independent review passes

- **WHEN** a separate reviewer inspects the exact current aggregate inputs and returns no unresolved blocking, triage, or impact-gap finding
- **THEN** the result binds the projected guidance digest and the Controller may derive approval for that obligation

#### Scenario: Review guidance changes during a release

- **WHEN** any normative review instruction changes
- **THEN** its package guidance digest changes, package tests update, and stale findings bound to the old digest cannot be applied to the new projected contract

#### Scenario: No separate reviewer is available

- **WHEN** only the current executor can inspect the change
- **THEN** guidance requires unavailable independent assurance or truthful self-review and leaves satisfaction to current waiver and budget rules

### Requirement: Guidance and model context are release-bounded

The complete stable `tools/list` representation SHALL be no larger than 32 KiB
UTF-8. Each tool description SHALL be no larger than 512 UTF-8 bytes. One action
guidance object SHALL be no larger than 8 KiB. One text content summary SHALL be no
larger than 4 KiB unless an existing smaller domain bound applies. Server-info text
SHALL be no larger than 1 KiB. List and discovery summaries SHALL be paginated and
bounded as specified by the tool capability.

No response SHALL duplicate complete structured JSON in text, return a full ledger or
raw path inventory by default, truncate an action binding, or silently omit a field
needed to perform the current action. If a required exact result cannot fit its
bound, the tool SHALL fail with `MCP_RESULT_LIMIT` and a safe recovery statement.

#### Scenario: A current action fits the budget

- **WHEN** the exact binding, required current fields, and guidance fit their declared limits
- **THEN** the complete action is returned without unrelated workflow manuals or duplicate JSON text

#### Scenario: A required action exceeds the budget

- **WHEN** exact safe execution data would exceed the MCP result bound
- **THEN** the tool fails atomically with `MCP_RESULT_LIMIT` and does not return a truncated or apparently usable action

#### Scenario: Tool metadata grows

- **WHEN** a catalog change causes the serialized tool list or a description to exceed its release gate
- **THEN** package validation fails before installation

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/mcp-plugin-packaging/spec.md`

## Purpose

Define how Dev Flow is distributed as an MCP-first Codex plugin and as an optional
standalone local MCP server while preserving authoritative source verification,
managed runtime ownership, user approval, duplicate-registration safety, and task
data.

## ADDED Requirements

### Requirement: The Codex plugin bundles the local MCP server as its interaction surface

The plugin manifest SHALL retain product name `dev-flow-orchestrator`, the single
`RELEASE_VERSION`, marketplace identity, author, license, and documentation metadata.
It SHALL declare an MCP server through the supported `mcpServers` reference to a root
`.mcp.json` file or the current equivalent plugin packaging contract. The MCP
configuration SHALL launch the installed Dev Flow MCP launcher in STDIO mode and
SHALL NOT embed machine-specific absolute paths, secrets, user tokens, network URLs,
or a second data namespace.

After MCP parity and installed-journey gates pass, the package SHALL no longer expose
Dev Flow Skills or command Hooks as current model-facing workflow authority. The
package validator SHALL reject a candidate that simultaneously advertises the new
MCP-first interface and installs the legacy `follow-dev-flow`,
`analyze-change-impact`, `review-dev-flow-change`, SessionStart, UserPromptSubmit, or
PreToolUse interaction path.

#### Scenario: The installed plugin is discovered

- **WHEN** Codex loads the verified plugin snapshot
- **THEN** it discovers one bundled `dev-flow` local STDIO MCP server and the stable tool catalog without requiring a Skill invocation or Hook trust step

#### Scenario: The MCP manifest is missing or unsafe

- **WHEN** `.mcp.json` is absent, malformed, references a network transport, contains a secret, or resolves outside validated installed assets
- **THEN** package validation or plugin activation fails before reporting a healthy MCP installation

#### Scenario: Legacy authority remains packaged

- **WHEN** the candidate retains installed workflow Skills or command Hooks after the MCP removal gate
- **THEN** package validation fails because two conflicting model-facing authorities would exist

### Requirement: The installed launcher resolves owned runtime and data paths natively

The package SHALL provide one POSIX launcher and one Windows launcher that preserve
argument boundaries, locate the installer-owned MCP runtime, start the same MCP
bootstrap with UTF-8 behavior, and require no shell-language emulation on the other
host. The launcher SHALL resolve the current Controller data root through the shared
resolver and SHALL pass no data-root path through model-visible configuration or
output.

A launcher SHALL fail before protocol initialization when the managed runtime is
missing, its receipt does not match the active source candidate, its locked
dependencies are inconsistent, or no supported 64-bit CPython 3.10–3.14 interpreter
can execute it. A failed launch SHALL not create or mutate task state merely to
diagnose installation.

#### Scenario: POSIX plugin path contains spaces or Unicode

- **WHEN** Codex starts the installed server from a supported macOS path containing spaces or valid Unicode
- **THEN** the POSIX launcher preserves the exact bootstrap and argument boundaries and initializes STDIO successfully

#### Scenario: Windows plugin path contains spaces or Unicode

- **WHEN** Codex starts the installed server from a supported Windows path containing spaces or valid Unicode
- **THEN** the native Windows launcher starts the same server without WSL, Git Bash, or Cygwin

#### Scenario: The managed runtime is inconsistent

- **WHEN** the runtime receipt, source commit, release version, Python identity, or locked dependency metadata does not match the active installation
- **THEN** launch fails with a bounded stderr diagnostic and emits no invalid MCP stdout

### Requirement: The MCP runtime is an isolated installer-owned asset

Installers SHALL create or update a managed runtime in an installer-owned location
outside the verified source checkout, outside every Controller data root, and outside
user repositories. They SHALL install the candidate's exact locked runtime set and
write a bounded ownership receipt containing product identity, source commit,
release version, Python identity, lock digest, runtime location identity, and creation
or update action.

Runtime replacement SHALL be staged and validated before activation. An existing
healthy runtime MAY be reused only when its receipt and installed metadata exactly
match the candidate. Failed staging SHALL leave the prior active runtime and task
data intact. The source checkout SHALL remain clean and SHALL not acquire a local
virtual environment or generated dependency files as a side effect of installation.

#### Scenario: A fresh runtime is provisioned

- **WHEN** source verification and package validation succeed and no matching runtime exists
- **THEN** the installer creates a staged isolated runtime, installs the lock, validates the MCP bootstrap, atomically activates it, and records ownership

#### Scenario: An installation is repaired idempotently

- **WHEN** the verified source and runtime receipt already match the candidate
- **THEN** the installer validates and reuses or deterministically repairs the owned runtime without changing task data

#### Scenario: Runtime staging fails

- **WHEN** dependency installation, import smoke, protocol smoke, or receipt validation fails
- **THEN** plugin activation is not reported as successful and the previous validated runtime and Controller data remain unchanged

### Requirement: Bundled and standalone registration are mutually exclusive

The supported default SHALL be bundled plugin registration. An operator MAY instead
register the same installed launcher as one standalone local STDIO MCP server through
the documented Codex MCP configuration path. The installer SHALL NOT create both
registrations automatically and SHALL NOT modify an unrelated user MCP server.

Installation, repair, validation, and public diagnostics SHALL detect an active
standalone Dev Flow registration when bundled mode is being enabled, and SHALL detect
an active bundled registration when standalone setup is requested. The operation
SHALL fail or require the documented explicit operator resolution before claiming a
healthy state. Detection SHALL compare the Dev Flow identity and launcher target,
not merely a generic server name.

#### Scenario: Only bundled mode is configured

- **WHEN** the plugin owns the active Dev Flow MCP registration and no standalone duplicate exists
- **THEN** health checks report one server identity and normal activation proceeds

#### Scenario: Both modes are active

- **WHEN** the same product would be started from bundled and standalone registrations
- **THEN** installation or health validation reports a duplicate, identifies the two configuration surfaces, and does not claim deterministic task authority

#### Scenario: An unrelated MCP server has a similar name

- **WHEN** another user server name contains `dev-flow` but does not resolve to the owned product identity or launcher
- **THEN** the installer preserves it and does not delete or rewrite it automatically

### Requirement: MCP approval remains user and host authority

Plugin installation SHALL register the server but SHALL NOT silently grant blanket
approval for its mutation tools, rewrite unrelated global MCP approval settings, or
represent tool annotations as authorization. The candidate SHALL provide a bounded
plugin-scoped recommended policy that allows practical use while leaving final
approval behavior to Codex and the operator.

Installation receipts and public documentation SHALL state which tools are read-only,
which mutate or terminate Controller state, that a user should review the installed
MCP identity and tool catalog, and that the former Hook trust step and PreToolUse
guard no longer apply. A successful install SHALL distinguish source verification,
runtime health, plugin activation, MCP visibility, and remaining user approval.

#### Scenario: Installation succeeds but a mutation needs approval

- **WHEN** Codex exposes the server but host policy requires approval for `dev_flow_start_task` or another mutation
- **THEN** documentation treats the prompt as expected host authority rather than an MCP runtime failure

#### Scenario: Installer attempts to grant blanket approval

- **WHEN** an implementation would edit unrelated user policy or approve all Dev Flow tools without explicit operator control
- **THEN** package or lifecycle validation fails

### Requirement: Activation proves the installed MCP artifact rather than source-only code

After source, package, and managed-runtime validation, each supported installer SHALL
activate the plugin and run an installed-artifact MCP smoke. The smoke SHALL invoke
the actual installed launcher and runtime, complete initialize, inspect bounded
instructions, list the exact tool catalog, call `dev_flow_server_info`, and shut down
cleanly. A source-tree import or mocked protocol exchange SHALL NOT substitute for
this activation proof.

Activation failure SHALL be explicit and recoverable. The installer SHALL return
nonzero, preserve the verified source and task data, preserve a previously working
runtime where possible, and print exact bounded recovery commands for plugin and MCP
inspection. It SHALL never report success merely because plugin registration
completed before the server failed.

#### Scenario: The installed smoke succeeds

- **WHEN** the real installed launcher initializes, lists the expected catalog, and returns matching server identity
- **THEN** the receipt may report MCP activation healthy

#### Scenario: Plugin registration succeeds but MCP startup fails

- **WHEN** Codex accepts the plugin yet the installed launcher or runtime cannot initialize
- **THEN** installation exits unsuccessfully and reports plugin activation and MCP health as separate states

### Requirement: Uninstallation removes only validated MCP installation assets

Uninstallers SHALL remove the installed plugin when present, atomically remove only
the Dev Flow marketplace entry from a valid marketplace, and remove only the
validated installer-owned MCP runtime and launch assets. They SHALL preserve all
Controller task data and unrelated MCP registrations by default.

Source-checkout deletion SHALL retain the current fail-closed validation over product
identity, allowed origin, attached authoritative branch, tracked/untracked/ignored
content, and local-only commits. A keep-source option SHALL preserve the source. A
keep-runtime option MAY be offered only when it is explicit and does not leave a
registration that claims a removed product. Any uncertainty about runtime or source
ownership SHALL leave that asset for manual handling rather than deleting it.
If an independently managed standalone Dev Flow registration still resolves to the
installer-owned launcher or runtime selected for removal, uninstallation SHALL fail
closed before removing those shared assets and SHALL require the operator to disable
or remove the standalone registration explicitly. It SHALL not leave a dangling
registration and SHALL not edit unrelated registration policy automatically.

#### Scenario: Ordinary uninstall succeeds

- **WHEN** plugin, marketplace entry, managed runtime, launch assets, and source are all validated as installer-owned and safe to remove
- **THEN** those installation assets are removed and the receipt states that task data was preserved

#### Scenario: Runtime ownership is uncertain

- **WHEN** the runtime receipt is missing, inconsistent, or points outside the expected owned location
- **THEN** uninstallation refuses to delete that runtime, continues only with independently safe removals, and reports manual cleanup without touching task data

#### Scenario: A standalone registration exists

- **WHEN** a standalone Dev Flow MCP registration is not owned by the plugin installer
- **THEN** plugin uninstall preserves it and, when it references an otherwise removable Dev Flow launcher or runtime, preserves those shared assets and requires explicit operator cleanup rather than leaving a dangling registration

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/personal-delivery-workflows/spec.md`

## Purpose

Move the model-facing execution of the existing personal delivery workflows from
packaged Skills and Hook-injected CLI locators to the stable MCP current-action
interface without changing workflow definitions, task topology, assurance policy,
budgets, records, or terminal Dossiers.

## ADDED Requirements

### Requirement: Official workflow execution is MCP-first

The `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full` workflows
SHALL remain current `dev-flow-workflow/0.4.0` definitions governed by the existing
Controller and assurance policy. In the installed `0.5.0` product, a Codex executor
SHALL start or discover a task through the stable MCP tools, obtain one live current
action through `dev_flow_get_next_action`, perform only that action across the exact
immutable repository set, and submit the exact action ID, closed payload, and
unmodified binding through `dev_flow_apply_action` or the applicable governance tool.

Workflow execution SHALL NOT require `$follow-dev-flow`, a Hook-injected Controller
locator, shell construction of the CLI, or direct task-state access. The MCP adapter
SHALL NOT auto-run repository edits, tests, external drivers, or review; the Codex
executor continues to perform the projected work with its ordinary repository and
optional-tool capabilities. One task SHALL retain one current action and one executor
regardless of the number of MCP requests or repository members.

#### Scenario: A user starts each official workflow through MCP

- **WHEN** a caller invokes `dev_flow_start_task` with any official workflow and a valid exact repository set
- **THEN** the Controller pins the same workflow identity and projects the same preflight action and current-model contract as the CLI path

#### Scenario: A workflow resumes after the MCP process restarts

- **WHEN** the local MCP process exits and a later process opens the same current data namespace
- **THEN** `dev_flow_find_tasks_for_path` and `dev_flow_get_next_action` resume the persisted task from its authoritative revision without session memory or workflow reconstruction

#### Scenario: An executor tries to skip the current action

- **WHEN** a caller submits an action ID or payload not projected for the current node
- **THEN** existing action and binding validation rejects it and no later workflow phase is entered

#### Scenario: A task reaches terminal delivery

- **WHEN** all current obligations and finalization rules succeed or an absolute budget routes to incomplete delivery
- **THEN** the same current Delivery Dossier authority reports `DONE` or `INCOMPLETE`; MCP adds no separate terminal model

### Requirement: Current action guidance replaces procedural Skill authority

For every official action template, the package SHALL provide bounded
`dev-flow-mcp-guidance/1.0.0` selected from the live projection. The guidance SHALL
preserve all current execution rules previously carried by the packaged Skills,
including repository-set completeness, source ownership claims, workspace roles,
resource bindings, optional-driver provenance, focused assurance, review causality,
contract-revision behavior, cancellation authority, absolute attempts, and terminal
verification.

Tool schemas and guidance SHALL be the model-facing authority for invocation shape.
They SHALL not change domain semantics or become persisted workflow inputs except
where a current review contract explicitly binds the stable package guidance digest.
A change to workflow semantics SHALL still be made in the Controller/workflow
capabilities rather than hidden only in MCP prose.

#### Scenario: Action guidance and workflow disagree

- **WHEN** package validation finds guidance that permits an effect, payload, retry, or transition forbidden by the current workflow projection
- **THEN** the candidate fails rather than treating guidance as a second workflow authority

#### Scenario: Guidance omits a required current rule

- **WHEN** an installed journey must read legacy Skill or implementation source to complete a projected action correctly
- **THEN** the candidate fails and the missing rule must be expressed in the projection, schema, or bounded guidance

## MODIFIED Requirements

### Requirement: Optional drivers have an explicit degraded path

An official workflow action template that names an optional OpenSpec,
codebase-memory, or independent-review driver SHALL declare its tool, produced
artifact or evidence type, fallback instructions, and the assurance obligations that
can require it. The runtime SHALL project driver metadata only when the current
action is required by an outstanding obligation and SHALL NOT dynamically load or
execute driver code.

The current MCP action guidance SHALL direct the Codex executor to use the named tool
when available or follow the declared fallback and record the actual driver status.
`available` SHALL mean the named tool produced evidence for the bound inputs;
`degraded` SHALL mean the declared fallback or materially incomplete supporting
coverage was used; and `unavailable` SHALL mean the named assurance could not be
produced. Fallback evidence SHALL NOT be described as the named tool's result.

Degraded, partial, stale, unavailable, unconfirmed, internally inconsistent, or
otherwise incomplete impact evidence SHALL normalize to `unknown` and SHALL invoke
the current conservative assurance result. Review evidence SHALL distinguish
`independent` and `self` assurance, but the Controller SHALL derive satisfaction,
rework, causal triage, impact-gap reentry, disposition, waiver, or exhaustion from the
current review obligation, structured findings, causal status, and absolute budgets
rather than trusting an executor-supplied aggregate outcome.

#### Scenario: Optional tool is available

- **WHEN** Codex can invoke the current action's named optional tool
- **THEN** the submitted driver result records that tool, current phase, bound inputs, concrete evidence, and limitations

#### Scenario: Optional tool is unavailable

- **WHEN** a required optional tool cannot be invoked
- **THEN** current MCP guidance provides the declared fallback, the executor records degraded or unavailable status truthfully, and the obligation's completion requirements remain intact

#### Scenario: Independent tool approves

- **WHEN** an independent-review driver produces current evidence with no unresolved blocking finding, causal-triage state, or impact gap for the exact task-change slice
- **THEN** the Controller marks that review obligation satisfied and does not project duplicate review for the same current fingerprint

#### Scenario: Fallback self-review finds changes

- **WHEN** independent review is unavailable and truthful self-review reports a current blocking `introduced` or `affected` finding
- **THEN** the Controller records self assurance and projects only the finding-bound route permitted by current obligations and absolute budgets

#### Scenario: Fallback review cannot establish causality

- **WHEN** independent or fallback review reports a current blocking finding with `unknown` causal relation
- **THEN** the Controller derives `triage-required` and permits only projected bounded causal refresh or an authorized disposition before approval or source rework

#### Scenario: Fallback cannot provide independence

- **WHEN** self-review finds no unresolved blocker but the plan requires independent review and no exact current assurance waiver exists
- **THEN** the independent-review obligation remains outstanding and follows its recorded execution and exhaustion rules

#### Scenario: Operator waives unavailable independent review

- **WHEN** the named driver records unavailable independent assurance and an exact current authorized assurance waiver governs that obligation
- **THEN** the Controller may mark it waived while the Dossier reports the actor, rationale, and remaining risk and never labels self-review as independent approval

#### Scenario: Optional review is not required

- **WHEN** the current assurance plan marks independent review not required
- **THEN** no independent-review driver action or fallback self-review is projected merely because the driver exists

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/task-discovery-boundaries/spec.md`

## Purpose

Replace automatic Hook context injection with explicit bounded MCP discovery while
preserving current inventory isolation, path canonicalization, active membership
leases, ambiguity handling, and fail-closed admission.

## MODIFIED Requirements

### Requirement: Active task discovery covers every member repository

Repository-path discovery SHALL match a non-terminal task when the inspected path
equals or is contained by any canonical member repository root. Discovery SHALL
return each matching task at most once. Valid model `0.4.0` task creation SHALL
prevent active worktree overlap, so a healthy current inventory SHOULD produce at
most one active match for a canonical member path.

The installed MCP product SHALL expose this behavior through
`dev_flow_find_tasks_for_path`. The tool SHALL return a closed classification of
`none`, `single`, `ambiguous`, or `inventory-unavailable`, bounded task identities,
and current inventory diagnostics. It SHALL NOT inject hidden authority into the
session, select an ambiguous task, create a task, or create a live action binding by
default. A caller SHALL explicitly select the returned task ID and obtain its current
action before mutation.

If persisted valid current task state nevertheless contains conflicting active
membership, discovery SHALL report an explicit lease-integrity conflict and SHALL
NOT choose one task implicitly. If a current-namespace entry cannot be validated,
discovery SHALL isolate and report it without treating it as task authority or
released membership; task admission SHALL remain globally fail closed until the
current lease inventory is valid. Terminal tasks SHALL remain excluded from active
automatic matching.

#### Scenario: MCP discovery isolates corrupt current state

- **WHEN** `dev_flow_find_tasks_for_path` encounters a corrupt model `0.4.0` task entry while inspecting a repository path
- **THEN** it returns no authority from that entry, exposes bounded diagnostics, and does not imply that its membership lease was released

#### Scenario: MCP discovery starts in a secondary repository

- **WHEN** a client supplies a path at or below any non-first member repository of one active task
- **THEN** discovery returns that same task once and the caller can explicitly request its current action

#### Scenario: One task has multiple matching roots

- **WHEN** a candidate path could otherwise match more than one member record of the same task
- **THEN** discovery returns that task once

#### Scenario: Valid active task overlap is detected

- **WHEN** inventory contains two valid non-terminal current tasks that claim the same canonical member despite admission enforcement
- **THEN** discovery reports a lease-integrity conflict with both task IDs and selects neither as implicit authority

#### Scenario: Multiple tasks cover the inspected path

- **WHEN** multiple non-terminal tasks are returned for a path because of persisted conflicting state or another current ambiguity
- **THEN** discovery reports `ambiguous`, retains all bounded task identities, and requires explicit operator resolution

#### Scenario: Matching task is terminal

- **WHEN** the only task containing the inspected path is `DONE`, `INCOMPLETE`, or `CANCELLED`
- **THEN** active discovery returns `none` and the worktree may be considered for a new task only after complete admission checks

#### Scenario: Discovery is requested with a different Windows spelling

- **WHEN** the inspected Windows path differs from an active member only by supported drive-letter case, separator, or redundant-component spelling
- **THEN** discovery uses the existing canonical comparison and returns the same active task

#### Scenario: Discovery has no match

- **WHEN** the canonical path is outside every healthy non-terminal member
- **THEN** the tool returns `none` without starting a task or acquiring a membership lease

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/package-delivery-validation/spec.md`

## Purpose

Replace package release gates that treat Skills and Hooks as current model-facing
authority with equally strict MCP protocol, tool, guidance, installation, compatibility,
and installed-journey evidence while preserving every current workflow, assurance,
repository, model-version, and boundary guarantee.

## RENAMED Requirements

- FROM: `### Requirement: Public skill guidance matches the current product`
- TO: `### Requirement: Public MCP guidance matches the current product`

## MODIFIED Requirements

### Requirement: Public MCP guidance matches the current product

The packaged server instructions, stable tool descriptions, generated input and
output schemas, action-guidance catalog, plugin metadata, and public operator
documentation SHALL describe compatibility model `0.4.0` and one exact set of one to
eight user-prepared local Git worktrees. Together they SHALL explain:

- official workflow selection;
- exact repository-set admission and active member leases;
- one task, one current action, and one Codex executor;
- structured delivery contracts and contract revision;
- immutable preflight ownership origin and roll-forward task-change claims;
- ambient drift and exact ownership adoption;
- task-scoped assurance plans, current obligations, closed risk triggers, evidence
  reuse, and absolute recorded-attempt and total-action budgets;
- optional OpenSpec, codebase-memory, and independent-review driver provenance and
  fallback;
- structured causal findings, `triage-required`, impact-gap planning reentry,
  decisions, waivers, dispositions, and Delivery Dossier completion;
- repository-mismatch stop and explicit cancellation authority;
- the non-goals of branch/worktree management, Git publication, parallel executors,
  and external CI/PR/release effects;
- the loss of the old PreToolUse guard and the bounded MCP/local-shell trust model.

The MCP interface SHALL direct the executor to run only the current projected action
and, within assurance, only the current obligation and smallest declared check. It
SHALL NOT authorize undeclared retries, reuse stale or intersecting evidence, convert
an adjacent observation into a blocking causal finding, claim ambient drift without
complete ownership claims, or present a non-required dimension as completed
assurance. Only source-confirmed impact MAY support focused assurance; degraded,
partial, stale, unavailable, unconfirmed, inconsistent, or unknown impact SHALL use
the conservative policy.

After the executor confirms that immutable repository membership cannot satisfy the
accepted contract, current guidance SHALL require it to stop, identify the exact
active task, and obtain explicit user authority for cancellation unless that
specific authority is already present. Cancellation SHALL use
`dev_flow_cancel_task` only at a declared stage, and completion SHALL be reported
only after Controller authority states `done: true`, `status: CANCELLED`, and
`current_node: cancelled`. Failure or unavailability SHALL preserve active state and
leases.

Normal guidance SHALL NOT tell Codex to invoke `$follow-dev-flow`, read packaged Skill
or Hook files, construct a Controller locator, call the CLI through a shell, or read
Controller state directly. A CLI recovery document MAY describe the retained
operator CLI but SHALL distinguish it from normal MCP execution.

#### Scenario: Packaged MCP metadata is inspected

- **WHEN** package validation reads initialization instructions, tool metadata, schemas, guidance, plugin configuration, and public documentation
- **THEN** stale version, schema, workflow, namespace, ownership, assurance, finding, budget, topology, executor, approval, or cancellation guidance causes validation to fail

#### Scenario: Multi-repository start guidance is inspected

- **WHEN** package validation examines `dev_flow_start_task`
- **THEN** its schema and guidance require one to eight exact roots, canonical exact-set semantics, active member leases, user-prepared worktrees, and one executor

#### Scenario: Focused obligation is projected

- **WHEN** a current plan requires one focused repository check and no integration or review obligation
- **THEN** action guidance requests only that obligation and preserves explainable not-required decisions

#### Scenario: Adjacent review observation is found

- **WHEN** independent review reports a pre-existing, out-of-scope, or non-blocking unknown-causal observation
- **THEN** guidance records it truthfully and does not request task rework or expand the contract

#### Scenario: Blocking review causality is unknown

- **WHEN** review reports a current blocking finding whose causal relation is unknown or disputed
- **THEN** guidance preserves `triage-required`, follows only projected bounded causal refresh, and claims neither approval nor direct source rework without governed relation or authorized disposition

#### Scenario: Review identifies an impact gap

- **WHEN** source evidence proves an affected relation outside the current plan closure
- **THEN** guidance follows plan invalidation and impact/planning reentry under the same contract and requests contract revision only when accepted scope or criteria change

#### Scenario: Repository mismatch lacks cancellation authority

- **WHEN** immutable membership cannot satisfy the accepted requirement and no explicit cancellation authority exists
- **THEN** guidance stops the executor and reports that the task and leases remain active

#### Scenario: Repository mismatch cancellation is authorized

- **WHEN** exact cancellation authority exists and the current stage declares cancellation
- **THEN** guidance invokes the MCP cancellation tool and reports completion only from terminal Controller output

#### Scenario: Legacy source-reading guidance remains

- **WHEN** any installed model-facing asset instructs normal execution through Skills, Hooks, shell CLI locators, or plugin-source inspection
- **THEN** package validation fails

### Requirement: Candidate validation proves supported repository topology

The candidate package SHALL expose authoritative current capability definitions for
repository topology, active leases, task-change ownership, assurance planning,
finding governance, absolute budgets, MCP runtime, MCP tools, action guidance,
managed installation, and task-data preservation. Validation SHALL exercise the
actual candidate root rather than already imported invoking-checkout modules.

Validation SHALL cover:

- core Controller, Store, Git, workflow, delivery, review, and replay behavior;
- strict JSON CLI recovery behavior and local read-only Web UI behavior;
- MCP initialization, instructions, `tools/list`, every stable `tools/call`, output
  schemas, annotations, cancellation, errors, shutdown, and restart;
- official and custom workflow validation;
- one-member and larger exact repository sets, secondary-member discovery,
  pre-existing dirty baselines, staged/unstaged/untracked task changes, ambient drift,
  governing resources, selective evidence reuse, findings, dispositions, exhaustion,
  and aggregate Dossier generation;
- macOS and Windows installed launchers and lifecycle entry points;
- managed-runtime ownership, exact dependency lock, plugin packaging, duplicate
  bundled/standalone registration detection, and public documentation;
- strict release/model identity separation and retained prior-namespace isolation.

Every official workflow SHALL continue to embed the exact closed
`dev-flow-assurance-policy/0.4.0`. Validation SHALL prove the exact supported trigger
IDs `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`,
`cross-repository-contract`, `installer`, and `protocol`, and SHALL reject an
additional free-form trigger. A custom policy MAY strengthen a base profile, require
review, reduce allowances, or reduce ceilings; it SHALL NOT remove a base obligation,
weaken unknown-impact or risk-trigger expansion, or raise a product maximum.

Only current source-confirmed impact SHALL permit focused obligations. Every missing,
stale, degraded, partial, unavailable, unconfirmed, inconsistent, or otherwise
unknown result SHALL expand to the current conservative every-member, declared-or-
applicable integration, independent-review, documentation, and manual-evidence rules
for the selected profile and criteria. Canonical grouping SHALL remain at most one
repository check per required member, one integration check per distinct evidence
contract over sorted required boundaries, and at most one documentation,
manual-evidence, and independent-review obligation per plan.

With `V` required non-review obligations, `R` required independent-review
obligations, `A = 2` for every profile except `full`, `A = 3` for `full`, and `U`
equal to the sum of `max(allowance - 1, 0)` for source-rework-capable obligations in
the initial conservative reservation set, validation SHALL prove these exact
ceilings:

| Profile | `verification_ceiling` | `review_ceiling` | `rework_ceiling` |
| --- | --- | --- | --- |
| `lite`, `investigation` | `min(A × V, V + 1)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(1, U)` |
| `feature`, `bugfix`, `refactor` | `min(A × V, V + 2)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(2, U)` |
| `full` | `min(A × V, V + 4)` | `min(A × R, R + 2)` | `min(4, U)` |

Validation SHALL prove `rework_ceiling = 0` when `U = 0`, the exact value below a
profile cap, and the cap when `U` meets or exceeds it. One review result SHALL group
all current blocking causal findings into one finding-bound source-rework obligation
against the governing review obligation's next unused retry unit. Materialization
SHALL create no free authority; execution SHALL consume exactly one reserved retry,
one rework unit, and one total-action unit as currently defined. Restart and
same-contract replacement SHALL preserve the original reservation set, `U`, ceilings,
and consumption. Only a new contract digest SHALL derive a new bounded plan.

The total-action ceiling SHALL remain the exact sum of reachable fixed mutations,
all three class ceilings, exact product-bounded reserve for every reachable unique
waiver, finding disposition, persisted-reuse decision, and prerequisite-refresh
subject, and one non-cancelled Dossier finalization, and SHALL remain at most 256 per
effective contract. Read-only reuse derivation SHALL consume no authority; persisted
governance or reuse SHALL consume exactly the currently declared unit classes.

Installed evidence SHALL run both source-confirmed focused and closed-trigger
journeys for each of `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and
`full`. These journeys SHALL prove profile floors, review rules, per-obligation
allowances, class formulas, not-required reasons, optional-driver behavior, and
Dossier results from the installed MCP artifact. Additional installed journeys SHALL
prove contract-revision carry-forward with exact adopted drift, blocking unknown
causality, affected impact-gap reentry, corrupt current-inventory admission failure,
concurrent admission of distinct linked worktrees, and resume of a task created by a
`0.4.x` release.

Boundary validation SHALL exercise both the exact maximum and first excess value for
all current product bounds, including 4,096 snapshot paths per repository, 12,288
Git index stage entries per repository, 2 MiB Git index output per capture, 128
ownership claims per source action, 4,096 current roll-forward manifest entries, 128
impact entries, 64 plan obligations, 64 findings per review, 64 evidence items per
assurance execution, 256 actions per effective contract, the shared 64 KiB action
payload, and shared 8 KiB text field. Exact maxima SHALL remain admissible when every
other rule holds. First-excess values SHALL fail atomically without truncation or
partial mutation, except the current impact-overflow rule that records bounded
overflow and selects unknown/conservative assurance.

Candidate validation SHALL require plugin manifest, Python package metadata, lock
metadata, MCP server identity, and managed-runtime receipt to agree with the single
`RELEASE_VERSION`. It SHALL independently require exact `MODEL_VERSION` `0.4.0` in
workflows, policy, schemas, task records, MCP projections of domain identity,
installed evidence, and persisted-model documentation. Supplied missing, mixed, or
non-current model values SHALL fail closed with no compatibility conversion. Current
runtime discovery, admission, replay, MCP, CLI, and package validation SHALL never
enumerate, read, migrate, translate, repair, or delete retained `0.2.0` namespace
bytes.

The release-bump command SHALL continue to update only release authority and derived
plugin/package/lock/MCP release metadata when no compatibility-model change is
declared. It SHALL leave `MODEL_VERSION`, all `0.4.0` schemas, namespaces, workflows,
policy, and protocol-bearing model documentation unchanged.

#### Scenario: Runtime and capability definition drift

- **WHEN** any Controller, CLI, MCP tool, workflow, guidance, Web view, Dossier, installed journey, or documentation asset describes behavior inconsistent with current product authority
- **THEN** candidate validation fails

#### Scenario: Unsupported later-stage capability is claimed

- **WHEN** assets claim automatic branch/worktree creation, parallel repository executors, per-repository partial approval, remote MCP state, or external CI/PR/release orchestration
- **THEN** candidate validation fails

#### Scenario: Installed exact-set MCP journey succeeds

- **WHEN** the installed candidate runs a task over two prepared worktrees, resumes from the second member, verifies current aggregate evidence, and finalizes through MCP
- **THEN** the Dossier identifies both members and the journey never requires CLI invocation or plugin-source reading

#### Scenario: Installed one-member MCP journey succeeds

- **WHEN** the installed candidate completes a one-member task
- **THEN** snapshot, projection, verification, resources, and Dossier use the same repository-set schemas as the larger journey

#### Scenario: Embedded current-product schema is missing

- **WHEN** an MCP action submits a manifest, plan, verification, review, finding, driver, decision, payload, or binding without its exact current schema
- **THEN** validation fails without a partial mutation

#### Scenario: Retained prior-namespace bytes exist

- **WHEN** retained `0.2.0` bytes are beside the current namespace
- **THEN** installed MCP discovery, admission, replay, and package validation leave them unchanged and unread

#### Scenario: Patch release is prepared

- **WHEN** the release-bump command receives a valid patch release with no model change
- **THEN** only release-authority and derived release metadata change while model-bearing files remain byte-for-byte unchanged

### Requirement: Candidate validation proves the MCP interface and context boundary

The candidate SHALL include protocol tests against the real MCP server process and
SDK client transport. Tests SHALL cover initialize negotiation, bounded instructions,
`tools/list`, all eleven tool calls, structured output validation, concise text
content, unknown tool, malformed JSON-RPC, invalid parameters, current domain errors,
unexpected adapter errors, cancellation before commit, uncertain completion recovery,
EOF, restart, stdout purity, stderr redaction, and no listening socket.

For every stable tool, tests SHALL assert exact name, input schema, output schema,
annotations, task-support declaration, result envelope, size budget, and Controller
mapping. CLI/MCP parity tests SHALL start from equivalent isolated state and prove the
same successful task state or exact current domain error for every mapped operation.
They SHALL not compare unstable request IDs or presentation-only text as domain
authority.

Context tests SHALL enforce server instructions at most 4 KiB with a self-contained
first 512 characters, tool descriptions at most 512 bytes each, serialized
`tools/list` at most 32 KiB, action guidance at most 8 KiB, text summaries at most 4
KiB, and bounded pagination. A required exact action that cannot fit SHALL produce
`MCP_RESULT_LIMIT`; truncation of bindings, payload schemas, current obligation,
review contract, or governing-resource identity SHALL fail validation.

Installed journey instrumentation SHALL prove that normal tasks do not read legacy
Skills, Hooks, CLI source, MCP adapter source, launchers, or raw task-state files to
discover how the product works. It SHALL distinguish legitimate reading of the
user's repository and governing OpenSpec artifacts from package-source reading.

#### Scenario: One stable tool lacks a protocol test

- **WHEN** a catalog tool is not covered by success, failure, schema, annotation, and Controller parity evidence
- **THEN** candidate validation fails

#### Scenario: MCP stdout is polluted

- **WHEN** startup, logging, warning, error, or shutdown writes a non-protocol byte to stdout
- **THEN** protocol validation fails

#### Scenario: Context metadata grows beyond its bound

- **WHEN** instructions, descriptions, catalog, guidance, summaries, or page output exceed their release limits
- **THEN** candidate validation fails before installation

#### Scenario: An installed journey reads plugin source for invocation guidance

- **WHEN** the executor opens package implementation or removed Skill/Hook content to determine normal sequencing or payload shape
- **THEN** the installed journey fails and the missing information must be supplied through the MCP interface

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/authoritative-plugin-installation/spec.md`

## Purpose

Extend the existing authoritative source and marketplace lifecycle so supported
installers provision, activate, validate, repair, and remove the MCP-first plugin and
its isolated runtime without weakening source verification or task-data preservation.

## MODIFIED Requirements

### Requirement: Plugin activation failure is explicit and recoverable

The installer SHALL return nonzero when plugin registration, managed-runtime
activation, MCP initialization, tool-catalog validation, or installed server health
fails. It SHALL report source verification, marketplace registration, plugin
activation, runtime activation, MCP visibility, and tool health as separate states.
It SHALL print exact bounded recovery commands for plugin removal/re-addition and MCP
inspection without rewriting or deleting the verified source checkout or Controller
task data.

A prior validated managed runtime SHALL remain available when staged replacement
fails and retaining it is safe. The installer SHALL NOT claim success merely because
`codex plugin add` succeeded before the MCP server failed. It SHALL NOT automatically
fall back to legacy Skills or Hooks.

#### Scenario: Codex rejects plugin activation

- **WHEN** source, package, runtime, and marketplace validation succeed but `codex plugin add` exits unsuccessfully
- **THEN** installation exits unsuccessfully and reports manual plugin recovery while preserving source, runtime staging evidence, and task data

#### Scenario: Plugin activates but MCP startup fails

- **WHEN** Codex accepts the plugin but the installed launcher cannot initialize the MCP server
- **THEN** installation exits unsuccessfully, identifies MCP health as failed, and does not present the plugin as usable

#### Scenario: Tool catalog does not match the candidate

- **WHEN** installed `tools/list` differs from the candidate's approved interface
- **THEN** activation fails and reports the identity or catalog mismatch without enabling a legacy fallback

### Requirement: Candidate validation covers installer authority boundaries

The candidate SHALL include behavior suites that invoke each supported host installer
against isolated Git repositories, marketplaces, Codex executables, MCP configuration,
Python interpreters, and managed-runtime roots. The macOS suite SHALL retain the
complete established source-authority matrix. The Windows suite SHALL retain its
representative native fresh, idempotent, fast-forward, refusal, preservation,
activation-failure, and uninstall boundaries.

Both suites SHALL additionally cover:

- exact locked MCP runtime provisioning and receipt validation;
- runtime staging failure and preservation of a prior valid runtime;
- real installed launcher initialization and stable tool catalog;
- no non-protocol stdout;
- bundled/standalone duplicate registration detection;
- plugin success with MCP failure as an overall failure;
- Python below 3.10 and unsupported interpreter architecture refusal;
- stale, missing, or mismatched runtime ownership receipt;
- safe uninstallation of owned runtime assets while preserving task data;
- absence of installed legacy Skill and Hook authority.

Validation SHALL NOT require either host to execute the other host's shell language.
Windows SHALL NOT duplicate every established Git-history permutation merely for
platform parity, but it SHALL execute the real PowerShell installer, uninstaller, and
Windows MCP launcher. Every required shell, PowerShell, MCP configuration, launcher,
lock, receipt, package validator, and host test asset SHALL be part of candidate
validation.

#### Scenario: Candidate installer behavior is validated on macOS

- **WHEN** focused validation runs on macOS
- **THEN** it retains all authoritative source and marketplace cases and proves the real POSIX MCP runtime, activation, duplicate detection, and uninstall path

#### Scenario: Candidate installer behavior is validated on Windows

- **WHEN** focused validation runs on Windows
- **THEN** it executes real PowerShell lifecycle entry points and native MCP launcher against isolated dependencies and covers representative success, refusal, preservation, and activation failure

#### Scenario: A required MCP lifecycle asset is missing

- **WHEN** `.mcp.json`, a native launcher, runtime lock, managed-runtime receipt contract, or installed MCP smoke is absent
- **THEN** package validation fails before plugin installation

### Requirement: Public installation guidance states the authority boundary

Public English and Simplified Chinese guidance SHALL continue to identify `main` as
the non-configurable authoritative source ref and SHALL explain that automatic
upgrades require the expected origin, a clean attached `main`, and fast-forward-only
history. It SHALL provide the correct native installation and uninstallation entry
points for every supported host.

Guidance SHALL additionally state:

- local STDIO MCP is the default installed interaction boundary;
- supported Python is 64-bit CPython 3.10–3.14;
- the installer creates an isolated owned runtime from the locked dependency set;
- bundled and standalone Dev Flow MCP registrations must not both be active;
- the operator can verify server visibility, identity, and tool catalog with current
  Codex MCP inspection commands or UI;
- mutation approval remains host/user authority;
- legacy Skills, command Hooks, `/hooks` review, and the old PreToolUse guard are no
  longer part of the installed product;
- task data remains in the current `0.4.0` namespace and is preserved on uninstall;
- CLI and Web UI remain recovery/inspection adapters;
- the local-shell residual risk, unsupported environments, and rollback path are
  explicit.

Neither language SHALL imply that plugin registration proves MCP health, that tool
annotations grant approval, that the installer migrates task data, or that the MCP
server prevents unrestricted local shell access.

#### Scenario: macOS operator reviews installation guidance

- **WHEN** an operator reads the macOS instructions
- **THEN** they can determine source authority, eligible upgrade state, Python and runtime requirements, MCP verification, registration mode, approval boundary, uninstall behavior, and rollback

#### Scenario: Windows operator reviews installation guidance

- **WHEN** an operator reads the Windows instructions
- **THEN** they can identify the native PowerShell command, x64 client boundary, Git and Python prerequisites, MCP health check, duplicate-registration rule, Web UI command, and data-preserving uninstall

#### Scenario: Documentation still requires Hook trust

- **WHEN** public guidance instructs the operator to trust `/hooks` as part of current `0.5.0` activation
- **THEN** package validation fails as stale product guidance

### Requirement: Supported host entry points apply one authoritative installation lifecycle

The product SHALL provide `scripts/install.sh` for supported macOS hosts and
`scripts/install.ps1` for supported Windows x64 clients. Each entry point SHALL
enforce authoritative `main`, eligible existing checkout, candidate package
validation, marketplace isolation, managed-runtime staging, plugin activation,
installed MCP protocol smoke, duplicate-registration checks, and final receipt before
reporting success.

The managed runtime SHALL be outside source, task data, and user repositories. It
SHALL be produced from the candidate's exact lock under a supported 64-bit CPython
3.10–3.14 interpreter and SHALL be activated only after import and MCP smoke success.
Platform-specific syntax MAY differ, but neither host SHALL weaken source authority,
mutate an ineligible checkout, replace a malformed marketplace, reuse an unverified
runtime, report plugin-only success, grant blanket tool approval, or install legacy
Skill/Hook authority.

#### Scenario: Fresh macOS installation succeeds

- **WHEN** a supported macOS host has required tools, no source checkout, no duplicate registration, and a valid or absent marketplace
- **THEN** the installer verifies `main`, validates the package, provisions the runtime, activates the plugin, proves the installed MCP server, and emits one complete receipt

#### Scenario: Fresh Windows installation succeeds

- **WHEN** a supported Windows x64 client has required tools, no source checkout, no duplicate registration, and a valid or absent marketplace
- **THEN** the PowerShell installer performs the same authority lifecycle through native executables and reports MCP health separately

#### Scenario: Existing installation is repaired or upgraded

- **WHEN** source is the expected clean attached `main` and equal to or behind fetched `main`
- **THEN** the installer leaves or fast-forwards it, stages or reuses an exact matching runtime, validates the installed MCP artifact, and reports repair or upgrade accurately

#### Scenario: Existing source is ineligible

- **WHEN** source has an unexpected origin or branch, reported changes, local-ahead history, divergence, or an ignored-path collision
- **THEN** installation fails without switching, resetting, stashing, cleaning, overwriting, registering, or activating that source

#### Scenario: A duplicate Dev Flow registration is active

- **WHEN** bundled activation would coexist with a standalone registration for the same owned launcher
- **THEN** installation fails with explicit resolution guidance and does not claim one deterministic server

#### Scenario: Runtime validation fails after staging

- **WHEN** dependency, import, identity, protocol, or tool-catalog validation fails
- **THEN** the candidate is not activated, a prior validated runtime remains authoritative where safe, and task data is unchanged

### Requirement: Windows uninstallation removes only validated installation assets

The product SHALL provide `scripts/uninstall.ps1` for supported Windows x64 clients.
It SHALL remove the installed plugin when present, atomically remove only the Dev
Flow entry from a valid personal marketplace, and remove only validated
installer-owned MCP runtime and launcher assets. It SHALL preserve external
Controller task data in all cases and SHALL preserve unrelated bundled or standalone
MCP registrations.

By default, source deletion SHALL occur only after validating the expected product,
an allowed origin, attached `main`, no tracked, untracked, or ignored content, and no
local-only commits. A keep-source option SHALL preserve source. Runtime deletion
SHALL require an exact ownership receipt and expected location; uncertainty SHALL
fail closed and leave the runtime for manual handling. Uninstallation SHALL report
plugin, marketplace, MCP registration, runtime, source, and task-data outcomes
separately.

#### Scenario: Ordinary Windows uninstall succeeds

- **WHEN** plugin, marketplace entry, runtime, launchers, and source are all validated as installer-owned and safe
- **THEN** those assets are removed and the receipt states that Controller task data was preserved

#### Scenario: Windows source contains user work

- **WHEN** source has local changes, ignored content, local-only commits, unexpected origin, or another unsafe identity
- **THEN** uninstallation refuses to delete source and reports the reason without deleting task data or unrelated MCP configuration

#### Scenario: Managed-runtime ownership is uncertain

- **WHEN** the runtime receipt is missing, inconsistent, or points outside the expected owned path
- **THEN** uninstallation leaves the runtime for manual handling and does not infer ownership from directory name alone

#### Scenario: Keep source is requested

- **WHEN** the operator supplies the documented keep-source option
- **THEN** independently safe plugin, marketplace, and owned runtime removal may proceed while source and task data remain unchanged

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/native-windows-product-support/spec.md`

## Purpose

Replace Windows command-Hook product integration with one native installed STDIO MCP
server while retaining the same Controller state, workflow, assurance, Web UI,
installer authority, and bounded Windows x64 support claim.

## REMOVED Requirements

### Requirement: The installed plugin launches its current Hook natively on supported Windows clients

**Reason:** The `0.5.0` model-facing interaction path is the bundled MCP server, not a
command Hook. Keeping the Hook would preserve a second invocation and context
authority and would not solve repeated source and Skill reading.

**Migration:** The native `.cmd` launcher starts `dev_flow_mcp.py --stdio` from the
managed runtime. Context restoration uses `dev_flow_find_tasks_for_path` and
`dev_flow_get_next_action`.

### Requirement: Windows Hook context uses the same task authority and a copyable PowerShell locator

**Reason:** MCP tools replace injected CLI locators and shell-escaped JSON commands.
The Controller and current data namespace remain unchanged.

**Migration:** Operators use the stable MCP tool catalog for normal tasks and retain
the standalone JSON CLI only for documented recovery or scripting.

### Requirement: Windows Hook guards remain practical and explicitly bounded

**Reason:** An MCP server cannot observe every Bash, PowerShell, edit, or patch call.
Retaining only this Hook would keep an incomplete Codex-specific guard and a second
trust surface.

**Migration:** Task data stays outside admitted repositories; MCP responses and
normal diagnostics do not expose its path; model-facing mutations are closed tools;
documentation states that unrestricted local shell access remains outside the MCP
security boundary.

### Requirement: Hook activation remains an explicit user trust decision

**Reason:** The installed product no longer uses command Hooks. MCP visibility and
mutation approval are governed by Codex MCP registration and tool-approval behavior.

**Migration:** Installation receipts distinguish verified source, managed runtime,
plugin activation, MCP server health, tool visibility, and remaining host/user
approval.

## ADDED Requirements

### Requirement: The installed plugin launches its MCP server natively on supported Windows clients

The packaged Windows MCP configuration SHALL invoke the installed Windows MCP
launcher and the same MCP bootstrap used on macOS. The launcher SHALL locate the
validated installer-owned runtime and supported 64-bit CPython 3.10–3.14, SHALL
preserve UTF-8 STDIO and exact argument boundaries, and SHALL require no WSL, Git
Bash, Cygwin, or POSIX shell.

The Windows server SHALL expose the same `dev-flow-mcp/1.0.0` identity, instructions,
tool names, input/output schemas, annotations, Controller errors, and current model
values as macOS. It SHALL not create a Windows-specific MCP interface, task type,
workflow, data namespace, or release line.

#### Scenario: Installed MCP launches from an ordinary Windows path

- **WHEN** Codex starts the plugin from a local Windows path containing spaces or valid Unicode
- **THEN** the native launcher initializes the protocol and lists the current stable catalog without shell emulation

#### Scenario: Supported Python is unavailable

- **WHEN** no supported 64-bit Python 3.10–3.14 interpreter or valid installer-owned runtime can execute the server
- **THEN** launch fails with bounded stderr diagnostics, emits no malformed protocol stdout, and does not mutate Controller state

#### Scenario: macOS and Windows catalogs are compared

- **WHEN** installed artifact tests initialize both supported host packages for the same release
- **THEN** server identity, instructions digest, tool catalog, schemas, and annotations are equivalent except for native launcher details

### Requirement: Windows MCP discovery uses current canonical task authority

On supported Windows clients, `dev_flow_find_tasks_for_path`, task admission, active
membership leases, overlap checks, and Controller-data separation SHALL use the same
current Windows path comparison. Discovery from any member or contained path SHALL
return the same active task despite supported drive-letter case or separator
spelling differences. It SHALL return a bounded PowerShell-independent task identity,
not an injected shell locator.

The MCP server SHALL use the same Controller and current model namespace as the CLI
and Web UI. It SHALL NOT create platform-specific projections or persist the client
working directory as task authority.

#### Scenario: A task resumes from a secondary Windows member

- **WHEN** a client discovers from a contained path in any non-first member
- **THEN** it receives the same current task ID and can obtain the same exact action binding as discovery from the first member

#### Scenario: No active task covers the path

- **WHEN** the canonical Windows path is outside every healthy active member
- **THEN** discovery returns `none` without creating task state or a data directory inside the repository

### Requirement: Windows MCP approval and residual local-shell risk are explicit

The Windows installer and public guidance SHALL direct the operator to inspect the
MCP server identity and tool catalog and SHALL explain the host's approval behavior
for mutation tools. Installation SHALL NOT be represented as blanket approval and
SHALL NOT rewrite unrelated user policy.

Documentation SHALL state that removal of PreToolUse Hook guards means the MCP server
cannot prevent an unrestricted PowerShell or other local process from searching for
or changing files outside the MCP interface. It SHALL also state the compensating
controls: no tool exposes the data path, all normal mutations use Controller tools,
data and repositories are disjoint, server logs redact protected paths, and direct
state access remains unsupported.

#### Scenario: Codex asks for mutation approval

- **WHEN** host policy requires approval for a Windows MCP mutation tool
- **THEN** the prompt is treated as expected user authority and not diagnosed as server failure

#### Scenario: An arbitrary PowerShell command targets task data

- **WHEN** a user or model with unrestricted local shell constructs a path outside the MCP server
- **THEN** the product makes no claim that MCP intercepted it and documentation does not present the removed Hook as a security boundary that still exists

## MODIFIED Requirements

### Requirement: Native Windows support remains one bounded whole-product claim

The Windows installation SHALL expose the same plugin name, `RELEASE_VERSION`,
`MODEL_VERSION`, product identity, workflow catalog, Controller state model,
assurance policy, Delivery Dossier, CLI, Web UI, and MCP interface as macOS. It SHALL
NOT declare a Windows-specific release, model version, MCP catalog, package,
marketplace entry, data namespace, workflow, compatibility line, or release gate.

The public supported Windows boundary SHALL be Windows 10 22H2 x64 and Windows 11
x64 client systems using supported 64-bit CPython 3.10–3.14, Git for Windows, Codex
plugin and local STDIO MCP support, native PowerShell for lifecycle commands, and
ordinary local repositories. Windows ARM64, 32-bit Python, Windows Server, WSL
execution, UNC/SMB/NAS or mapped network repositories, `\\wsl$`, remote MCP serving,
historical migration, and cross-operating-system task transfer SHALL remain outside
the claim.

#### Scenario: Supported Windows client completes an installed MCP task

- **WHEN** a documented Windows x64 client installs the plugin and completes a representative workflow through MCP
- **THEN** every task record and output uses the same current product authorities and persisted model as macOS

#### Scenario: Existing current task is resumed after upgrade

- **WHEN** a model `0.4.0` task created by the prior Hook/CLI product is opened by the Windows MCP release
- **THEN** it resumes in place with no state migration or Windows-specific conversion

#### Scenario: Unsupported Windows environment is used

- **WHEN** the product runs outside the documented support boundary
- **THEN** the project makes no compatibility claim and is not required to add a broad platform-detection, remote path, or compatibility subsystem for this change

---

# Source: `openspec/changes/dev-flow-orchestrator-mcp/specs/native-windows-runtime/spec.md`

## Purpose

Update the native Windows core runtime boundary for the MCP-first installed product:
raise the supported Python floor to 3.10, keep the Controller/Git/storage core
standard-library-only, and isolate the official MCP SDK in the adapter runtime.

## MODIFIED Requirements

### Requirement: The core runtime operates natively on common Windows x64 clients

The core Controller, CLI, Web UI, and shared repository runtime SHALL operate without
WSL, Git Bash, or Cygwin on Windows 10 22H2 x64 and Windows 11 x64 client systems
using supported 64-bit CPython 3.10–3.14 and Git for Windows. Core production modules
outside `src/dev_flow_orchestrator/mcp/` SHALL remain Python-standard-library-only.
The installed MCP adapter MAY depend on the official Python MCP SDK stable v2 line and
its locked transitive dependencies, but those dependencies SHALL remain isolated from
the core import and persisted-model boundary.

The documented support boundary SHALL exclude Windows Server, Windows ARM64, 32-bit
Python, CPython 3.9, WSL execution, UNC/SMB/NAS repositories, `\\wsl$`, mapped
network storage, and remote MCP serving. The runtime is not required to detect every
unsupported Windows edition or storage technology merely to enforce that support
statement.

#### Scenario: Supported Windows core lifecycle executes

- **WHEN** a user runs the core CLI or an MCP tool against an ordinary local Git worktree on a documented Windows x64 client
- **THEN** start, capture, current-action projection, action application, stored inspection, path discovery, governance, and cancellation execute without a POSIX compatibility layer

#### Scenario: Core package imports without MCP dependencies

- **WHEN** Controller, Store, GitClient, CLI, and Web modules are imported on Windows in a core-only environment
- **THEN** no unavailable POSIX module or MCP SDK package is imported as a side effect

#### Scenario: The MCP adapter imports in its managed runtime

- **WHEN** the installed Windows launcher uses its validated managed runtime
- **THEN** the MCP adapter imports the locked official SDK and initializes STDIO while using the same core modules and current data namespace

#### Scenario: Only Python 3.9 is available

- **WHEN** a Windows operator attempts to install release `0.5.0` with no supported Python 3.10–3.14 runtime
- **THEN** installation fails before MCP activation, preserves existing task data, and reports the new runtime floor

#### Scenario: Unsupported environment is used

- **WHEN** the runtime is used outside the documented Windows client boundary
- **THEN** the product makes no compatibility claim and does not require a broad SKU, filesystem, or remote-transport detection subsystem

---
