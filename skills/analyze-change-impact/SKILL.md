---
name: analyze-change-impact
description: Produce a bounded, read-only V6 change-impact artifact for one repository with phase-selected codebase-memory evidence, distinct baseline and current-workspace project IDs, and direct source confirmation. Use for impact, diagnosis, or structural-analysis workflow stages before implementation.
---

# Analyze Change Impact

Produce one source-confirmed impact report. Do not modify source, OpenSpec,
Git state, controller state, or task evidence.

## Bind the analysis input

Read the current V6 projection or supplied review packet and retain:

- task ID, workflow ID, node ID, and analysis `phase`;
- effective contract revision/digest and acceptance IDs;
- repository root and bound workspace snapshot digest;
- current input record IDs, record/artifact digests, and edge kinds;
- requirement, scope, constraints, risks, non-goals, and open questions.

Use only the one declared repository. Mark missing or contradictory input as a
limitation; never reconstruct controller-owned provenance.

## Select codebase-memory projects by phase

Keep these identities distinct:

- `baseline_project_id`: a graph indexed from the recorded baseline snapshot;
- `current_project_id`: a graph indexed from the current bound workspace
  generation.

Never reuse one project ID for both generations. Record the snapshot identity
associated with each project. Select exactly one `selected_project_id` for the
current phase:

- use the baseline project only for baseline questions;
- use the current project for current implementation/impact questions;
- use both explicit IDs for a delta comparison and label which claim came from
  which generation.

If an exact baseline checkout/index is unavailable, leave its project ID null
and mark graph coverage degraded. Do not create a substitute baseline from the
current worktree. If the current graph cannot be refreshed or its snapshot
identity is uncertain, inspect source directly and mark the graph stale or
unavailable.

## Discover, then confirm

1. Use `search_graph` to find symbols, classes, routes, and variables.
2. Use `trace_path` for callers, callees, and data flow.
3. Use `get_code_snippet` for exact definitions found by graph search.
4. Use repository text search for string literals and non-code files, or when
   graph results are insufficient.
5. Use `get_architecture` only for orientation or an unclear boundary.
6. Confirm every material graph conclusion in the actual source at the bound
   workspace. Cite repository-relative paths and symbols.

Treat graph results as discovery evidence. Classify each conclusion as
`confirmed`, `inferred`, or `unknown`. A graph-only material claim is
unconfirmed and makes the report degraded.

## Return the bounded artifact

Return one JSON-compatible `driver_result` object. Use the shared driver
envelope at the top level and place the complete tool-specific impact report
inside `driver_result.details`:

```json
{
  "schema": "dev-flow-driver-result/v1",
  "tool": "codebase-memory",
  "status": "available",
  "phase": "impact",
  "details": {
    "schema": "dev-flow-impact-report/v1",
    "status": "available",
    "phase": "impact",
    "contract_digest": "<sha256>",
    "workspace_snapshot_digest": "<sha256>",
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
    "selected_project_id": "<phase-selected id>",
    "affected": {"components": [], "symbols": [], "contracts": [], "tests": []},
    "confirmed": [],
    "inferred": [],
    "unknowns": [],
    "risks": [],
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
