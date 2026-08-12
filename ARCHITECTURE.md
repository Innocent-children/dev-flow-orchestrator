# Dev Flow Orchestrator Architecture

[Simplified Chinese](ARCHITECTURE_CN.md)

## Product identities

Release `0.5.1` bundles a formal Codex Skill named `dev-flow` alongside the MCP
interface without changing persisted model identity. `MODEL_VERSION`, the
task-data namespace, workflows, policies, bindings, records, findings,
snapshots, and Delivery Dossiers remain `0.4.0`.

The non-persisted transport identities are:

- `dev-flow-mcp/1.0.0`
- `dev-flow-mcp-result/1.0.0`
- `dev-flow-mcp-action/1.0.0`
- `dev-flow-mcp-guidance/1.0.0`

## Layers

```text
Codex Skill               CLI                 Read-only Web UI
     |                      |                         |
     v                      v                         v
MCP adapter ----------- Controller -----------------+
     |                      |
     |                      +--> Engine --> Delivery --> Model
     |                      +--> Store / locks / revision CAS
     |                      +--> GitClient / complete-set capture
     |
     +--> schemas, results, guidance, concurrency, stderr logging
```

The Skill provides activation and routing and calls the MCP; it does not write
task state. The Controller is the only state-transition writer. The MCP package
imports the Controller, but Controller, Engine, Store, GitClient, workflow,
assurance, delivery, review, snapshot, and model modules never import the MCP
SDK or its framework dependencies. Core and CLI runtime code remains
standard-library only; the managed MCP environment owns the third-party SDK.

## Codex Skill

`.codex-plugin/plugin.json` registers `skills: "./skills/"`. The canonical
Skill tree is closed to `SKILL.md`, `agents/openai.yaml`, and
`references/activation-and-routing.md` under `skills/dev-flow/`.

The `SKILL.md` description is the host's implicit-matching surface and also
names the explicit `$dev-flow` route. `agents/openai.yaml` carries interface
metadata and enables `policy.allow_implicit_invocation`. It intentionally omits
`dependencies`: the supported dependency schema is URL-based, while this
plugin's local STDIO server is already registered by `mcpServers: "./.mcp.json"`.
No URL or alternate transport is synthesized.

At runtime the Skill checks server identity, discovers tasks for each exact
repository root, resumes one unambiguous compatible task or starts a new one,
and then repeats the live `get_next_action`/execute/apply loop. Ambiguous task
selection returns to the user. Uncertain mutations use read-after-write recovery
before any retry.

This content is not a protocol authority. Package validation rejects a Skill
that embeds an action catalog, payload schema, state machine, transition table,
or versioned Controller protocol definition. The current MCP response remains
the source for the action id, closed payload, exact binding, review and
verification obligations, transitions, and terminal result.

## MCP server

One `MCPServer` named `dev-flow` runs over STDIO. Initialization advertises
Tools only: no Resources, Prompts, Tasks, sampling, elicitation, HTTP, SSE,
authentication, or listening transport. The catalog contains exactly five read
tools and six mutation tools.

Inputs are closed Pydantic/JSON schemas with field, enum, count, and byte
limits. Domain objects still pass through current Controller/model validators;
transport validation does not duplicate or weaken domain rules. Unknown tools,
unknown fields, malformed JSON values, and protocol failures are rejected
before Controller dispatch.

Every tool returns one concise text item plus a structured
`dev-flow-mcp-result/1.0.0` envelope. Domain errors preserve their code and
receive bounded redacted details and deterministic recovery. Unexpected adapter
exceptions return `INTERNAL_ERROR` plus a request ID; stderr records only the
exception class and stack-frame locations, never arguments, contracts,
bindings, environment values, repository contents, or the task-data root.

## Read models

Existing bounded Controller inspection APIs are reused:

- product identity and health;
- paginated stored task inventory with isolated diagnostics;
- stored task detail, contract summary, governance summary, timeline page, and
  terminal Dossier;
- canonical active-task discovery for a repository path;
- live authoritative next-action capture.

