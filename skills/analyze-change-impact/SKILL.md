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

1. Call `index_repository` once for every repository, using its pinned baseline analysis workspace as `repo_path` when supplied. Verify that workspace's `HEAD` equals the recorded baseline before indexing. Use `fast` by default; select `moderate` or `full` only when the investigation needs the additional semantic or inventory coverage described in the reference. Record the exact project identifier returned by each call.
2. For every indexed project, call `get_architecture`, narrow symbol candidates with `search_graph`, trace relevant relationships with `trace_path`, search literals and configuration with `search_code`, and inspect exact symbols with `get_code_snippet`. Detect truncated results and refine or paginate instead of assuming the first page is complete.
3. Open the relevant source and test files directly from the indexed baseline workspace. Cite repository-relative paths and symbols for confirmed findings; label graph-only observations as unconfirmed.
4. For multi-repository work, refresh every participating index first. Then call `index_repository` in `cross-repo-intelligence` mode with the affected project identifiers and trace the discovered cross-service paths. Do not infer cross-repository safety from independently stale indexes.

## Deliver the report

Group findings by project and include:

- requirement interpretation, assumptions, and non-goals;
- candidate files and symbols, with the reason each is affected;
- inbound, outbound, data-flow, and cross-service call paths;
- public contracts, schemas, events, migrations, configuration, and compatibility concerns;
- tests to update or add, including boundary and failure cases;
- risks, unknowns, conflicting evidence, and analysis limitations;
- a direct-versus-OpenSpec routing recommendation with reasons.

Distinguish `confirmed`, `inferred`, and `unknown` evidence. Recommend a route; do not choose it on the user's behalf. Do not edit application code, Git state, or OpenSpec artifacts.

If codebase-memory is unavailable or indexing fails, continue with source-native search only when useful, mark the affected project as degraded, list the missing graph checks, and never present the fallback as equivalent coverage.
