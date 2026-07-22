# Evidence workflow

## Choose an index mode

Use one mode per repository and record the choice in the report.

| Mode | Choose it when | Tradeoff |
|---|---|---|
| `fast` | Structural discovery, definitions, routes, callers, and ordinary impact analysis are sufficient | Omits similarity and semantic edges |
| `moderate` | Vocabulary differs from the requirement or semantic discovery is likely to reveal relevant code | Adds similarity and semantic edges over filtered files |
| `full` | The repository needs the broadest supported inventory and semantic coverage, and the extra indexing cost is justified | Highest cost; do not select reflexively |

Do not reuse an index merely because a project with the same name exists. When the orchestrated workflow supplies `analysis_workspace.path`, confirm its `HEAD` equals the pinned `base_sha` and index that path instead of the user's possibly dirty or feature-branch worktree. Pass the controller-recommended baseline-specific `name` and `persistence=false`. Otherwise index the supplied repository path and record its current commit and dirt limitations. Retain the exact project identifier returned by the tool; the requested name is not proof of the returned ID.

This skill builds the `baseline` side of Dev Flow's dual-index structure. It does not create or refresh the implementation `workspace` index. Codebase-memory does not select an index automatically: every subsequent query must pass the exact baseline project identifier explicitly. A before/after comparison requires two separately labelled calls, never an ambiguous or mixed project.

## Query each repository

Apply this sequence, narrowing as evidence improves:

1. Call `get_architecture` with the exact baseline project ID plus `overview`, `entry_points`, `boundaries`, `routes`, `hotspots`, and `clusters`. Add `file_tree` only when directory placement is itself uncertain.
2. Call `search_graph` with the same explicit project ID, requirement concepts, and domain terms. Prefer natural-language `query` for discovery and `name_pattern` or `qn_pattern` for known identifiers. Use `include_connected` when adjacent nodes help explain impact. If `has_more` is true, narrow first or paginate with `offset` until the relevant result set is covered.
3. Call `trace_path` from exact symbols:
   - use `calls` with `inbound` to find dependants and `outbound` to find dependencies;
   - use `data_flow` for validation, transformation, persistence, or sensitive-value propagation;
   - include tests when mapping regression coverage;
   - use `risk_labels` as prioritization evidence, not as a final severity decision.
4. Call `search_code` for literals, configuration keys, serialized fields, route strings, error messages, and test names that graph symbol search may miss. Compare `total_results` with `limit`; narrow or raise the limit when truncated.
5. Call `get_code_snippet` only after `search_graph` yields the exact `qualified_name`. Include neighbors when the enclosing branch or local collaborator affects the conclusion.
6. Read current source files directly from the indexed path and inspect the surrounding implementation, declarations, tests, and configuration. Prefer source over graph data whenever they disagree.

Use native repository search to inspect file types or generated/configuration content that the index does not model well. Record such evidence alongside graph results rather than hiding the fallback.

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
- If codebase-memory is unavailable, use read-only source search and file inspection, mark coverage `degraded`, and enumerate which architecture, path, or cross-repository conclusions remain unknown.
- If repositories or baselines are ambiguous, report the ambiguity rather than silently analyzing a convenient directory.
- If source changed after indexing, refresh the affected index before finalizing conclusions.
