# Architecture

## 0.4.0 compatibility model: task capsule and adaptive assurance

The immutable membership tuple stores each canonical worktree root, its
worktree-specific Git administrative directory, and its common Git directory.
A data-directory-wide admission lock derives active leases from valid
non-terminal model 0.4.0 state. Corrupt current inventory blocks admission; retained
0.2 namespaces are outside discovery and are never read, repaired, migrated,
or deleted.

`capsule.py` separates the immutable preflight baseline, cumulative task-owned
manifest, exact ownership claims, and ambient drift. `assurance.py` is the pure
closed-policy planner and budget authority. It groups obligations canonically,
derives finite per-obligation and aggregate ceilings, and selects one eligible
outstanding obligation. `review.py` validates stable causal findings and derives
review outcomes without treating an agent verdict as authority. The engine
persists plans and executions in sealed `dev-flow-record/0.4.0` and
`dev-flow-artifact/0.4.0` lineage, replays their bindings, and projects the
current obligation through `dev-flow-agent/0.4.0`.

The terminal `dev-flow-delivery-dossier/0.4.0` includes the preflight origin,
roll-forward manifest, impact closure, plan rationale, obligation states,
budgets, structured review state, aggregate snapshot freshness, and an
explainable `DONE` or `INCOMPLETE` decision.

[简体中文](ARCHITECTURE_CN.md)

The current Dev Flow release uses compatibility model 0.4.0 and one Python-standard-library package with one
controller mutation boundary, an append-only delivery ledger, and declarative
workflow definitions. It supports one task over an exact canonical set of one
to eight user-prepared local Git worktrees, with one current action and one
Codex executor.

## Dependency direction

```text
CLI ─────┐
Hook ────┼─> Controller ─┬─> Engine ─> Delivery ─> Model
Web UI ──┘               │       └────> Workflow ─> Product
                         ├─> Store ───> Engine
                         │      └─────> Filesystem primitives
                         ├─> Web views (bounded projections)
                         ├─> Workflows ─> yaml_subset
                         └─> GitClient (bounded, read-only)
```

The domain layer (`model.py`, `product.py`, `snapshot.py`, `workflow.py`,
`delivery.py`, and `engine.py`) performs no filesystem, process, environment,
or network I/O.
`workflows.py` loads packaged or selected definitions. `GitClient` is the one
target-repository inspection port, invoked serially for every task member.
Drivers are instructions executed by Codex
outside the controller; the runtime only validates and records their declared
results.

## Local read-only presentation boundary

`web.py` is a standard-library loopback adapter under the existing 0.4.0
product identity. It binds only `127.0.0.1`, owns an ephemeral process token,
serves a fixed same-origin asset/API route set, enforces exact Host and Origin
checks, rejects cross-site Fetch Metadata and unsafe methods, and emits no CORS
allowance. Native HTML, CSS, and JavaScript assets use no build step, external
resource, telemetry, service worker, cookie, or persistent browser storage.

`web_views.py` owns bounded presentation projections. Inventory and stored
detail call `TaskStore.inspect_inventory()` and `inspect_with_definition()`,
which traverse no-follow file-descriptor chains without acquiring locks,
creating directories, changing modes, or writing caches. Authoritative
controller operations retain their existing locks, revision CAS, replay, and
atomic replacement behavior.

Live detail is an explicit selected-task operation. It captures one existing
aggregate repository-set snapshot and reuses that exact value for task and
agent projections, then rereads persisted state and returns `VIEW_STALE` if the
revision changed. A process-global non-queued slot returns `429` to competing
live requests. Shutdown cancellation terminates the active Git process group;
stored views remain independent of Git and live-capture availability. HTTP
responses never expose raw state, ledger payloads, snapshot entries, bindings,
commands, absolute paths, or raw internal errors.

## Module ownership

