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

Schema-v2 is default-explicit. Its exact full-flow automatic whitelist is:

- final required `record-index --role baseline`:
  `BASELINED -> INDEXED`;
- `transition`: `WORKSPACE_READY -> PLANNING`;
- `transition`: `IMPLEMENTING -> VERIFYING`;
- `review-snapshot`: `VERIFYING -> REVIEWING`.

No other full-flow edge is automatic. Confirmed all-repository preflight,
`baseline`, `set-route`, route approval, and
`prepare-workspace --execute` use their documented explicit action/gate
decisions. Every other `transition`, including all rework and `DONE`, uses
`--preview` followed by the confirmed `--confirm-intent`. Use `transition` for
the remaining forward edges and supported rework, not to duplicate domain
commands.

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
independent review acceptance. These do not authorize later explicit state
edges. When route approval advances to `ROUTE_APPROVED`, approval and movement
remain separate durable audit facts even though one explicit approved action
records both.
