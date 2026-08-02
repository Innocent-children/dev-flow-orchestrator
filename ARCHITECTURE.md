# Architecture

Dev Flow Orchestrator V6 is one Python-standard-library package with one
controller mutation boundary, an append-only delivery ledger, and declarative
workflow definitions. It supports one task, one Git repository, the current
worktree, and one Codex executor.

## Dependency direction

```text
CLI ─┐
Hook ┴─> Controller ─┬─> Engine ─> Delivery ─> Model
                    │       └────> Workflow ─> Product
                    ├─> Store ───> Engine
                    │      └─────> Filesystem primitives
                    ├─> Workflows ─> yaml_subset
                    └─> GitClient (bounded, read-only)
```

The domain layer (`model.py`, `product.py`, `workflow.py`, `delivery.py`, and
`engine.py`) performs no filesystem, process, environment, or network I/O.
`workflows.py` loads packaged or selected definitions. `GitClient` is the one
target-repository inspection port. Drivers are instructions executed by Codex
outside the controller; the runtime only validates and records their declared
results.

## Module ownership

| Module | Owns |
|---|---|
| `product.py` | V6 task/workflow/catalog/record/artifact/projection identities and the six official workflow IDs |
| `model.py` | Immutable task values, canonical JSON, stable errors, revision-zero initialization, receipts |
| `workflow.py` | workflow-v1/v2 validation and adaptation, node/artifact/input/rework contracts, graph safety, selected-definition identity |
| `delivery.py` | Delivery-contract validation, digests and seals, decisions, action bindings, input resolution, freshness, coverage, dossier generation |
| `engine.py` | Payload validation, action planning, ledger records, assurance routing, revision replay, transition validation, projections and task views |
| `workflows.py` | Official catalog resolution and absolute custom-definition loading |
| `yaml_subset.py` | Strict JSON/YAML-subset parsing with bounded errors |
| `git_client.py` | Content-sensitive read-only repository and resource snapshots |
| `store.py` | Private task paths, locks, revision CAS, replay validation, atomic replacement |
| `controller.py` | Application coordination and every post-creation state mutation |
| `cli.py` | Strict argv/JSON adapter and one JSON response per command |
| `hook.py` | Active-task lookup, exact locator injection, and fail-open data-path guardrails |

## Product and compatibility identities

V6 scopes compatibility independently:

| Surface | Identity boundary |
|---|---|
| product generation | task schema `6`, task identity, and data namespace `v6` |
| workflow language | `dev-flow-workflow/v1` or `dev-flow-workflow/v2` plus its adapter identity |
| selected workflow | digest of selector, schema, adapter, and canonical selected document |
| official catalog | digest of the sorted official IDs; catalog changes do not invalidate an unchanged selected workflow |
| records and artifacts | canonical per-object schema and digest seals |
| driver capability | producer metadata recorded on that artifact |
| agent protocol | `dev-flow-agent-v2`; projection evolution is separate from persisted task replay |

The V6 Hook uses `<PLUGIN_DATA>/v6`. Retained V5 state remains under
`<PLUGIN_DATA>/v5`; V6 does not load, copy, alter, or delete it. A retained V5
package and its V5 locator are required to inspect a V5 task.

## Delivery contract and ledger

Task creation atomically writes revision-zero state with an immutable original
`dev-flow-delivery-contract/v1` and an empty record tuple. An explicit contract
contains exactly:

```json
{
  "schema": "dev-flow-delivery-contract/v1",
  "revision": 1,
  "summary": "Deliver the requested behavior",
  "acceptance_criteria": [
    {"id": "C1", "statement": "Observable acceptance condition"}
  ],
  "scope": ["Included work"],
  "constraints": [],
  "risks": [],
  "non_goals": [],
  "open_questions": []
}
```

A requirement-only start derives a bounded minimal revision-one contract.
Every subsequent successful mutation appends exactly one sealed
`dev-flow-record/v1`; typed outputs use sealed `dev-flow-artifact/v1`
descriptors. Each mutation increments task revision exactly once, preserving:

```text
task revision == record count
```

The first record is always repository preflight. Workflow actions, contract
revisions, and decisions share the same ledger. Replay validates record seals,
workflow transitions, pinned definition identity, append-only history, and the
one-record-per-revision invariant before state is accepted.