| Module | Owns |
|---|---|
| `_version.py` | The single distributable `RELEASE_VERSION`; a release-only bump changes no persisted authority |
| `product.py` | Model 0.4.0 task/workflow/catalog/record/artifact/projection identities, the six official workflow IDs, and the authoritative 1–8 repository-topology capability |
| `model.py` | Immutable task values and canonical repository membership, canonical JSON, stable errors, revision-zero initialization, receipts |
| `snapshot.py` | Aggregate repository-set snapshot and nested member workspace-snapshot validation, lookup, and digesting |
| `workflow.py` | `dev-flow-workflow/0.4.0` validation, node/artifact/input/rework/cancellation contracts, graph safety, selected-definition identity |
| `delivery.py` | Delivery-contract validation, digests and seals, decisions, action bindings, input resolution, freshness, coverage, dossier generation |
| `engine.py` | Payload validation, action planning, ledger records, assurance routing, revision replay, transition validation, projections and task views |
| `workflows.py` | Official catalog resolution and absolute custom-definition loading |
| `yaml_subset.py` | Strict JSON/YAML-subset parsing with bounded errors |
| `git_client.py` | Content-sensitive read-only repository and resource snapshots |
| `store.py` | Private task paths, locks, revision CAS, replay validation, atomic replacement |
| `controller.py` | Application coordination and every post-creation state mutation |
| `cli.py` | Strict argv/JSON interface, installed Codex data-root discovery, and one JSON response per command |
| `hook.py` | Active-task lookup, exact locator injection, and fail-open data-path guardrails |
| `web.py` | Authenticated loopback server, fixed routes, security policy, foreground and managed-process lifecycles, and live-capture admission |
| `web_views.py` | Bounded inventory, stored detail, live detail, timeline, Dossier, and recovery projections |

## Current product identities

`PRODUCT_IDENTITY` seals the complete current authority: task, record,
artifact, action-binding, repository-set snapshot, nested workspace snapshot,
workflow, agent, verification-coverage, Delivery-Dossier, data
namespace, and the one-to-eight repository topology. A task whose stored
product identity differs fails closed.

| Surface | Current identity boundary |
|---|---|
| distributable release | `RELEASE_VERSION`, shared by plugin/package/lock metadata and presentation receipts |
| compatibility model | `MODEL_VERSION` `0.4.0`, task identity, data namespace `0.4.0`, and the exact topology authority |
| workflow language | `dev-flow-workflow/0.4.0`, version `0.4.0` |
| selected workflow | digest of selector, schema, and canonical selected document |
| official catalog | digest of the sorted official IDs; catalog identity is separate from a task's selected workflow |
| records, artifacts, and bindings | current canonical schema and digest seals for each value |
| agent projection | `dev-flow-agent/0.4.0` with one `repository_set` and one current action |
| verification coverage | exact `schema: dev-flow-verification-coverage/0.4.0` with `criteria`, `repositories`, and `integration` |
| repository snapshot | `dev-flow-repository-set-snapshot/0.4.0` containing one `dev-flow-workspace-snapshot/0.4.0` per member |
| Delivery Dossier | `dev-flow-delivery-dossier/0.4.0` |

The 0.4.0 Hook and controller use `<PLUGIN_DATA>/0.4.0` for current task state.

## Repository-set boundary

`start` accepts one to eight repeated `--repo` values. The controller resolves
each value to the exact canonical root of an existing non-bare Git worktree,
rejects duplicate roots, overlapping roots, shared Git common directories, and
data-directory overlap, then sorts the resulting `{id, path}` records by
canonical path and repository ID. Caller order has no semantic meaning.
`TaskState.repositories` is the only persisted membership authority; its
derived `repository_set_id` is not a second mutable copy. Membership cannot be
added, removed, replaced, moved, or reordered after revision zero.

