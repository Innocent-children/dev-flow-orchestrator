---
name: review-dev-flow-change
description: Independently review one V6 task's exact current single-repository snapshot and return a bounded verdict bound to base revision, artifact digest, guidance snapshot digest, and workspace snapshot. Use for an official review.record stage or a read-only pre-handoff review.
---

# Review Dev Flow Change

Perform a fresh, read-only review. Do not edit repository files, OpenSpec
artifacts, Git state, controller state, task records, or evidence.

## Build the exact review snapshot

Collect from the V6 projection and full read-only task view:

- task/workflow/node ID, effective contract revision and digest;
- repository path and current review action binding;
- `base_revision`: the `HEAD` recorded by the current contract's repository
  baseline or `revision-source`;
- `workspace_snapshot_digest`: the action binding's
  `starting_snapshot_digest`;
- every current input `record_id`, `record_digest`, `artifact_digest`,
  `snapshot_digest`, type, and edge;
- every current governing resource path, normalizer, and semantic digest;
- requirement, criteria, scope, constraints, risks, non-goals, decisions, and
  applicable repository guidance.

Derive two lowercase SHA-256 values from UTF-8 canonical JSON (object keys
sorted, no insignificant whitespace, arrays kept in declared order):

- `artifact_digest`: digest the current action-input manifest listed above;
- `guidance_snapshot_digest`: digest the sorted manifest of every governing
  contract/guidance/resource input actually used by the review, including its
  path or stable label, normalizer, and semantic/content digest.

Record the manifests as well as their digests. Never invent a missing digest.
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

1. Compare committed changes from `base_revision` through current `HEAD`.
2. Inspect staged, unstaged, and every untracked non-ignored path.
3. Account for renames, deletions, modes, symlinks, gitlinks/submodules,
   generated files, and bound governing resources.
4. Map every acceptance criterion, scope item, constraint, and non-goal to
   implementation and focused test evidence.
5. Inspect correctness, error paths, boundary inputs, interruption, retry,
   concurrency, idempotency, authorization, secret handling, path safety,
   persistence/replay, and documentation where applicable.
6. Use the explicitly selected current-workspace codebase-memory project for
   discovery and confirm every material finding in source. Mark graph evidence
   stale or degraded when its generation cannot be matched.
7. Recompute or re-read the base, artifact, guidance, and workspace snapshot
   fingerprints after review. Any drift invalidates the entire result; obtain
   a new action binding and rerun.

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
findings, but it cannot return independent approval.

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
  "schema": "dev-flow-independent-review/v1",
  "status": "available",
  "verdict": "PASS",
  "assurance": "independent",
  "snapshot": {
    "base_revision": "<git object id>",
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

Lead `findings.items` with highest severity and include path/symbol, consequence,
smallest sufficient resolution, and required re-review evidence. Use an empty
array and the summary `No actionable findings` when appropriate.

Compute `review_fingerprint` over the complete canonical result excluding the
`review_fingerprint` field. This fingerprint identifies the bounded review
artifact; it is not an authenticated actor identity.