A contract revision is available after preflight. Its record contains the
complete next contract, reason, actor label, transition, and a safe current
snapshot exposed as a new-contract `revision-source` artifact. The workflow's
`revision_target` selects reentry (`impact` for the planning workflows and
`implement` for `lite`). This revision source is the only source bridge across
contract digests.

Decision records keep task-unique IDs and bind kind, subject, outcome,
rationale, actor label, and effective contract. Criterion waivers target an
exact acceptance ID. Assurance waivers target an exact workflow node whose
handler is `review.record` (the official node ID is `review`). One
`(kind, subject)` pair is accepted per contract digest.

## Workflow definitions

Official definitions use `dev-flow-workflow/v2`, version `6`. The catalog is
`bugfix`, `feature`, `full`, `investigation`, `lite`, and `refactor`. A custom
workflow is selected by absolute JSON/YAML path. Linear workflow-v1 version-5
documents remain accepted for new V6 tasks through the pinned v1 adapter.

A workflow-v2 document declares `entry`, `revision_target`, `nodes`, and a
shared `cancel` action. Each non-terminal node has one normal target. Only
`verification.record` and `review.record` may add a finite failure route and
an exhausted route.

### Node contract

| Field | Rule |
|---|---|
| `action_id` | Unique action selected by the projection |
| `handler` | `preflight`, `artifact.record`, `verification.record`, `review.record`, or `delivery.finalize` |
| `target` | Normal `{node, status}` transition |
| `payload` | Exact required field-to-type map; unknown or missing fields fail |
| `artifact` | Required `{type, workspace, inputs}` declaration for workflow-v2 action nodes |
| `rework` | Assurance-only `{failure, max_attempts, exhausted}` contract |
| `finalize` | `success` or `incomplete` on a `delivery.finalize` node |
| `driver` | Opaque capability metadata, including optional fallback and produced artifact |
| `effect` | `git.inspect-repository` for preflight; `none` elsewhere |
| `writes` | If present, must equal the handler-derived V6 record write set |
| `terminal` | `true` defines an action-free sink |

Payload types are `string`, `boolean`, `integer`, `object`, and `sha256`.
Validation requires one preflight entry, unique action IDs, reachable nodes,
valid terminal dossier paths, and a cancel target with `CANCELLED`. Removing
all finite assurance-failure edges must leave an acyclic graph, so every
possible rework cycle consumes a declared attempt budget.

### Artifact lineage

Each workflow-v2 artifact declares a workspace role:

- `context`: read-only analysis that cannot authorize a worktree change;
- `produces-source`: exactly one `source-predecessor` is pinned, then the
  successor snapshot is recorded atomically;
- `verifies-source`: verification, review, and finalization observe the latest
  source authority exactly.

Input edges carry distinct semantics:

- `governing` selects the latest current artifact of its type and propagates
  replacement or resource staleness;
- `source-predecessor` identifies the source authority intentionally consumed
  by a source-producing action;
- `causal` retains the failed verification or review that motivated rework
  without making that addressed failure current completion proof.

Artifact envelopes contain type, schema and digest, producer action/node and
attempt, effective contract revision/digest, workspace role, observed
repository snapshot, resolved input record/artifact digests, bound resources,
and bounded body content. The controller derives provenance fields; the action
payload does not supply them.

### Repository resources and freshness

A source-producing planning payload may declare repository-relative resources:

```json
{
  "items": [
    {"path": "openspec/changes/example/proposal.md", "role": "governing", "normalizer": "none"},
    {"path": "openspec/changes/example/tasks.md", "role": "governing", "normalizer": "openspec-tasks-v1"},
    {"path": "openspec/changes/example/tasks.md", "role": "reported", "normalizer": "none"}
  ]
}
```

`governing` digests participate in artifact freshness even for Git-clean
files. `reported` digests preserve provenance. `openspec-tasks-v1` canonicalizes
only Markdown task checkbox markers; text, ordering, and test obligations
remain governing bytes.