Every member worktree is prepared and owned by the user. The controller does
not create or switch branches/worktrees, publish Git changes, run parallel
agents, or operate external CI, PR, or release systems. One Codex executes the
one projected action over the complete set. The Hook can discover the task
from any member root, but refuses an ambiguous match. A missing or moved member
blocks every repository-dependent mutation without partial evidence; stored
ledger inspection remains available until the exact persisted root is restored.

## Delivery contract and ledger

Task creation atomically writes revision-zero state with an immutable original
`dev-flow-delivery-contract/0.4.0` and an empty record tuple. An explicit contract
contains exactly:

```json
{
  "schema": "dev-flow-delivery-contract/0.4.0",
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
`dev-flow-record/0.4.0`; typed outputs use sealed `dev-flow-artifact/0.4.0`
descriptors. Each mutation increments task revision exactly once, preserving:

```text
task revision == record count
```

The first non-cancellation record is preflight for the complete immutable
repository set. A cancellation explicitly declared for the entry stage may be
the only task record. Workflow actions, contract revisions, decisions, and
cancellation share the same ledger. Replay validates record seals,
workflow transitions, pinned definition identity, append-only history, and the
one-record-per-revision invariant before state is accepted.

A contract revision is available after preflight. Its record contains the
complete next contract, reason, actor label, transition, and a safe current
snapshot exposed as a new-contract `revision-source` artifact. This is always
one aggregate snapshot and one record; no member commits separately. The workflow's
`revision_target` selects reentry (`impact` for the planning workflows and
`implement` for `lite`). This revision source is the only source bridge across
contract digests.

Decision records keep task-unique IDs and bind kind, subject, outcome,
rationale, actor label, and effective contract. Criterion waivers target an
exact acceptance ID. Assurance waivers target an exact workflow node whose
handler is `review.record` (the official node ID is `review`). One
`(kind, subject)` pair is accepted per contract digest.

## Workflow definitions

Official definitions use `dev-flow-workflow/0.4.0`, version `0.4.0`. The catalog is
`bugfix`, `feature`, `full`, `investigation`, `lite`, and `refactor`. A custom
workflow is selected by absolute JSON/YAML path and passes the same 0.4.0 workflow
validation and selected-identity calculation as an official definition.

A `dev-flow-workflow/0.4.0` document declares `entry`, `revision_target`, `nodes`, and a
shared `cancel` action with a non-empty, unique `stages` list. Cancellation is
available only when the current node appears in that list. Official workflows
list the normal majority of non-terminal stages and omit every
`delivery.finalize` node. Each non-terminal node has one normal target. Only
`verification.record` and `review.record` may add a finite failure route and
an exhausted route.

### Node contract

| Field | Rule |
|---|---|
| `action_id` | Unique action selected by the projection |
| `handler` | `preflight`, `artifact.record`, `verification.record`, `review.record`, or `delivery.finalize` |
| `target` | Normal `{node, status}` transition |
| `payload` | Exact required field-to-type map; unknown or missing fields fail |
| `artifact` | Required `{type, workspace, inputs}` declaration for 0.4.0 workflow action nodes |
| `rework` | Assurance-only `{failure, max_attempts, exhausted}` contract |
| `finalize` | `success` or `incomplete` on a `delivery.finalize` node |
| `driver` | Opaque capability metadata, including optional fallback and produced artifact |
| `effect` | `git.inspect-repository` for preflight; `none` elsewhere |
| `writes` | If present, must equal the handler-derived 0.4.0 record write set |
| `terminal` | `true` defines an action-free sink |

The top-level `cancel.stages` list may contain only declared non-terminal node
IDs. Its shared action uses `artifact.record`, an exact `reason: string`
payload, and a `CANCELLED` terminal target.

Payload types are `string`, `boolean`, `integer`, `object`, and `sha256`.
Validation requires one preflight entry, unique action IDs, reachable nodes,
valid terminal dossier paths, and a cancel target with `CANCELLED`. Removing
all finite assurance-failure edges must leave an acyclic graph, so every
possible rework cycle consumes a declared attempt budget.

### Artifact lineage

Each `dev-flow-workflow/0.4.0` artifact declares a workspace role:

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

Every repository-backed observation uses
`dev-flow-repository-set-snapshot/0.4.0`. It wraps one complete validated
`dev-flow-workspace-snapshot/0.4.0` per canonical repository; its aggregate digest
covers the set ID, ordered IDs, and complete nested snapshots. A one-member set
contains one nested member and uses the same wrapper. The two-pass capture must
stabilize as a whole or the mutation records nothing.

A source-producing planning payload may declare repository-relative resources.
Every item requires `repository_id`:

```json
{
  "items": [
    {"repository_id": "repo-api", "path": "openspec/changes/example/proposal.md", "role": "governing", "normalizer": "none"},
    {"repository_id": "repo-api", "path": "openspec/changes/example/tasks.md", "role": "governing", "normalizer": "openspec-tasks/0.4.0"},
    {"repository_id": "repo-docs", "path": "openspec/changes/example/tasks.md", "role": "reported", "normalizer": "none"}
  ]
}
```

Resource identity is `(repository_id, path, role, normalizer)`. Unknown member
IDs, absolute or escaping paths, cross-root resolution, and duplicate scoped
keys fail; equal relative paths in different members remain distinct.
`governing` digests participate in artifact freshness even for Git-clean
files. `reported` digests preserve provenance. `openspec-tasks/0.4.0` canonicalizes
only Markdown task checkbox markers; text, ordering, and test obligations
remain governing bytes.

Freshness is derived from immutable history plus the current safe task
snapshot. For a repository set, drift in any member conservatively stales the
aggregate source, verification, review, and Dossier evidence. The current core
does not reuse assurance from unchanged members.
Contract changes, missing or replaced inputs, changed governing resources,
newer source producers, workspace drift, and superseded artifact types produce
explicit stale reasons. Stale evidence remains visible but is excluded from
current coverage and successful finalization.

## Action binding and mutation boundary

`next` resolves inputs before work begins and emits a sealed
`dev-flow-action-binding/0.4.0` containing:

- task ID and task revision;
- action and node IDs;
- effective contract revision and digest;
- typed input record, record digest, artifact digest, snapshot digest, and
  edge kind;
- the source predecessor, when declared;
- the starting aggregate repository-set snapshot digest;
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

Context and verifying actions require every member of the current snapshot to
equal the bound starting snapshot. A source-producing action may change any
subset of user-owned worktrees and links one complete predecessor snapshot to
one complete successor snapshot. Concurrent advancement
returns `REVISION_CONFLICT` with `error.details.projection`; the caller obtains
a fresh `next` action and does not replay stale work.

## Assurance and Delivery Dossier

Verification records `passed`, the non-empty command, a summary, and coverage
for every current criterion as `proven` or `unverified`. A current criterion
waiver derives `waived`. Successful coverage contains only proven or waived
criteria.

Coverage always uses the `dev-flow-verification-coverage/0.4.0` contract with
exact `schema`, `criteria`, `repositories`, and `integration` fields.
The repository map exactly covers the canonical member IDs; every member and
the integration result contains only a non-empty `command` and boolean
`passed`. The top-level command equals the integration command, and top-level
`passed` equals the conjunction of every member and integration result. Command
success with an unverified, unwaived criterion is a well-shaped unsuccessful
assurance attempt and consumes the bounded rework route.

Review records outcome (`approved`, `changes-requested`, or `unavailable`) and
assurance (`independent` or `self`). Independent approval succeeds. An
unavailable review succeeds only with an exact current assurance-waiver for
that review node. Other results follow the finite rework or exhausted route.
Attempts are counted by node ID and effective contract digest, so a contract
revision starts the full declared budget for its new scope.

`delivery.finalize` generates the authoritative
`dev-flow-delivery-dossier/0.4.0` body inside the pure domain layer. It contains
set identity, canonical member baseline/final summaries, changed-member
diagnostics, scoped resources, all verification and review attempts, current structured
verification, and aggregate freshness. Successful finalization requires fresh
passing evidence for the complete set, complete current coverage, and any
declared review input to contain independent approval or an exact waiver.
Exhausted routes generate one aggregate `INCOMPLETE` dossier with unresolved
member/integration details, coverage, and retained failed assurance.

## Agent projection and task view

`next` returns compact `dev-flow-agent/0.4.0` JSON with one `repository_set` and
one current action for every set size (abridged here):

```json
{
  "schema": "dev-flow-agent/0.4.0",
  "task_id": "task-example",
  "revision": 3,
  "workflow": {"id": "lite", "version": "0.4.0", "schema": "dev-flow-workflow/0.4.0"},
  "status": "VERIFYING",
  "current_node": "verify",
  "contract": {"revision": 1, "digest": "<sha256>", "summary": "...", "criterion_ids": ["C1"]},
  "repository_set": {
    "id": "<derived-set-id>",
    "digest": "<aggregate-snapshot-digest>",
    "repositories": [
      {"id": "repo-api", "path": "/absolute/api", "snapshot": {"digest": "<sha256>"}},
      {"id": "repo-client", "path": "/absolute/client", "snapshot": {"digest": "<sha256>"}}
    ]
  },
  "freshness": {},
  "action": {
    "action_id": "verification.record",
    "payload": {"passed": "boolean", "command": "string", "coverage": "object", "summary": "string"},
    "inputs": [],
    "binding": {"schema": "dev-flow-action-binding/0.4.0", "digest": "<sha256>"},
    "retry_budget": {"attempts_used": 0, "max_attempts": 2, "remaining": 2},
    "verification_coverage": {"fields": ["criteria", "repositories", "integration"]}
  },
  "dossier": null,
  "done": false
}
```

A one-member task uses this exact envelope with one item in
`repository_set.repositories`.

Terminal projections set `action` to `null`, `done` to `true`, and expose a
compact dossier summary. `show` returns the full read-only task state,
effective contract, current aggregate snapshot, artifact freshness, and
dossier summary; full dossier content remains in its ledger artifact. If live
aggregate capture fails, the stored state and Dossier remain available while
the current snapshot and freshness are `null` and `snapshot_error` identifies
the blocked member.

## Persistence and public bootstraps

```text
<PLUGIN_DATA>/
  0.4.0/
    tasks/<task-id>/state.json
    locks/<task-id>.lock
