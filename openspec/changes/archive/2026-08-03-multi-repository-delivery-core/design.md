## Context

The product executes one delivery task over an exact set of one to eight local Git worktree roots prepared by the user. Workflow depth, repository topology, and workspace strategy are independent dimensions. A task has one state machine, one current action, one revision sequence, and one Codex executor. A one-member repository set is the normal minimum cardinality of this model.

Repository-set membership, snapshots, resources, verification, projection, freshness, and completion evidence form one protocol across the complete cardinality range. Runtime code uses only the Python standard library, controller state remains outside every target repository, and Git inspection remains bounded and read-only.

## Goals / Non-Goals

**Goals:**

- Accept one to eight repeated `--repo` arguments and bind one immutable canonical repository set.
- Reject the complete candidate set before task creation when any member or relationship is invalid.
- Capture all members into one sealed repository-set snapshot and commit no partial member evidence.
- Bind every repository-backed resource to an explicit repository ID.
- Bind each current action, artifact, freshness decision, verification result, projection, and Dossier to the complete repository-set snapshot.
- Record structured verification results for every member plus one repository-set integration result.
- Resume an active task from any member repository.
- Use one current workflow language, projection schema, Dossier schema, and product identity authority.
- Expose exactly one semantic product version, `0.2.0`, across every current package and protocol surface.

**Non-Goals:**

- Creating, switching, repairing, or deleting branches or worktrees.
- Staging, committing, merging, rebasing, stashing, cleaning, pushing, opening pull requests, or dispatching external delivery effects.
- Parallel agents, per-repository child tasks, claims, leases, partial assurance reuse, or repository-specific retry budgets.
- Adding, removing, replacing, relocating, or ordering repositories after task creation.
- Filesystem transactions or rollback across user-owned worktrees.

## Decisions

### Make `0.2.0` the sole version authority

`PRODUCT_VERSION = "0.2.0"` is the sole runtime version authority. The plugin manifest, package metadata and lock file contain the same exact value and package validation rejects drift. Task state and workflow documents use the string `0.2.0`; the controller data namespace is also `0.2.0`. Every current schema identifier is derived as `dev-flow-<kind>/0.2.0`, including task, record, artifact, action binding, snapshots, workflow, projection, verification coverage, Dossier, receipt, contracts, driver results, reports, review results, installed evidence, and identity digest domains.

`PRODUCT_IDENTITY` is derived from the current product document, including `PRODUCT_VERSION`, the exact repository-topology bounds, and the accepted current schemas. A change to the version or authority creates a different product identity and does not reinterpret persisted tasks. Component-specific generation constants, independent wire-version suffixes, and names such as V5, V6, workflow-v2, agent-v3, and Dossier-v2 are not part of the current source model.

The workflow language is `dev-flow-workflow/0.2.0`. A selected workflow identity binds exactly its selector, schema, and canonical document. `TaskState` and `WorkflowDefinition` carry no workflow-adapter identity because there is no adapter selection axis. Official and absolute-path custom workflow documents pass the same current validation and identity calculation.

Agent projection uses `dev-flow-agent/0.2.0`. Delivery completion uses `dev-flow-delivery-dossier/0.2.0`. Loading fails closed when task state, a ledger record, selected workflow identity, or an embedded value does not match the current authority. There is no reader, migration, detector, translator, or recovery path for prior development versions.

### Derive one exact canonical repository set

`start` accepts one to eight repeated `--repo` values. The controller resolves each supplied path to its canonical absolute worktree root and performs bounded read-only admission. Every path must be the exact root of an existing non-bare Git worktree. Admission rejects:

- an empty set or more than eight members;
- duplicate roots, including aliases that resolve to the same root;
- two worktrees with the same canonical Git common directory;
- ancestor-descendant overlap between member roots; and
- equality or containment in either direction between any member root and the controller data directory.

Repository records are sorted by byte-stable canonical path and then repository ID; caller order has no semantic meaning. `TaskState.repositories` is the sole persisted membership authority and is immutable. `repository_set_id` is a domain-separated digest over the ordered `{id, path}` records and is exposed in views and embedded snapshots.

Later repository-dependent operations validate every persisted root and the complete set relationships. Content replacement behind the same canonical root is reported as workspace content drift when all persisted membership fields remain unchanged.

### Seal every cardinality in one repository-set snapshot

Every repository-backed operation captures `dev-flow-repository-set-snapshot/0.2.0`:

```json
{
  "schema": "dev-flow-repository-set-snapshot/0.2.0",
  "repository_set_id": "<derived digest>",
  "repositories": [
    {"repository_id": "<id>", "snapshot": {"schema": "dev-flow-workspace-snapshot/0.2.0"}}
  ],
  "digest": "<aggregate digest>"
}
```

The member list exactly matches `TaskState.repositories` in canonical order and contains one through eight entries. Every member snapshot validates in its current member schema and names the persisted root. The aggregate digest covers the schema, set identity, ordered repository IDs, and complete nested snapshots.

