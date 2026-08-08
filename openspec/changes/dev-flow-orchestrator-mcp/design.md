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