```

Private directories and files use local-account-only permissions. State paths
cannot overlap the target repository. Symlinks and malformed state fail
closed; writes use a task lock and atomic replacement.

`scripts/dev_flow_python_launcher` selects a supported interpreter and runs
the fixed CLI or Hook bootstrap. The Hook registers `SessionStart`,
`UserPromptSubmit`, and `PreToolUse`, injects the exact installed 0.4.0 locator
and fresh projection, and guards direct writes to the plugin data root. Hook
internal errors fail open and never mutate task state.

## Native host integration

The product core, product identity, schemas, workflow catalog, state namespace,
assurance policy, Dossier, and Web UI remain shared. `_platform` owns the two
low-level path, storage, and bounded-process implementations. Host integration
adds only launch and lifecycle edges: POSIX uses
`dev_flow_python_launcher`/shell scripts; Windows uses
`dev_flow_python_launcher.cmd`/PowerShell scripts and a PowerShell-literal
Controller locator.

Every command Hook retains `command` and adds `commandWindows`. Structured
`Write`, `Edit`, and `apply_patch` paths use the runtime comparison boundary
before inventory loading. Shell inspection recognizes the exact generated
locator and obvious protected-data references, remains fail-open for ambiguous
PowerShell, and is documented as a guardrail rather than a security boundary.