The controller partitions resource requests by repository ID, captures every member in canonical order, then repeats the complete capture with identical requests. It publishes the wrapper only when both observations match. A missing, unsafe, unstable, over-budget, changed, or mismatched member fails the operation before ledger mutation. The controller lock and revision compare-and-swap protect the single task mutation; no filesystem transaction is claimed.

### Keep one append-only task ledger

Task creation atomically persists the original contract and immutable repository tuple at revision zero. Every later successful mutation appends exactly one typed record and advances the task revision once. Repository-backed action, cancellation, and contract-revision records contain the complete repository-set snapshot in their existing snapshot field. Artifact snapshots use the same aggregate value. Decision records retain their exact null snapshot, artifact, and binding envelope because task ownership already binds them to immutable membership.

Replay validates the current record vocabulary, seals, transitions, workflow identity, membership, and embedded repository-set snapshots. Earlier records within the same current task remain immutable and replayable. Contract revisions preserve prior-contract evidence as historical task evidence; freshness excludes it from current proof when its governing contract or source authority is stale.

### Scope every resource explicitly

A resource request is keyed by `(repository_id, path, role, normalizer)`. `repository_id` is required for every repository-backed resource, including a one-member set. Unknown IDs, absolute paths, parent traversal, duplicate scoped keys, and cross-root resolution are rejected.

Each member collector receives only its requests. Artifact resource entries include the resolved repository ID, while the nested member snapshot retains the bounded workspace-resource shape. Equal relative paths in different repositories remain distinct scoped resources.

Every action is scoped to the complete repository set. A source-producing action may change any subset of members, but its successor snapshot contains every member. Context and source-verification actions reject drift in any member. There is no per-member scheduler, action binding, source-authority join, or partial ledger append.

### Use one structured verification contract

Every `verification.record` retains the workflow action's top-level payload fields and uses this `coverage` structure:

```json
{
  "criteria": {"criterion-id": "proven"},
  "repositories": {
    "repository-id": {"command": "<command>", "passed": true}
  },
  "integration": {"command": "<command>", "passed": true}
}
```

`criteria` exactly covers the effective acceptance criteria with `proven` or `unverified`. `repositories` exactly covers the canonical repository IDs. Each repository and integration result has only a non-empty bounded `command` and boolean `passed`. The top-level `command` equals `integration.command`; top-level `passed` equals the conjunction of every repository result and the integration result.

Assurance success additionally requires every criterion to be proven or covered by a current valid waiver. A well-shaped command aggregate with unverified, unwaived criteria is recorded as an unsuccessful assurance attempt and follows the workflow's bounded rework or exhaustion route.

### Derive aggregate freshness and completion

Freshness is a pure view over immutable current-model records and the present complete snapshot. Repository-backed artifacts bind the aggregate snapshot, so drift in any member makes affected source authority, verification, review, and Dossier assurance stale. Governing resources are checked by repository ID and path to identify the affected member.

Proof is not reused independently for unchanged members. Per-member snapshot differences and verification results remain visible for targeted rework, while completion remains one aggregate decision over the exact set.

`dev-flow-delivery-dossier/0.2.0` contains the repository-set identity, canonical inventory, per-member baseline and final summaries, changed-member diagnostics, scoped resources, every verification and review attempt with current or stale state, current structured verification, aggregate coverage, current review assurance, documentation, decisions, remaining risks, outcome, and handoff recommendation. `DONE` requires fresh successful evidence for the complete set. Exhausted paths preserve missing or failed member details and attempt history in `INCOMPLETE`.

The `dev-flow-agent/0.2.0` projection exposes one `repository_set` summary and exactly one current action. Terminal projection includes a compact current-Dossier summary. Full records and Dossier content remain in read-only task views.

### Resume and recover against immutable membership

`tasks_for_path` compares the inspected path with every stored member root and returns each active task once. A session may resume the same task from any member. Multiple matching active tasks remain explicitly ambiguous, and Hook internal errors fail open.

Repository-dependent projection, apply, contract revision, cancellation, and non-cancelled finalization validate the complete persisted set. A missing or moved member blocks that mutation with member-specific diagnostics and leaves the ledger unchanged. Pure stored-ledger inspection remains available. Restoring the canonical roots permits retry of the same current action or cancellation.

Cancellation uses the same complete-snapshot, action-binding, revision-CAS, and one-record mutation boundary as other repository-backed actions. Workflow stages declare whether cancellation is available; capture failure commits no cancellation record.

## Risks / Trade-offs

- Repository-set capture is sequential. Two complete matching passes, apply-time recapture, and conservative freshness provide a bounded evidence boundary.
- Up to eight members increase latency and state size. Cardinality and existing per-member path, byte, output, and elapsed-time limits bound the operation.
- One changed member invalidates aggregate proof. Member diagnostics narrow rework while completion remains deterministic.
- Canonical paths make moved worktrees unavailable until the operator restores the exact roots or starts a task for a different set.

## Open Questions

None.