Freshness is derived from immutable history plus the current safe snapshot.
Contract changes, missing or replaced inputs, changed governing resources,
newer source producers, workspace drift, and superseded artifact types produce
explicit stale reasons. Stale evidence remains visible but is excluded from
current coverage and successful finalization.

## Action binding and mutation boundary

`next` resolves inputs before work begins and emits a sealed
`dev-flow-action-binding/v1` containing:

- task ID and task revision;
- action and node IDs;
- effective contract revision and digest;
- typed input record, record digest, artifact digest, snapshot digest, and
  edge kind;
- the source predecessor, when declared;
- the starting workspace snapshot digest;
- the binding digest.

Every `apply` must return that exact object with `--binding-json`. The
controller loads state and the pinned definition, validates action/payload,
captures requested resources and the apply-time snapshot, locks and reloads,
performs revision CAS, verifies the binding and lineage, appends one sealed
record, validates replay, and atomically replaces state.

```text
next → pinned action binding → perform one action → apply with binding
     → snapshot/lineage/CAS validation → append record → fresh projection
```

Context and verifying actions require the current snapshot to equal the bound
starting snapshot. A source-producing action may change the worktree and links
the bound predecessor snapshot to its successor. Concurrent advancement
returns `REVISION_CONFLICT` with `error.details.projection`; the caller obtains
a fresh `next` action and does not replay stale work.

## Assurance and Delivery Dossier

Verification records `passed`, the non-empty command, a summary, and coverage
for every current criterion as `proven` or `unverified`. A current criterion
waiver derives `waived`. Successful coverage contains only proven or waived
criteria.

Review records outcome (`approved`, `changes-requested`, or `unavailable`) and
assurance (`independent` or `self`). Independent approval succeeds. An
unavailable review succeeds only with an exact current assurance-waiver for
that review node. Other results follow the finite rework or exhausted route.
Attempts are counted by node ID and effective contract digest, so a contract
revision starts the full declared budget for its new scope.

`delivery.finalize` generates the authoritative
`dev-flow-delivery-dossier/v1` body inside the pure domain layer. Successful
finalization requires fresh passing verification, complete current coverage,
and any declared review input to contain independent approval or an exact
waiver. Exhausted routes generate an `INCOMPLETE` dossier with unresolved
coverage and retained failed assurance.

## Agent projection and task view

`next` returns compact `dev-flow-agent-v2` JSON with one current action:

```json
{
  "schema": "dev-flow-agent-v2",
  "task_id": "task-example",
  "revision": 3,
  "workflow": {"id": "lite", "version": 6, "schema": "dev-flow-workflow/v2"},
  "status": "VERIFYING",
  "current_node": "verify",
  "contract": {"revision": 1, "digest": "<sha256>", "summary": "...", "criterion_ids": ["C1"]},
  "repository": {"id": "repo-id", "path": "/absolute/repo", "snapshot": {"digest": "<sha256>"}},
  "freshness": {},
  "action": {
    "action_id": "verification.record",
    "payload": {"passed": "boolean", "command": "string", "coverage": "object", "summary": "string"},
    "inputs": [],
    "binding": {"schema": "dev-flow-action-binding/v1", "digest": "<sha256>"},
    "retry_budget": {"attempts_used": 0, "max_attempts": 2, "remaining": 2}
  },
  "dossier": null,
  "done": false
}
```

Terminal projections set `action` to `null`, `done` to `true`, and expose a
compact dossier summary. `show` returns the full read-only task state,
effective contract, current snapshot, artifact freshness, and dossier summary;
full dossier content remains in its ledger artifact.

## Persistence and public bootstraps

```text
<PLUGIN_DATA>/
  v5/                              # retained V5 tasks; V6 never reads them
  v6/
    tasks/<task-id>/state.json
    locks/<task-id>.lock
```

Private directories and files use local-account-only permissions. State paths
cannot overlap the target repository. Symlinks and malformed state fail
closed; writes use a task lock and atomic replacement.

`scripts/dev_flow_python_launcher` selects a supported interpreter and runs
the fixed CLI or Hook bootstrap. The Hook registers `SessionStart`,
`UserPromptSubmit`, and `PreToolUse`, injects the exact installed V6 locator
and fresh projection, and guards direct writes to the plugin data root. Hook
internal errors fail open and never mutate task state.
