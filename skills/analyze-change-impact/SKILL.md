---
name: analyze-change-impact
description: Analyze a requested code change across one or more repositories using codebase-memory discovery and direct source confirmation. Use before route approval to identify affected files, symbols, call paths, contracts, tests, risks, unknowns, and repository coordination without modifying code or Git state.
---

# Analyze Change Impact

Produce a read-only impact report.

1. Capture the requirement, acceptance signals, repository set, pinned
   baselines, constraints, assumptions, and non-goals.
2. Index each pinned baseline with `codebase-memory`. Keep each returned
   baseline project ID distinct from every current-workspace project ID.
3. Use `search_graph` for symbols, `trace_path` for callers and callees,
   `get_code_snippet` for exact definitions, and `search_code` for literals.
   Use `get_architecture` only when orientation or a boundary is unclear.
4. Treat graph results as discovery evidence. Confirm every material
   conclusion in the actual source and cite repository-relative paths and
   symbols.
5. Cover every registered repository. Mark coverage degraded when a required
   index, source confirmation, or bounded query cannot be completed.
6. Report affected components, call/data paths, public contracts, test impact,
   security boundaries, cross-repository order, risks, unknowns, and a reasoned
   direct-or-OpenSpec route recommendation.

Distinguish confirmed, inferred, and unknown evidence. Do not edit source,
OpenSpec artifacts, controller state, or Git state.