The MCP current-action view is a transient compact projection derived from
`dev-flow-agent/0.4.0`. It retains the complete repository set, snapshot
digests, exact binding, payload contract, drivers, obligation/review context,
inputs, governing resources, and source projection digest. It does not persist
a new model object or expose Git-internal snapshot paths. If complete context
does not fit its limit, the adapter returns `MCP_RESULT_LIMIT`; it never
truncates a binding or required action field.

## Guidance

Initialization instructions contain only the discovery, explicit selection,
get-next, execute, and apply loop and are bounded to 4 KiB. A versioned catalog
selects guidance by current node and handler for preflight, impact, planning,
implementation, investigation, documentation, rework, assurance/review,
finalization, cancellation, and a closed generic fallback.

Impact guidance separates current and baseline codebase-memory projects and
requires source confirmation. Planning guidance carries governing OpenSpec
status, path/digest, source stage, and fallback. Review guidance uses the bound
review package and preserves its snapshot/digest authority. The final guidance
is bounded to 8 KiB.

## Repository and state authority

A task owns an immutable canonical set of one to eight user-prepared Git
worktree roots. The Controller does not create, switch, repair, or remove Git
worktrees or branches. Complete live capture covers all members twice where
required by the snapshot protocol. Missing members, overlap, aliases, shared Git
administration, stale bindings, unstable snapshots, or revision conflicts fail
atomically before state transition.

Stored inventory inspection performs no live Git capture and isolates corrupt
entries. Path discovery excludes terminal tasks and returns explicit ambiguity
for overlapping active claims. Task storage remains in the model `0.4.0`
namespace outside every repository.

## Concurrency and uncertain completion

The MCP adapter adds a bounded in-process coordinator: same-task mutations are
serialized, and at most four live-capture or mutation calls are admitted without
queueing. Excess calls fail immediately. This is only an admission optimization.
Store locks, repository membership, exact bindings, and revision CAS remain
authoritative across processes.

Mutations are non-idempotent. A disconnect or cancellation after a commit may
make completion uncertain, so clients must read the stored task and current
action before deciding whether another mutation is necessary. No adapter retry
loop replays mutations automatically.

## Runtime and installation

The source checkout, sealed plugin snapshot, managed MCP runtime, and task-data
root are disjoint. The installer preserves the complete Skill tree in the
sealed plugin snapshot, builds a versioned virtual environment using the exact
`uv.lock`, installs a wheel, runs installed Skill validation plus MCP
startup/catalog/read smoke checks, and writes a runtime receipt. The receipt and
ownership manifest bind the release, source commit, interpreter identity and
architecture, lock digest, launchers, and every installed Skill asset without
exposing the data root.

The plugin manifest points to root `.mcp.json`, which declares one `dev-flow`
server invoking the owned `dev-flow-mcp --stdio` PATH launcher. Bundled and
standalone registrations are mutually exclusive. Runtime publication and
launcher replacement are staged so a failed build leaves the prior runtime
usable.

## Security and residual boundary

The tool catalog has no generic command, raw-state, branch/worktree,
publication, external CI/PR/release, or parallel-executor capability. Tool
annotations are host hints and do not grant authority.

The legacy fail-open Hook, predecessor Skills, Hook bootstrap, and Hook-specific
Windows launcher are absent from the release package. The formal `dev-flow`
Skill is present, but supplies only activation and routing. Consequently there
is no PreToolUse data-directory guard. Safety relies on Controller validation,
Store integrity, host approvals, repository and operating-system permissions,
and user review. This residual boundary is explicit rather than represented as
Skill or MCP enforcement.

## Compatibility

Supported Python is `>=3.10,<3.15`, 64-bit for managed installation. macOS is
the primary installed delivery platform. Native Windows 10 22H2 x64 and Windows
11 x64 use PowerShell 5.1/7 lifecycle scripts and require native evidence;
Windows Server and compatibility layers are outside the client claim.

Existing 0.4.x tasks resume directly because the model namespace and bytes are
unchanged. Retained historical OpenSpec material remains evidence, not current
package authority.
