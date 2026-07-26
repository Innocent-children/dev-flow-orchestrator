# Evidence workflow

## Contents

- [Choose an index mode](#choose-an-index-mode)
- [Run the query funnel](#run-the-query-funnel)
- [Apply query budgets](#apply-query-budgets)
- [Confirm material conclusions](#confirm-material-conclusions)
- [Analyze multiple repositories](#analyze-multiple-repositories)
- [Emit the evidence contract](#emit-the-evidence-contract)
- [Recommend a route](#recommend-a-route)
- [Handle failures](#handle-failures)

## Choose an index mode

Use one mode per repository and record the choice in the report.

| Mode | Choose it when | Tradeoff |
|---|---|---|
| `fast` | Structural discovery, definitions, routes, callers, and ordinary impact analysis are sufficient | Omits similarity and semantic edges |
| `moderate` | Vocabulary differs from the requirement or semantic discovery is likely to reveal relevant code | Adds similarity and semantic edges over filtered files |
| `full` | The repository needs the broadest supported inventory and semantic coverage, and the extra indexing cost is justified | Highest cost; do not select reflexively |

Do not reuse an index merely because a project with the same name exists. When the orchestrated workflow supplies `analysis_workspace.path`, confirm its `HEAD` equals the pinned `base_sha` and index that path instead of the user's possibly dirty or feature-branch worktree. Pass the controller-recommended baseline-specific `name` and `persistence=false`. Otherwise index the supplied repository path and record its current commit and dirt limitations. Retain the exact project identifier returned by the tool; the requested name is not proof of the returned ID.

This skill builds the `baseline` side of Dev Flow's dual-index structure. It does not create or refresh the implementation `workspace` index. Codebase-memory does not select an index automatically: every subsequent query must pass the exact baseline project identifier explicitly. A before/after comparison requires two separately labelled calls, never an ambiguous or mixed project.

## Run the query funnel

### Stage 0: bind the baseline

For every registered repository, verify the pinned analysis workspace, index it once, and retain the exact returned baseline project ID. Do not query a same-named project opportunistically. A missing required index makes that repository and the overall report `degraded`.

### Stage 1: seed narrowly

1. Start from repository-relative paths, exact symbols, routes, schema names, configuration keys, and test names stated by the requirement or visible in source.
2. Call `search_graph` with the exact baseline project ID and a narrow identifier or concept. Use a limit of at most 20.
3. Open the returned candidate source immediately. Confirm its declarations, surrounding implementation, tests, and configuration before broadening the search.
4. Call `get_architecture` only when the implementation location is unknown or the change may cross architecture, entry-point, ownership, route, or boundary concerns. Request only the needed sections; add `file_tree` only when placement remains uncertain.

### Stage 2: expand on an evidence trigger

Expand only to answer a recorded, material question:

- call `trace_path` when callers, dependencies, data flow, regression reach, or cross-service paths remain unresolved;
- call `search_code` for literals, configuration, serialized fields, route strings, error messages, generated content, or test names that graph search may miss;
- call `get_code_snippet` only after obtaining an exact `qualified_name`;
- paginate only when a relevant result is truncated, after first narrowing the query.

Use `calls` inbound/outbound for dependants and dependencies, `data_flow` for validation/transformation/persistence, and tests when mapping regression coverage. Treat `risk_labels` as prioritization evidence, not final severity. Prefer source whenever source and graph disagree.

Use native repository search for generated, configuration, or unsupported file types. Record that evidence alongside graph evidence rather than hiding the fallback.

### Stage 3: expand across repositories only on signal

Run cross-repository matching only when the task registers multiple repositories or current source/graph evidence identifies a cross-service route, client, event, channel, schema, or shared contract. Follow [Analyze multiple repositories](#analyze-multiple-repositories). Do not spend cross-repository queries merely to prove that an already bounded single-repository change is bounded.

### Stage 4: close the completeness checks

For each registered repository, resolve or explicitly classify:

- `orientation`: relevant location and architectural boundary;
- `candidates`: affected files and symbols;
- `paths`: material inbound, outbound, data-flow, and cross-service paths;
- `contracts`: APIs, events, schemas, migrations, configuration, security, compatibility, and rollout contracts;
- `tests`: existing assertions and required regression coverage;
- `source_confirmation`: material graph findings checked in current pinned source.

Each check is `complete`, `not_applicable`, or `degraded`. `not_applicable` and `degraded` require a specific reason. Never convert absence from search results into `not_applicable`.

## Apply query budgets

Count every tool call, including failed attempts and pagination. `search_graph` counts include both initial and page calls. A pagination call must use a narrowed query; never fetch more than two additional pages for the same narrowed query.

| Profile | `architecture` | `search_graph` | `trace` | `search_code` | `snippet` |
|---|---:|---:|---:|---:|---:|
| `seed-v1` | 0–1 | at most 5 total: at most 3 initial calls plus 2 page calls; limit 20 | at most 4; depth at most 2 | at most 3; limit 10 | at most 4 |
| `expanded-v1` | at most 1 | at most 9 total: at most 5 initial calls plus 4 page calls; limit 20 | at most 8; depth at most 3 | at most 6; limit 20 | at most 8 |

Begin every report with `seed-v1`. Escalate at most once per report to `expanded-v1`, and record one non-empty `expansion_reason` naming the unresolved material question. Do not exceed `expanded-v1`. If another query would be needed after that budget is exhausted, record the unresolved question and mark the affected check, repository, and overall coverage `degraded`.

The budgets are per repository. A cross-service `trace_path` call counts against the originating repository's `trace` total. Baseline indexing is mandatory provenance rather than a discovery-query allowance; a cross-repository pass is limited to one refreshed pass per participating source project.

## Confirm material conclusions

Classify evidence consistently:

- `confirmed`: current source, tests, schemas, or configuration directly support the statement;
- `inferred`: multiple signals support the statement, but an execution path, runtime setting, generated artifact, or external system remains unverified;
- `unknown`: evidence is missing, contradictory, inaccessible, or outside the supplied repositories.

Confirm at least these conclusions in source:

- the implementation entry point and changed symbols;
- each public or cross-service contract;
- the most important inbound and outbound paths;
- current tests and their observable assertions;
- migration, compatibility, authorization, and failure-handling behavior when relevant.

Never turn absence from search results into proof that code or risk does not exist.

## Analyze multiple repositories

1. Index every participating repository's verified baseline analysis workspace with an explicit baseline-specific name, `persistence=false`, and `fast`, `moderate`, or `full`; capture its returned project identifier.
2. Stop and report degraded coverage if a required repository cannot be refreshed. Do not run cross-repository matching against a knowingly stale participant and call the result complete.
3. After all required refreshes succeed, call `index_repository` with mode `cross-repo-intelligence`, an affected analysis-workspace path/name, and `target_projects` containing only the other refreshed baseline identifiers. Follow the tool response if matching must be repeated from additional source projects.
4. Call `trace_path` with the explicit baseline project and mode `cross_service` from relevant routes, clients, publishers, consumers, or handlers.
5. Confirm protocol details in source on both sides: route and method, payload/schema, authentication, retry/idempotency, versioning, event/channel name, ordering, and rollout assumptions.
6. Record the safe implementation and deployment order. Mark cyclic or lockstep changes as elevated risk.

For a multi-repository task, `cross_repository.status` must be `complete` or `degraded`, never `not_applicable`. For a single-repository task without a cross-service signal, use `not_applicable` with a reason. A signal to an unavailable or unregistered repository is a material unknown and therefore `degraded`.

## Emit the evidence contract

Pass a JSON object with schema `dev-flow-impact-analysis/v1` as the impact artifact's `--metadata-json` value:

```json
{
  "schema": "dev-flow-impact-analysis/v1",
  "strategy": "funnel",
  "coverage": "complete",
  "budget_profile": "seed-v1",
  "repositories": [
    {
      "repository_id": "api",
      "index_id": "api-baseline-abc123",
      "index_mode": "fast",
      "checks": {
        "orientation": {"status": "not_applicable", "reason": "Exact source path and boundary were supplied"},
        "candidates": {"status": "complete"},
        "paths": {"status": "complete"},
        "contracts": {"status": "complete"},
        "tests": {"status": "complete"},
        "source_confirmation": {"status": "complete"}
      },
      "queries": {
        "architecture": 0,
        "search_graph": 2,
        "trace": 2,
        "search_code": 1,
        "snippet": 1
      },
      "unresolved_truncations": [],
      "material_unknowns": []
    }
  ],
  "cross_repository": {
    "status": "not_applicable",
    "reason": "Single-repository change with no cross-service signal"
  }
}
```

When `budget_profile` is `expanded-v1`, add a top-level non-empty `expansion_reason`. Use each task repository ID exactly once; the repository set must exactly equal the controller's registered repository set. `index_id` is a non-empty string for complete coverage and `null` for an unavailable index. Query counts are non-negative integers using the canonical keys shown above.

Top-level `coverage` may be `complete` only when:

- every repository has a non-empty `index_id`;
- every check is `complete` or reasoned `not_applicable`, with no `degraded` check;
- every `unresolved_truncations` and `material_unknowns` array is empty;
- all declared counts fit the selected budget;
- `cross_repository` satisfies the single/multi-repository rule and is not `degraded`.

Otherwise set top-level coverage to `degraded`, identify the affected check, and provide reasons or array entries. A degraded report remains recordable evidence, but it is not equivalent to complete coverage and requires explicit acceptance at the route gate.

The controller can validate the metadata shape, exact repository set, status consistency, and declared counts. It cannot prove the raw codebase-memory calls or their results without signed tool receipts. Treat query counts as an auditable declaration, not controller-verified execution evidence; retain source citations and index provenance in the report.

## Recommend a route

Recommend OpenSpec when any of these materially apply:

- multiple repositories or teams must coordinate;
- a public API, event, persisted schema, migration, compatibility promise, authentication, authorization, infrastructure, or rollout contract changes;
- architecture or product behavior requires explicit tradeoffs;
- requirements or acceptance criteria remain materially ambiguous;
- sequencing, rollback, or backwards compatibility needs a durable plan.

Recommend the direct route only when the change is bounded, reversible, well understood, and testable with a compact contract. State the evidence and caveats; the user makes the final route choice.

## Handle failures

- Retry only a clearly transient tool failure once.
- If indexing succeeds but a later graph query fails, preserve successful evidence and list the missing query.
- If codebase-memory is unavailable, use read-only source search and file inspection, set the affected checks and coverage to `degraded`, and enumerate which architecture, path, or cross-repository conclusions remain unknown.
- If repositories or baselines are ambiguous, report the ambiguity rather than silently analyzing a convenient directory.
- If source changed after indexing, refresh the affected index before finalizing conclusions.
- If the expanded budget is exhausted, stop querying, preserve the partial evidence, record unresolved truncations or material unknowns, and mark coverage `degraded`.
