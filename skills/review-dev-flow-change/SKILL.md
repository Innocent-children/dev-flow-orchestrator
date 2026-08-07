---
name: review-dev-flow-change
description: Independently review one 0.4.0 task's complete roll-forward task-owned slice and its direct or indirect effects across one to eight repositories, returning bounded structured causal findings bound to the plan, manifest, guidance, reviewer, and snapshot. Use for an independent-review assurance obligation or read-only pre-handoff review.
---

# Review Dev Flow Change

Review the complete roll-forward task-owned slice and its direct or indirect
effects. Emit at most 64 structured causal findings using
`dev-flow-review-finding/0.4.0`. Each finding binds the contract, plan, manifest,
review scope, guidance, reviewer, and workspace digests and classifies causality
as `introduced`, `affected`, `pre-existing`, `out-of-scope`, or `unknown`.
`affected` requires a bounded source-confirmed causal path from at least one
current manifest entry. An affected location outside the plan closure is an
impact gap; a blocking unknown stays in causal triage. Preserve pre-existing and
out-of-scope observations without requesting task rework. Do not submit an
aggregate verdict as authority: the controller derives approval, rework,
triage, or unavailability from the validated findings.

Perform a fresh, read-only review. Do not edit repository files, OpenSpec
artifacts, Git state, controller state, task records, or evidence.

## Build the exact review snapshot

Collect from the 0.4.0 projection and full read-only task view:

- task/workflow/node ID, effective contract revision and digest;
- repository-set ID and complete canonical member inventory, plus the current
  review action binding;
- each member's repository ID and `HEAD` from the current contract's baseline
  or aggregate `revision-source`;
- `workspace_snapshot_digest`: the action binding's
  `starting_snapshot_digest`, which is the aggregate repository-set digest;
- every current input `record_id`, `record_digest`, `artifact_digest`,
  `snapshot_digest`, type, edge, and member scope when present;
- every current governing resource's repository ID, path, normalizer, and
  semantic digest;
- requirement, criteria, scope, constraints, risks, non-goals, decisions, and
  applicable guidance for every member.

Derive two lowercase SHA-256 values from UTF-8 canonical JSON (object keys
sorted, no insignificant whitespace, arrays kept in declared order):

- `artifact_digest`: digest the current action-input manifest listed above;
- `guidance_snapshot_digest`: digest the sorted manifest of every governing
  contract/guidance/resource input actually used by the review, including its
  repository ID, path or stable label, normalizer, and semantic/content digest.

Include the canonical member and per-member base/snapshot manifests in the
fingerprinted review input. Never default to one member,
reorder or omit a member, or treat equal relative paths from different members
as the same resource. Record the manifests as well as their digests. Never
invent a missing digest.
If the base, inputs, guidance, or workspace cannot be bound exactly at the
start, return `unavailable` and do not issue independent approval. If a bound
snapshot later drifts, discard that attempt, obtain a fresh action binding,
and rerun; return no result that could be applied with the stale binding.

For OpenSpec-governed work, run the current read-only queries:

```text
openspec status --change <change-id> --json
openspec instructions <current-artifact-or-apply> --change <change-id> --json
```

Select the current artifact or apply phase from the returned status. Read the
concrete paths returned by OpenSpec. Do not assume a fixed phase sequence.

## Inspect the complete change

1. In every member, compare committed changes from its recorded base revision
   through current `HEAD`.
2. In every member, inspect staged, unstaged, and every untracked non-ignored
   path.
3. Account for renames, deletions, modes, symlinks, gitlinks/submodules,
   generated files, and repository-scoped governing resources.
4. Map every acceptance criterion, scope item, constraint, and non-goal to
   implementation and focused test evidence.
5. Inspect correctness, error paths, boundary inputs, interruption, retry,
   concurrency, idempotency, authorization, secret handling, path safety,
   persistence/replay, and documentation where applicable.
6. For each repository ID, use its explicitly selected current-workspace
   codebase-memory project for discovery, inspect cross-repository contracts,
   and confirm every material finding in the corresponding source. Never share
   a graph project across members. Mark graph evidence stale or degraded when
   its member generation cannot be matched.
7. Recompute or re-read every member base, artifact, guidance, member snapshot,
   and aggregate workspace fingerprint after review. Drift in any member
   invalidates the entire result; obtain a new action binding and rerun.

Use existing focused command results only when they are bound to the reviewed
snapshot. State skipped, external, platform-specific, or manual checks
precisely.

## Classify assurance and verdict

Use exactly one review status:

- `available`: a separate reviewer inspected the complete stable snapshot and
  all required evidence; verdict may be `PASS` or `FAIL`;
- `degraded`: a separate reviewer inspected the stable snapshot but a material
  evidence channel remains incomplete; verdict is `CONDITIONAL` or `FAIL`,
  never `PASS`;
- `unavailable`: no separate reviewer can be used or an exact snapshot cannot
  be stabilized after refresh; verdict is `UNAVAILABLE` and assurance is
  `self`.

Independence comes from a genuinely separate reviewer context. The Skill name
alone does not establish independence. A self-review can report useful
findings, but it cannot return independent approval. Assurance belongs to the
whole task: never approve members independently or reuse an unchanged member's
partial approval after aggregate drift.

Use verdicts as follows:

- `FAIL`: a blocking defect, unmet requirement, failing required check, unsafe
  behavior, or demonstrably incomplete implementation;
- `CONDITIONAL`: no blocking defect is demonstrated, but a material evidence
  or external condition remains;
- `PASS`: the independent complete stable review has no blocking or
  conditional finding;
- `UNAVAILABLE`: independent assurance was not produced for the exact
  snapshot.

## Return the review artifact

Return one JSON-compatible object:

```json
{
  "schema": "dev-flow-independent-review/0.4.0",
  "status": "available",
  "verdict": "PASS",
  "assurance": "independent",
  "snapshot": {
    "repository_set_id": "<repository-set-id>",
    "repositories": {
      "<repository-id>": {
        "root": "<absolute-worktree-root>",
        "base_revision": "<git-object-id>",
        "head_revision": "<git-object-id>",
        "workspace_snapshot_digest": "<member-sha256>"
      }
    },
    "workspace_snapshot_digest": "<sha256>",
    "artifact_digest": "<sha256>",
    "guidance_snapshot_digest": "<sha256>",
    "input_manifest": [],
    "guidance_manifest": []
  },
  "findings": {"items": []},
  "criterion_results": {},
  "test_evidence": {"observed": [], "skipped": []},
  "limitations": [],
  "summary": "No actionable findings",
  "review_fingerprint": "<sha256>"
}
```

The `snapshot` always binds the canonical repository-set inventory, every
member's base and snapshot summary, the aggregate `workspace_snapshot_digest`,
and repository-scoped input and guidance manifests. This is unchanged when the
exact set has one member. `criterion_results`, findings, and test evidence
cover the complete set and its integration behavior; they do not express
per-member approval. Return one verdict and one fingerprint for the aggregate
snapshot.

Lead `findings.items` with highest severity and include path/symbol, consequence,
smallest sufficient resolution, and required re-review evidence. Use an empty
array and the summary `No actionable findings` when appropriate.

Compute `review_fingerprint` over the complete canonical result excluding the
`review_fingerprint` field. This fingerprint identifies the bounded review
artifact; it is not an authenticated actor identity.
