# Full flow

Read this file only when `show.flow` is `full`.

## State order

```text
INTAKE
  -> PREFLIGHTED
  -> BASELINED
  -> INDEXED
  -> IMPACT_REVIEW
  -> ROUTE_APPROVED
  -> WORKSPACE_READY
  -> PLANNING
  -> IMPLEMENTING
  -> VERIFYING
  -> REVIEWING
  -> FINALIZING
  -> DONE
```

Every arrow needs its own Chinese confirmation from the common rules.
Automatic domain transitions are:

- confirmed all-repository preflight -> `PREFLIGHTED`;
- any successful `baseline` -> `BASELINED`;
- final required `record-index --role baseline` -> `INDEXED`;
- `set-route` -> `IMPACT_REVIEW`;
- `approve --gate route` -> `ROUTE_APPROVED`;
- all-repository `prepare-workspace --execute` -> `WORKSPACE_READY`;
- `review-snapshot` -> `REVIEWING`.

Use `transition` for the remaining forward edges and supported rework, not to
duplicate those domain commands.

## Load one gate bundle

| Current status | Read next |
|---|---|
| `INTAKE`, or preflight-origin `BLOCKED` | [gates/preflight.md](gates/preflight.md) |
| `PREFLIGHTED`, `BASELINED`, `INDEXED`, `IMPACT_REVIEW` | [gates/baseline-impact-route.md](gates/baseline-impact-route.md) |
| `ROUTE_APPROVED`, `WORKSPACE_READY`, `PLANNING` | [gates/workspace-plan.md](gates/workspace-plan.md) |
| `IMPLEMENTING`, `VERIFYING`, `REVIEWING`, `FINALIZING` | [gates/verification-review.md](gates/verification-review.md) |

After a backward transition, route again from the new status. Do not read all
four gate bundles at once.

## Artifact lifecycle

| Artifact kind | Recording state | Bound gate |
|---|---|---|
| `impact` | `INDEXED` or `IMPACT_REVIEW` | `route` |
| `workspace-plan` | controller-generated in `ROUTE_APPROVED`/`WORKSPACE_READY` | `workspace` |
| `direct-contract` | `PLANNING` | `plan` |
| `openspec-plan` | `PLANNING` | `plan` |
| `review-report` | `REVIEWING` after a snapshot | `review` |

Recorded paths are immutable audit evidence. The controller rehashes them at
approval and downstream gates. On `ARTIFACT_CHANGED`, record a replacement
only in its legal state and obtain a new approval; never edit state or relabel
old evidence.

## Backward paths

Return from `IMPLEMENTING`, `VERIFYING`, `REVIEWING`, or `FINALIZING` to
`PLANNING --note <reason>` when the approved plan must change. This creates a
new planning generation, clears plan/review approvals and snapshots, and
requires a replacement plan, approval, tests, snapshot, and review.

Return from `ROUTE_APPROVED` through `FINALIZING` to
`INDEXED --note <reason>` when new baseline evidence changes impact or route.
This creates a new impact/workspace generation, retires current workspaces and
workspace indexes into history, and clears downstream approvals. Physical
worktrees and external indexes remain for separately authorized cleanup. The
immutable requirement and repository set cannot change; ask to cancel/replace
the task if they do.

## Full-flow human gates

Require explicit decisions for baseline scope/fetch/materialization, degraded
impact evidence, direct versus OpenSpec route, workspace plan execution,
direct/OpenSpec plan approval, material impact/plan corrections, and
independent review acceptance. These do not authorize later state edges.
