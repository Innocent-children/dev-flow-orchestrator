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
workspace, then record the exact project:

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
<ctl> record-artifact --task <task-id> --expected-revision <revision> --kind impact --path <report>
```

It must cover every repository or explicitly name degraded coverage. A newer
index or corrected report stales prior routing. Present findings,
recommendation, unknowns, and limitations before route selection.

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
authorize workspace creation. Never silently downgrade OpenSpec after a tool
failure.

For impact reassessment, use the backward path described in
[../flow-full.md](../flow-full.md), record a new-generation impact report, and
repeat route, workspace, plan, tests, and review.
