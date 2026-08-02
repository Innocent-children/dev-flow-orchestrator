# Architecture

Dev Flow Orchestrator V5 is one importable Python package with one mutation
boundary and one declarative workflow definition source. Physical modules
match runtime ownership; there is no dynamic module registry or generated
workflow bundle.

## Dependency direction

```text
CLI ─┐
Hook ┴─> Controller ─┬─> Engine ─> Workflow ─> Model
                    ├─> Store ──> Engine
                    │      └────> Filesystem primitives
                    ├─> Workflows ─> yaml_subset
                    └─> GitClient (read-only)
```

`model.py`, `product.py`, `workflow.py`, `engine.py` and `yaml_subset.py` do
not perform filesystem, process, environment or network I/O. `workflows.py`
loads definition files. The only target-repository effect is the bounded,
read-only Git inspection run by the preflight node.

## Owners

| Module | Owns | Does not own |
|---|---|---|
| `product.py` | Schema/workflow version constants, plugin-data namespace, built-in workflow registry, product identity | selection, state, I/O |
| `model.py` | Schema-v5 values, stable errors, canonical JSON | persistence, Git, workflow policy |
| `workflow.py` | YAML document validation, node contracts, graph checks, identity, agent projection | state writes, I/O |
| `workflows.py` | Built-in file resolution and custom-path loading | validation semantics |
| `yaml_subset.py` | Strict YAML-subset parsing with line errors | workflow semantics |
| `engine.py` | Eligibility, payload checks, mutation plans, deterministic state replay and transition validation | locks, Git, persistence |
| `store.py` | Private paths, identity-bound safe reads, task locks, revision CAS, semantic validation boundary, atomic state replace | workflow declaration policy |
| `git_client.py` | Bounded read-only Git evidence | state transitions |
| `controller.py` | Application coordination and the only state-write entrypoint | wire protocols |
| `cli.py` | argv and one-JSON-object responses | workflow policy |
| `hook.py` | Scope lookup and context injection | transitions, policy |

## Workflow definitions

A workflow declares one deterministic normal path from its entry to a terminal
node, plus an optional shared cancel action targeting a terminal node. It is
stored as YAML (or JSON) at `workflows/<id>.yaml`, or in a custom file selected
by absolute path. The runtime executes exactly one action per non-terminal
node, then moves to that node's single target.

### Node contract

| Field | Required | Meaning |
|---|---|---|
| `action_id` | non-terminal | the action the agent applies |
| `handler` | non-terminal | one of `preflight`, `evidence.record`, `test.record` |
| `target` | non-terminal | `{node: <id>, status: <status>}` — where the task lands |
| `terminal` | terminal | `true` = sink: no action, no target |
| `payload` | no | `field: type` — all declared fields are required |
| `writes` | no | must equal the handler's derived write set |
| `effect` | no | `none` or `git.inspect-repository` (preflight only) |
| `authority` | no | only `task-revision` accepted; other values rejected for now |
| `driver` | no | opaque label (e.g. `{tool: openspec}`); the runtime never interprets it |
| `description` | no | carried into the projection |

Payload types: `string`, `boolean`, `integer`, `object`, `sha256`.
Validation rejects unknown fields, dangling targets, unreachable nodes,
self-loops and multi-node cycles, duplicate action IDs, a missing terminal
node, a second preflight node, and any payload on the preflight node. A cancel
contract must record exactly `reason: string`, target a terminal node and land
with `CANCELLED`. Violations use `WORKFLOW_INVALID` with the offending node in
`details`.

### Identity pinning

Each task pins `workflow_identity = sha256(product_identity + selector +
canonical(document))`. Every load recomputes it against the current file:
editing, moving or deleting a workflow file after a task started fails fast
(`WORKFLOW_IDENTITY_MISMATCH` / `WORKFLOW_NOT_FOUND`). The selector is the
built-in id (`lite`) or the absolute path used at `start`.

## Mutation boundary

```text
load state plus pinned definition → validate and plan current action →
(preflight: read bounded Git evidence) → lock and re-read → revision CAS →
validate deterministic replay and append-only transition → atomic replace
```

Every mutation increments the revision exactly once, enforced at the store
boundary (`TaskStore.update`). The agent protocol never carries a revision:
`apply` reads it from the loaded state, and a concurrent writer's loser
receives `REVISION_CONFLICT` whose `details.projection` is the fresh
projection — the agent simply re-runs `next`. State is never corrupted.
Every persisted read is replayed from the workflow entry using preflight and
ordered evidence. Impossible node/status/revision combinations fail closed as
`STATE_INVALID`; mutation candidates that change immutable fields or rewrite
evidence fail as `STATE_WRITE_INVALID` before replacement.

## The agent-v1 projection

`next` returns exactly one thing to do:

```json
{
  "schema": "dev-flow-agent-v1",
  "task_id": "task-9f2c4a1b3d7e",
  "requirement": "Implement the persisted task requirement",
  "revision": 2,
  "workflow": {"id": "lite", "version": 5, "identity": "<64 hex>"},
  "status": "IMPLEMENTING",
  "current_node": "implement",
  "repo_context": {
    "repository_id": "repo-<12 hex>",
    "path": "/absolute/path/to/repo",
    "preflight": {"schema": "dev-flow-v5-git-preflight/v1", "...": "opaque evidence"}
  },
  "action": {
    "action_id": "task.implementation.complete",
    "node_id": "implement",
    "target": {"node": "verify", "status": "VERIFYING"},
    "payload": {"summary": "string"},
    "handler": "evidence.record",
    "writes": ["/current_node", "/revision", "/status", "/updated_at", "/evidence"],
    "driver": null,
    "description": null
  },
  "done": false
}
```

At a terminal node `action` is `null` and `done` is `true`, regardless of the
workflow's chosen display status. `apply` returns the same projection, so the
agent never needs an extra round trip.

## Persistence layout

```text
<PLUGIN_DATA>/
  tasks/                         # retained V4 data; V5 never reads it
  v5/
    tasks/<task-id>/state.json
    locks/<task-id>.lock
```

Directories use local-account-only permissions, files are private, writes use
atomic replace, and state paths are never target-repository paths.

## Public bootstraps

`scripts/dev_flow_python_launcher` selects a supported interpreter, then runs
`scripts/dev_flow.py` or `hooks/dev_flow_hook.py`; the Python bootstraps only
add the fixed package-owned `src` directory and import one `main` function.
The Hook registers exactly `SessionStart`,
`UserPromptSubmit` and `PreToolUse`: it injects the controller locator plus
the fresh projection for tasks covering the cwd, and denies direct writes
into the plugin data directory. Its injected locator already contains the
launcher, CLI handler and exact V5 state directory. The guard is advisory,
fail-open, and never writes task state.
