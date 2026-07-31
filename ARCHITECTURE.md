# Architecture

Dev Flow Orchestrator is one importable Python package with one product matrix
and one mutation boundary. Physical modules match runtime ownership; there is
no dynamic module registry or generated workflow bundle.

## Dependency direction

```text
CLI ─┐
MCP ─┼─> Controller ─> Engine ─> Workflow / Repository kernel / Model
Hook ┘        │
              ├─> Confirmation store/index
              ├─> Store ─> Filesystem primitives
              ├─> Journal ─> Filesystem primitives
              └─> Git client
```

`model.py`, `product.py`, `workflow.py`, `repository_kernel.py`, and
`engine.py` do not perform filesystem, process, environment, or network I/O.

## Owners

| Module | Owns | Does not own |
|---|---|---|
| `product.py` | Four profiles, workspace compatibility, suite binding, product identity | CLI selection, state, I/O |
| `model.py` | Schema-v4 values and stable errors | persistence, Git, adapter protocols |
| `workflow.py` | Current node contracts and graph-derived `agent-v1` projection | state writes, effect execution |
| `repository_kernel.py` | Repository DAG, ordering, leases, attempts, results, retry, cancellation, barrier, integration binding | workflow-specific gates, I/O |
| `engine.py` | Eligibility, payload checks, mutation plans, pure state candidates | locks, time, Git, serialization |
| `authority.py` | Durable conversation requests, exact binding, prompt-event decisions, one-time claim/consume, replay ledger and private confirmation index | workflow policy, state transitions, authenticated-human claims |
| `store.py` | Private paths, task locks, revision CAS, atomic state replace | workflow policy |
| `journal.py` | Effect claim, receipt, quarantine, commit, abandonment | effect execution |
| `git_client.py` | Bounded Git evidence and declared workspace effects | state transitions |
| `controller.py` | Application coordination and the only state-write entrypoint | wire protocols |
| `cli.py` | argv and one-JSON-object responses | workflow policy |
| `mcp.py` | JSON-RPC/MCP framing and current tool schemas | fallback, task writes |
| `hook.py` | Scope lookup, context injection, bounded `UserPromptSubmit` forwarding, direct-state-write guard | confirmation policy, transitions |

## Product dimensions

The product matrix is the cross product of:

- workflow depth: `full@4` or `lite@4`;
- topology: single repository or multiple repositories;
- workspace strategy: `in-place`, `branch`, or `worktree`.

The first two dimensions produce exactly four profiles. Workspace strategy is
compatible with every profile and never changes workflow depth.

Full preflight enters its baseline and full-only gates. Lite preflight has no
workflow-entry approval: single-repository Lite targets `implement` /
`IMPLEMENTING`; multi-repository Lite targets `repository-plan` /
`ORCHESTRATING`.

## Node contract

Every actionable node declares:

- node and action ID;
- target node and status;
- required authority;
- allowed state JSON pointers;
- effect kind;
- direct handler ID and effect port;
- output kind and required payload fields;
- accepted payload types and bounded size;
- idempotency fields;
- failure code and recovery action.

The controller asks the engine for this contract at the current revision.
Each contract's handler ID resolves through one static node-family catalog to
a direct pure callable and the same declared effect port. The engine does not
dispatch reducers by `output_kind`. Adapters do not contain a second state
table.

Each task also pins a digest of its selected workflow graph, repository graph,
topology, and product identity. Loading rejects a task whose pinned identity
does not match the installed graph.

## Mutation boundary

Effect-free action:

```text
load under task lock → validate revision/action/payload/write set
                     → resolve exact conversation confirmation when required
                     → atomic state replace
```

External effect:

```text
pure payload/plan validation → resolve exact conversation confirmation
     → execution fence → durable claim
     → dispatch once → durable receipt → release fence
     → revision/plan revalidation → atomic state replace → journal commit
```

When confirmation is required but not ready, resolution creates or reloads a
private request and returns without a task write, Git operation, journal claim,
or business effect. A later `UserPromptSubmit` observation records only an
exact decision. A subsequent controller call reloads and revalidates the
binding before planning and consumes it only at the declared successful
lifecycle point.

