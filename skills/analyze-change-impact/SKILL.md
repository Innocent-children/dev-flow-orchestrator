---
name: analyze-change-impact
description: Produce a bounded, read-only 0.3.0 change-impact artifact for an exact set of one to eight repositories, with per-member phase-selected codebase-memory evidence, a bounded impact closure, closed risk triggers, and direct source confirmation. Use for impact, diagnosis, or structural-analysis workflow stages before implementation or assurance replanning.
---

# Analyze Change Impact

Return a bounded closure with at most 128 entries, deterministic repository/path/
symbol identity, affected cross-repository edges, the closed risk-trigger IDs,
public/documentation/manual/regression flags, limitations, and one confidence.
Use `source-confirmed` only when every material conclusion is confirmed in the
bound source. Normalize degraded, partial, stale, overflowed, or otherwise
uncertain analysis to `unknown` and explicitly request conservative assurance;
never truncate a closure and label it focused.

Produce one source-confirmed impact report. Do not modify source, OpenSpec,
Git state, controller state, or task evidence.

## Bind the analysis input

Read the current 0.3.0 projection or supplied review packet and retain:

- task ID, workflow ID, node ID, and analysis `phase`;
- effective contract revision/digest and acceptance IDs;
- the repository-set ID, every canonical member's repository ID/root/digest,
  and the aggregate repository-set snapshot digest;
- current input record IDs, record/artifact digests, and edge kinds;
- requirement, scope, constraints, risks, non-goals, and open questions.

Use only the immutable declared members. Mark missing or contradictory input
as a limitation; never infer a default member, drop an unavailable member, or
reconstruct controller-owned provenance.

## Select codebase-memory projects by phase

For every `repository_id`, keep these identities distinct:

- `baseline_project_id`: a graph indexed from the recorded baseline snapshot;
- `current_project_id`: a graph indexed from the current bound workspace
  generation.

Never reuse one project ID across generations or repository members. Record
the repository ID and member snapshot identity associated with each project.
Select exactly one `selected_project_id` per member for the current phase:

- use the baseline project only for baseline questions;
- use the current project for current implementation/impact questions;
- use both explicit IDs for a delta comparison and label which claim came from
  which generation.

If an exact member baseline checkout/index is unavailable, leave that project
ID null and mark graph coverage degraded. Do not create a substitute baseline
from the current worktree or another member. If a current graph cannot be
refreshed or its snapshot identity is uncertain, inspect that member's source
directly and mark the graph stale or unavailable. Missing graph evidence for
one member degrades the aggregate report; it does not remove that member.

## Discover, then confirm

1. Use `search_graph` to find symbols, classes, routes, and variables.
2. Use `trace_path` for callers, callees, and data flow.
3. Use `get_code_snippet` for exact definitions found by graph search.
4. Use repository text search for string literals and non-code files, or when
   graph results are insufficient.
5. Use `get_architecture` only for orientation or an unclear boundary.
6. Repeat discovery under each member's selected graph project, then inspect
   explicit cross-repository contracts, APIs, schema changes, or clients.
7. Confirm every material graph conclusion in the actual source at the bound
   member workspace. Cite `repository_id`, repository-relative path, and
   symbol.

Treat graph results as discovery evidence. Classify each member-local and
cross-repository conclusion as `confirmed`, `inferred`, or `unknown`. A
graph-only material claim is unconfirmed and makes the aggregate report
degraded.

## Return the bounded artifact

Return one JSON-compatible `driver_result` object. Use the shared driver
envelope at the top level and place the complete tool-specific impact report
inside `driver_result.details`:

```json
{
  "schema": "dev-flow-driver-result/0.3.0",
  "tool": "codebase-memory",
  "status": "available",
  "phase": "impact",
  "details": {
    "schema": "dev-flow-impact-report/0.3.0",
    "status": "available",
    "phase": "impact",
    "contract_digest": "<sha256>",
    "workspace_snapshot_digest": "<sha256>",
    "repository_set_id": "<repository-set-id>",
    "repositories": {
      "<repository-id>": {
        "root": "<absolute-worktree-root>",
        "workspace_snapshot_digest": "<member-sha256>",
        "baseline": {
          "project_id": "<baseline-project-id>",
          "snapshot_digest": "<baseline-sha256>",
          "status": "available"
        },
        "current": {
          "project_id": "<current-project-id>",
          "snapshot_digest": "<current-sha256>",
          "status": "available"
        },
        "selected_project_id": "<phase-selected-id>",
        "affected": {"components": [], "symbols": [], "contracts": [], "tests": []},
        "confirmed": [],
        "inferred": [],
        "unknowns": [],
        "risks": [],
        "limitations": []
      }
    },
    "cross_repository": {
      "contracts": [],
      "effects": [],
      "unknowns": [],
      "risks": []
    },
    "limitations": []
  },
  "limitations": []
}
```

Set both the envelope `status` and `details.status` to `degraded` when either
required generation is unavailable or stale, a bounded graph query cannot
complete, or any material claim lacks source confirmation. Set both `phase`
fields to the phase from the current action. Preserve the same object shape,
explain each limitation in the impact report, and copy those limitation strings
to the envelope `limitations` list. Do not use `available` to describe partial
graph coverage.

For a Dev Flow action payload, place this entire envelope in `driver_result`
and put a concise source-backed statement in `summary`. Never place the impact
report directly in `driver_result`; it belongs in `driver_result.details`.

The `workspace_snapshot_digest` always binds the aggregate repository-set
snapshot. Record one entry for every canonical `repository_id` under
`details.repositories`, including that member's baseline/current identities,
selected project, affected surface, and limitations. This is the same envelope
when the exact set has one member. Add explicit aggregate cross-repository
contracts, effects, unknowns, risks, and limitations. Never report `available`
when one canonical member is absent, stale, unconfirmed, or silently omitted.
