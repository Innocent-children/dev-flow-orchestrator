---
name: analyze-change-impact
description: Analyze a requested code change across one or more repositories with codebase-memory evidence and source confirmation. Use before implementation or route selection to identify affected projects, files, symbols, call paths, public contracts, tests, risks, unknowns, and whether the work is better suited to a direct contract or OpenSpec.
---

# Analyze Change Impact

Produce a read-only, evidence-backed impact report. Treat the knowledge graph as a discovery aid and confirm every material conclusion in current source code.

## Prepare the analysis

1. Capture the requirement, acceptance signals, named repositories, pinned baseline commits and baseline analysis-workspace paths when available, and explicit constraints.
2. Separate requirement interpretation from assumptions and non-goals. Ask only when an unresolved choice would materially change the analysis.
3. Read [references/evidence-workflow.md](references/evidence-workflow.md) before querying codebase-memory.
4. Use [assets/impact-report-template.md](assets/impact-report-template.md) as the report structure.

## Build evidence

1. Call `index_repository` once for every repository, using its pinned baseline analysis workspace as `repo_path` when supplied. Verify that workspace's `HEAD` equals the recorded baseline before indexing. Pass the controller-recommended baseline-specific `name` and `persistence=false`; never let a same-named feature worktree overwrite this project. Use `fast` by default; select `moderate` or `full` only when the investigation needs the additional semantic or inventory coverage described in the reference. Record the exact project identifier returned by each call with role `baseline`.
2. Start the `seed-v1` funnel with named paths, exact symbols, and narrow `search_graph` calls. Read the candidate source immediately. Call `get_architecture` only when code location is unknown or architecture/boundary risk is material.
3. Expand only when a concrete unanswered question requires callers, dependencies, data flow, literals, configuration, exact snippets, or additional pages. Narrow truncated queries before paginating. Use the single `expanded-v1` allowance only with a recorded reason; if its budget cannot resolve a material question, mark coverage `degraded`.
4. Open relevant source and test files directly from the indexed baseline workspace. Cite repository-relative paths and symbols for confirmed findings; label graph-only observations as unconfirmed.
5. Perform cross-repository matching only when the task names multiple repositories or source/graph evidence signals a cross-service boundary. Refresh every participating baseline index first, restrict `target_projects` to those exact baseline IDs, and confirm both ends in source.
6. Before declaring completion, check orientation, candidates, paths, contracts, tests, and source confirmation for every registered repository. Emit `dev-flow-impact-analysis/v1` metadata using the schema and budgets in the evidence reference. Unresolved truncation, a material unknown, an unavailable required index, or an exhausted expansion makes coverage `degraded`.

## Deliver the report

Group findings by project and include:

- requirement interpretation, assumptions, and non-goals;
- candidate files and symbols, with the reason each is affected;
- inbound, outbound, data-flow, and cross-service call paths;
- public contracts, schemas, events, migrations, configuration, and compatibility concerns;
- tests to update or add, including boundary and failure cases;
- funnel budget use, completeness checks, unresolved truncations, material unknowns, conflicting evidence, and analysis limitations;
- a direct-versus-OpenSpec routing recommendation with reasons.

Distinguish `confirmed`, `inferred`, and `unknown` evidence. Recommend a route; do not choose it on the user's behalf. Do not edit application code, Git state, or OpenSpec artifacts.

If codebase-memory is unavailable or indexing fails, continue with source-native search only when useful, mark the affected project and overall coverage as `degraded`, list the missing graph checks, and never present the fallback as equivalent coverage.