An uncertain effect is quarantined. Recovery requires an explicit `settle`,
`abandon`, `reattach`, or `compensate` request. Mode eligibility is checked
before confirmation and its evidence digest is included in the exact request.
After confirmation, the controller acquires the same per-execution fence,
reloads the journal, and proves the mode again before any terminal mutation.
Unavailable or changed proof returns operator intervention; unavailable
reattach or compensation does so without creating a request. Conversation
agreement is not effect evidence.

## Confirmation lifecycle

A canonical request binds task, workflow identity, revision, action, grant,
local execution account, actor role, validated payload, repository/lease
scope, repository context, and Codex session. It has no clock expiry:

```text
PENDING → CONFIRMED → CONSUMED
PENDING → CONFIRMED → CLAIMED → CONSUMED
PENDING → DENIED
binding drift without success evidence → STALE
```

The exact first apply creates `PENDING` and ends that agent turn. A later
exact `同意` / `approve` or request-ID reply can change only the confirmation
record; it cannot execute the action. The next turn reloads `agent-v1` and
retries only a still-current `CONFIRMED` binding. Denial is terminal for the
exact binding. There is no polling, background apply, public confirmation
issuer, caller approval flag, or manual Hook path.

One data-directory confirmation lock serializes request selection, the
`(session_id, turn_id)` event ledger, decisions, consumption, reconciliation,
and compaction across tasks. For a prompt event, the controller derives the
eligible active-task set from canonical cwd before selecting requests; stored
event evidence contains cwd, eligible-task-set, and prompt digests rather than
raw cwd or prompt. The confirmation lock is never nested with task, journal, or
workspace locks. The task CAS or deterministic journal claim resolves racing
confirmed retries, while successful task/journal evidence reconciles a crash
between commit and confirmation consumption.

## Command mapping

| Public operation | Controller method | State/effect owner |
|---|---|---|
| `start` / `task-start` | `Controller.start` | `TaskStore.create` |
| `show` / `task-show` | `Controller.show` | read only |
| `next` / `task-next` | `Controller.next` | graph-derived read only |
| `preflight` / `task-preflight` | `Controller.preflight` | Git read + CAS commit |
| `apply` / `action-apply` | `Controller.apply` | current node contract |
| `effect-inspect` | `Controller.effect_inspect` | journal read only |
| `effect-recover` | `Controller.recover_effect` | journal/controller recovery |
| `UserPromptSubmit` Hook | confirmation observer | confirmation record only |

## Repository kernel

Both multi-repository profiles call the same pure kernel:

```text
canonical set → owners + pinned HEADs + dependency DAG → ready leases
              → scoped results/retries
              → all-pass barrier → integration binding
```

`full@4` reaches this kernel after its planning approval.
Multi-repository `lite@4` reaches it directly after preflight. The kernel
contains no full/lite branch, and its own declared authority requirements are
identical for both workflows.

## Persistence layout

For an explicit data directory:

```text
<data-dir>/
  tasks/<task-id>/state.json
  locks/<task-id>.lock
  confirmations/index.json
  locks/confirmation.lock
  effects/<task-id>/<plan-binding>.json
  workspaces/<task-id>/<repository-id>/
```

Directories use local-account-only permissions, files are private, and writes
use atomic replace. State paths are not target-repository paths. Unsafe
permissions or symlinks, corruption, lock/write failure, and capacity
exhaustion fail closed for guarded authority; the Hook itself remains
fail-open and no automatic repair or deletion occurs.

## Public bootstraps

`scripts/dev_flow.py`, `scripts/dev_flow_mcp.py`, and
`hooks/dev_flow_hook.py` only add the fixed
package-owned `src` directory to the isolated interpreter path and import one
`main` function. Exactly one packaged `UserPromptSubmit` path forwards bounded
session, turn, cwd, and prompt evidence to the same controller/data directory
used by CLI and MCP. Hook context labels its bounded
`conversation_routing={session_id,request_turn_id}` as correlation-only.
Public adapters accept no caller-issued confirmation. None execute source text,
select another runtime, or dispatch by environment.

The configured lifecycle event is conversation correlation and audit evidence,
not independent operating-system or authenticated-human identity. Codex
host-owned sandbox, filesystem, or tool-permission prompts are outside this
plugin's boundary and are not suppressed or auto-confirmed.
