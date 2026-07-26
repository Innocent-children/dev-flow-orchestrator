# Baseline, impact, and route gates

Read this bundle for a full task in `PREFLIGHTED`, `BASELINED`, `INDEXED`, or
`IMPACT_REVIEW`. Also read [../index-routing.md](../index-routing.md) before
indexing or querying.

## Baseline gate

Present repository, remote URL/name, base branch/candidate SHA, preflight
`HEAD`, exact worktree evidence, dirt, and proposed fetch/materialization.
Obtain explicit approval and record:

```text
<ctl> approve --task <task-id> --expected-revision <revision> --gate baseline-fetch --note <note> [--allow-fetch] [--allow-dirty]
<ctl> baseline --task <task-id> --expected-revision <revision> [--fetch] [--materialize]
```

Every baseline call, including a bare or materialize-only call, requires the
current structured approval. `--fetch` additionally requires `--allow-fetch`;
accepted ordinary dirt requires `--allow-dirty`. A later preflight invalidates
the approval. Before pinning/fetching, the controller rechecks remote URL,
candidate ref, `HEAD`, and fingerprint.

Authorized fetch uses only the approved URL/base and explicit refspec while
disabling hooks, custom transports/upload-pack, credential and askpass helpers,
pruning, and automatic maintenance. When authentication requires an external
helper, ask the user to fetch under their policy, then preflight and approve a
no-fetch baseline.

The successful command enters `BASELINED`. Use each returned immutable
`base_sha` and detached `analysis_workspace.path`; drift requires a renewed
gate or supported recovery.

## Baseline index and impact

For every repository, invoke `$analyze-change-impact` over the pinned analysis
workspace. Begin with the narrow `seed-v1` funnel, expand only for a recorded
material question, and use `expanded-v1` at most once. Cross-repository matching
is required for a multi-repository task or a discovered cross-service signal,
not as a default single-repository query. Then record the exact project:

```text
<ctl> record-index --task <task-id> --expected-revision <revision> --role baseline --repo <id> --commit <base-sha> --index-id <project-id> --metadata-json <json>
```

Use `persistence:false` and the controller-recommended name. The final required
`record-index --role baseline` enters `INDEXED`; earlier records do not. Never
index the source/feature worktree as the pinned baseline, mix repository
freshness, or omit the explicit project ID from later queries.

If safe indexing still fails, produce a source-backed draft and present the
limitation. Only after explicit acceptance, record `approve --gate
impact-degraded`, then a baseline index attempt without `--index-id` whose
metadata names `status:"failed"`, non-empty error, requested mode,
`fallback_coverage`, and the exact current degraded approval ID. This records
failure provenance, not a successful index. Workspace indexes have no degraded
path.

Save the complete report under `<evidence-root>` and record:

```text
<ctl> record-artifact --task <task-id> --expected-revision <revision> --kind impact --path <report> --metadata-json <dev-flow-impact-analysis/v1-json>
```

The metadata must use `schema:"dev-flow-impact-analysis/v1"`,
`strategy:"funnel"`, and cover every task repository exactly once. For each
repository it records the exact baseline index ID, the six completeness checks,
declared query counts, unresolved truncations, and material unknowns. It also
records cross-repository status and the selected budget profile; an expanded
profile requires a non-empty expansion reason. Follow the normative schema and
budgets in
[the evidence workflow](../../../analyze-change-impact/references/evidence-workflow.md).

`coverage:"complete"` requires a usable index for every repository, no degraded
check, no unresolved truncation or material unknown, budget-conforming declared
counts, and a non-degraded cross-repository result. If the expanded budget is
exhausted while a material question remains, record `coverage:"degraded"`; do
not buy completeness with unbounded queries.

The controller validates the declaration's structure, repository coverage,
status consistency, and counts. Without signed tool receipts it cannot verify
the raw MCP call history, so the report must retain source citations and index
provenance. A newer index or corrected report stales prior routing. Present
findings, recommendation, unknowns, budget use, and limitations before route
selection.

`impact-degraded` remains the explicit gate for a failed baseline index. Other
degraded funnel coverage is recordable, but route confirmation must name and
accept the remaining limitations while binding the exact degraded artifact
hash; it is never equivalent to complete coverage.

## Route gate

Offer exactly:

- `direct`: compact approved contract for bounded, reversible,
  well-understood work;
- `openspec`: generated OpenSpec workflow for cross-repository,
  public-contract, migration, security, infrastructure,
  architecture-sensitive, or materially ambiguous work.

After the explicit choice:

```text
<ctl> set-route --task <task-id> --expected-revision <revision> --route <direct|openspec> --reason <reason>
<ctl> approve --task <task-id> --expected-revision <revision> --gate route --note <note> --artifact-sha256 <impact-sha256>
```

`set-route` enters `IMPACT_REVIEW`; route approval enters `ROUTE_APPROVED`.
Both edges need their own confirmation. `approve --gate route` does not
authorize workspace creation. For a degraded impact artifact, include the
accepted unknowns and consequences in the approval note. Never silently
downgrade OpenSpec after a tool failure or exhausted query budget.

For impact reassessment, use the backward path described in
[../flow-full.md](../flow-full.md), record a new-generation impact report, and
repeat route, workspace, plan, tests, and review.
