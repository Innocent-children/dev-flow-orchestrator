---
name: follow-dev-flow
description: Start or resume a Dev Flow 0.4.0 delivery task for code, configuration, tests, generated files, documentation, or OpenSpec work in an exact set of one to eight user-prepared local Git worktrees. Use the exact Hook-injected controller locator, select one of six official workflows or a pinned dev-flow-workflow/0.4.0 custom definition, follow the dev-flow-agent/0.4.0 repository-set projection, and apply the one current action with its exact binding until a Delivery Dossier 0.4.0 terminal.
---

# Follow Dev Flow

## Follow the task-owned capsule and current obligation

For every source-producing action, compare the bound starting snapshot with the
current controller capture and submit `dev-flow-task-change-claims/0.4.0` for
every and only observed changed path. Include its repository ID, relative path,
classification, criterion IDs, and purpose. Never claim ambient drift silently.

At `assurance.dispatch`, execute only `current_obligation`. Preserve its plan,
fingerprint, task-change slice, evidence contract, prerequisites, and remaining
recorded attempts in the submitted result. A `not_required` dimension is a
controller decision, not an omitted agent result. Treat optional driver failure
as degraded or unavailable evidence; never fabricate source confirmation.
Evidence is slice-aware: current proof may be reused for a disjoint manifest
delta only when the controller projects that reuse, while an intersecting or
ambiguous delta requires fresh execution. Stop at the controller-derived
`DONE`, `INCOMPLETE`, or `CANCELLED` terminal.

Invoke this workflow as `$follow-dev-flow`. Treat the 0.4.0 controller as the
only task-state writer and source of workflow truth. The supported boundary is
one task, one immutable exact repository set, one current action, and one Codex
executor. The set contains one to eight user-prepared local Git worktrees;
workflow depth never determines repository count.

The 0.4.0 evidence model uses `governing`, `source-predecessor`, and `causal`
lineage between typed artifacts. Source-changing stages are
`produces-source`; verification and review stages are `verifies-source`.
OpenSpec, codebase-memory, and `independent-review` are optional drivers with
explicit fallback, degraded, and unavailable behavior.

## Use the injected controller

Preserve the complete Hook-injected locator as:

```text
<ctl> = <exact injected locator>
```

It already contains the installed Python launcher, CLI, and
`--data-dir <PLUGIN_DATA>/0.4.0`. Do not reconstruct, shorten, or append another
data directory. Never read or edit controller state files directly.

Require a 0.4.0 context: the Hook identifies Dev Flow 0.4.0 and `next` emits
`schema: dev-flow-agent/0.4.0` with `repository_set`. A one-member set uses this
same projection and aggregate binding.

The Hook may reconnect the same active task from any member repository. When
multiple active tasks cover the current path, select the intended task ID
explicitly; never guess from member order.

## Select a workflow

Use the user's explicit choice. Otherwise select the smallest official path
that fits the requested outcome:

- `lite`: fast implementation plus bounded verification and dossier;
- `feature`: impact, OpenSpec-capable plan, implementation, documentation,
  verification, independent review, dossier;
- `bugfix`: diagnosis, fix plan, implementation, documentation, regression
  verification, independent review, dossier;
- `investigation`: impact, investigation report, verification, dossier, with no
  fabricated implementation;
- `refactor`: structural impact, invariant-backed plan, implementation,
  documentation, verification, independent review, dossier;
- `full`: the complete personal-delivery path with three verification and
  review attempts.

An absolute path to a valid `dev-flow-workflow/0.4.0` JSON/YAML document is accepted for a
new 0.4.0 task. The controller pins its schema, selector, canonical source
document, and identity.

## Start with a contract

Prefer an explicit initial contract for normal delivery:

```json
{
  "schema": "dev-flow-delivery-contract/0.4.0",
  "revision": 1,
  "summary": "<accepted outcome>",
  "acceptance_criteria": [
    {"id": "C1", "statement": "<observable criterion>"}
  ],
  "scope": ["<included work>"],
  "constraints": [],
  "risks": [],
  "non_goals": [],
  "open_questions": []
}
```

Use exactly these fields, unique portable criterion IDs, and initial contract
revision `1`. Do not place caller-supplied repository IDs or a
`repository_set_id` in the contract; the controller derives both from admitted
membership. Serialize strict JSON and pass it as one argument:

```text
<ctl> start \
  --requirement <non-empty-text> \
  --workflow <lite|feature|bugfix|investigation|refactor|full|absolute-path> \
  --repo <absolute-worktree-root> \
  --contract-json <json-object>
```

Repeat `--repo` for a larger exact repository set:

```text
<ctl> start \
  --requirement <non-empty-text> \
  --workflow <workflow-selector> \
  --repo <absolute-api-worktree-root> \
  --repo <absolute-client-worktree-root> \
  --contract-json <json-object>
```

Supply one through eight exact roots. Caller order has no priority or
dependency meaning. Before writing state, the controller canonicalizes the
complete set and rejects missing, bare, duplicate, Git-identity-sharing,
ancestor/descendant, unsafe, or data-directory-overlapping roots. Every
worktree must already exist and remain user-owned. Membership cannot be added,
removed, replaced, relocated, or reordered after creation.

For a requirement-only minimal start, omit `--contract-json`:

```text
<ctl> start --requirement <text> --workflow lite --repo <absolute-worktree-root>
```

The controller derives contract revision `1` with criterion ID `requirement`.
The minimal contract covers the complete repository set. Save the returned
task ID. Task creation writes revision-zero state; complete-set preflight is
the first ledger mutation.

Resume or obtain the first action with:

```text
<ctl> next <task-id>
```

## Execute exactly one projected action

For every non-terminal projection:

1. Read `projection.contract`, the complete `repository_set`, member/aggregate
   snapshots, freshness, current node,
   `action.inputs`, `action.retry_budget`, `action.driver`, exact payload field
   types, and the complete `action.binding`.
2. Perform only that action. A `context` or `verifies-source` stage must not
   change any member. A `produces-source` stage may intentionally change one or
   more members and replace its one aggregate bound source predecessor; its
   successor still observes every member.
3. Build one strict JSON payload containing every declared field and no unknown
   field.
4. Apply with the exact unmodified binding from the projection:

   ```text
   <ctl> apply <task-id> \
     --action <action-id> \
     --payload-json <json-object> \
     --binding-json '<projection.action.binding JSON>'
   ```

   `task.preflight` also requires `--payload-json '{}'` and its projected
   binding. Never synthesize, trim, or reuse a binding.
5. Continue from the fresh projection returned by `apply`. Run `next` when a
   fresh projection is otherwise needed.

On `REVISION_CONFLICT`, read `error.details.projection`, run `next`, and
reassess the action. On `ACTION_BINDING_STALE`, `WORKSPACE_CHANGED`, or stale
input/resource evidence, obtain a fresh projection and repeat the affected
work only if the new action still requires it. Do not replay a stale intent.
One unavailable, moved, or unsafe member blocks repository-dependent progress
without a partial ledger append. Restore the exact persisted root and retry;
never substitute another worktree or silently omit the member.

## Official action payloads

Use the current projection as authority. The official 0.4.0 workflow actions use
these exact payload shapes:

| Action | Payload |
|---|---|
| `task.preflight` | `{}` |
| `impact.record` | `{"summary": string, "driver_result": object}` |
| `plan.record` | `{"summary": string, "resources": object, "driver_result": object}` |
| `implementation.record` | `{"summary": string}` |
| `documentation.record` | `{"summary": string}` |
| `investigation.record` / `investigation.rework.record` | `{"summary": string, "evidence": object}` |
| `verification.record` | `{"passed": boolean, "command": string, "coverage": object, "summary": string}` |
| `verification.rework.record` / `review.rework.record` | `{"summary": string}` |
| `review.record` | `{"outcome": string, "assurance": string, "findings": object, "summary": string, "driver_result": object}` |
| `delivery.finalize.success` / `delivery.finalize.verification-incomplete` / `delivery.finalize.review-incomplete` | `{"summary": string, "remaining_risks": object, "handoff": string}` |

Custom workflow actions use only their projected payload contract.

Use this common driver envelope inside `driver_result`:

```json
{
  "schema": "dev-flow-driver-result/0.4.0",
  "tool": "<declared tool>",
  "status": "available",
  "phase": "<current workflow phase>",
  "details": {},
  "limitations": []
}
```

Use `available` when the named driver produced evidence for the bound inputs,
`degraded` when the declared fallback or incomplete supporting coverage was
used, and `unavailable` when independent assurance could not be produced.
Never describe fallback evidence as the named tool's result.

## Run codebase-memory stages

Invoke `$analyze-change-impact`. Keep `baseline_project_id` and
`current_project_id` distinct, record their snapshot generations, and select
the graph explicitly by workflow `phase`. Do this separately for every
`repository_id`; never share a graph project ID across members or generations.
Record per-member evidence plus cross-repository
effects, and confirm every material graph conclusion in the corresponding
source root.

Place the normalized impact object in the action payload's top-level
`impact_manifest`; keep graph query/output provenance in `driver_result.details`.
The controller reads `impact_manifest` as the assurance-planning authority and
falls back to conservative `unknown` impact when it is absent. Set driver
status to `degraded` when a required index is unavailable/stale, a bounded
query cannot complete, or a material claim is unconfirmed. Direct source
inspection is the fallback and remains read-only.

## Run source-producing OpenSpec planning

Obtain the planning action binding before changing files. Query OpenSpec for
current machine-readable state:

```text
openspec status --change <change-id> --json
openspec instructions <current-artifact-or-apply> --change <change-id> --json
```

Select the current artifact or apply phase from the status response. Follow the
returned instructions and concrete artifact paths; do not encode a fixed phase
sequence. Record the change ID, parsed JSON status/instructions, returned paths,
and any limitations in `driver_result.details`.

Planning is `produces-source`. Its `resources` object has exactly `items`, and
every item has exactly `repository_id`, `path`, `role`, and `normalizer`:

```json
{
  "items": [
    {"repository_id": "<planning-repository-id>", "path": "openspec/changes/example/proposal.md", "role": "governing", "normalizer": "none"},
    {"repository_id": "<planning-repository-id>", "path": "openspec/changes/example/design.md", "role": "governing", "normalizer": "none"},
    {"repository_id": "<planning-repository-id>", "path": "openspec/changes/example/specs/capability/spec.md", "role": "governing", "normalizer": "none"},
    {"repository_id": "<planning-repository-id>", "path": "openspec/changes/example/tasks.md", "role": "governing", "normalizer": "openspec-tasks/0.4.0"},
    {"repository_id": "<planning-repository-id>", "path": "openspec/changes/example/tasks.md", "role": "reported", "normalizer": "none"}
  ]
}
```

Bind every concrete proposal, design, and spec path returned for the plan as
`governing` with `normalizer: none`. Bind `tasks.md` twice: governing with
`openspec-tasks/0.4.0` and reported with `none`. The semantic normalizer ignores
only checkbox state; task text, ordering, and test obligations remain
governing. Treat machine-generated status/instruction output as reported
driver evidence; if it is persisted as a repository file, bind it as
`reported`, never as governing plan content.

Resolve each path only below its declared member root. Unknown or omitted
repository IDs, absolute paths, parent traversal, and duplicate scoped
keys are invalid. Equal relative paths in different repositories remain
distinct because `repository_id` is part of the key.

When OpenSpec is unavailable, create the equivalent repository-backed plan
from source and the delivery contract, keep the same governing/reported
resource rules, and record `status: degraded` with the exact limitation.

## Record verification and bounded rework

Read `action.current_obligation` and run only the smallest checks required by
that obligation's `evidence_contract`, repository scope, task-change slice,
impact closure, and prerequisites. Submit exactly one `assurance_result`:

```json
{
  "assurance_result": {
    "obligation_id": "<action.current_obligation.obligation_id>",
    "passed": true,
    "evidence": [
      {"kind": "command", "reference": "<actual focused command>", "summary": "<actual result>"}
    ],
    "limitations": []
  },
  "summary": "<bounded assurance summary>"
}
```

The controller derives criterion coverage and obligation state; do not submit
an aggregate coverage verdict. A failed, unavailable, or incomplete attempt is
still persisted and consumes exactly one allowance. Never run an undeclared
retry. When a later manifest/impact plan preserves an obligation fingerprint,
the controller may reuse its passing evidence; disjoint aggregate drift alone
does not invalidate that slice-bound proof. Intersecting task changes,
governing-resource changes, impact-closure changes, or prerequisite changes do.

## Record independent review

Use a genuinely separate reviewer capability and `$review-dev-flow-change`
against the exact review action binding. Bind the canonical per-member base
and snapshot manifest plus the aggregate `workspace_snapshot_digest`. The
review artifact must also bind `artifact_digest` and `guidance_snapshot_digest` and
remain unchanged through completion. Review every member and cross-repository
acceptance behavior as one task-wide assurance result; never issue per-member
approval or reuse partial approval after aggregate drift.

Use `action.review_contract` verbatim and submit the current obligation through
the runtime schema:

```json
{
  "assurance_result": {
    "obligation_id": "<action.current_obligation.obligation_id>",
    "passed": true,
    "evidence": [{"kind": "review", "reference": "<review fingerprint>", "summary": "<result>"}],
    "limitations": [],
    "review": {
      "reviewer_available": true,
      "independent": true,
      "reviewer_digest": "<sha256>",
      "review_scope_digest": "<action.review_contract.review_scope_digest>",
      "guidance_digest": "<action.review_contract.guidance_digest>",
      "workspace_digest": "<action.review_contract.workspace_digest>",
      "findings": [],
      "claimed_outcome": "approved"
    }
  },
  "summary": "<review summary>"
}
```

`findings` is a list of complete `dev-flow-review-finding/0.4.0` objects.
Every introduced finding's `causal_manifest_entries` must contain its exact
current manifest location; affected findings additionally carry a bounded,
source-confirmed causal path.
Independent PASS uses `claimed_outcome: approved`; FAIL/CONDITIONAL uses
`changes-requested`; no reviewer uses `reviewer_available: false`,
`independent: false`, `passed: false`, and `claimed_outcome: unavailable`.
The controller derives the authoritative outcome and rejects contradictory
`passed` or claimed outcomes. Snapshot drift invalidates the action binding and
requires a fresh projection.

An unavailable independent review follows the successful route only when a
current explicit `assurance-waiver` targets the exact review obligation after
that same current obligation has recorded a controller-derived unavailable
execution. No repository, integration, documentation, or manual obligation can
be waived this way. Without it,
the unavailable result consumes the bounded review budget and eventually
finalizes `INCOMPLETE`.

## Revise scope and record decisions

Use these controller mutations only after preflight and only for an accepted
scope or authority decision. They append one record and return a fresh
projection.

Supply the complete next contract revision:

```text
<ctl> revise-contract <task-id> \
  --contract-json <complete-next-contract-json> \
  --ownership-claims-json <exact-reconciliation-claims-json> \
  --reason <non-empty-text> \
  --actor-label <non-empty-text>
```

The revision must advance by exactly one. The controller captures a
new-contract aggregate `revision-source`, reconciles the latest accepted source
snapshot to the stable revision snapshot, and reenters the workflow's declared
impact or implementation node. It cannot change immutable
repository membership; start a new task for a different set. Earlier-contract
artifacts and waivers remain historical. Reconciliation claims must exactly
cover every ambient path being adopted and map it to current replacement
criteria; omitted, extra, or incompatible claims reject the revision atomically.

Record a criterion or review-assurance waiver:

```text
<ctl> decide <task-id> --decision-json <decision-json>
```

The object has exactly `id`, `kind`, `subject`, `outcome`, `rationale`, and
`actor_label`. Use `criterion-waiver` with an exact criterion ID or
`assurance-waiver` with the exact current independent-review obligation ID or
fingerprint after an unavailable execution; `outcome` is `waived`.
Decision IDs are task-unique, and one `(kind, subject)` is accepted per
contract digest. Never invent an operator decision, actor label, or rationale.

## Finalize and inspect the dossier

Follow the projected finalization action. Supply only the change/investigation
summary, a structured `remaining_risks` object, and a concrete `handoff`
recommendation. The engine derives contract, coverage, verification, review,
decisions, artifacts, freshness, and repository snapshots.

Both `DONE` and `INCOMPLETE` terminal projections have `done: true`. Inspect
the complete record and Delivery Dossier before handoff:

```text
<ctl> show <task-id>
```

Report the exact dossier outcome, coverage, assurance or waiver, remaining
risks, freshness, and handoff. `dev-flow-delivery-dossier/0.4.0` always includes the
repository-set identity, canonical inventory, member baseline/final summaries,
changed-member diagnostics, scoped resources, every verification attempt, and
current aggregate evidence.

Do not describe an incomplete or waived result as independently approved.

## Close a confirmed repository mismatch

Treat a confirmed semantic repository mismatch as an operator-decision
boundary. Confirm from the effective contract and the declared members'
source that the immutable repository set cannot satisfy the accepted outcome.
Uncertainty is still impact or diagnosis work and does not authorize
cancellation.

When the mismatch is confirmed:

1. Stop the projected action. Do not change a member or apply the current
   workflow action. Obtain a fresh projection and check whether its exact
   `current_node` is listed in the selected workflow's `cancel.stages`.
2. Tell the user the exact task ID, the accepted requirement, the mismatching
   repository set, and that the task remains active. If the current user
   request does not already authorize cancellation of that exact task, request
   explicit user authorization and stop for the decision.
3. Without that authority, do not call `cancel`, claim that the task ended,
   start a replacement task, or substitute another repository. Membership is
   immutable and the active task remains the controller's source of truth.
4. After authorization, use the injected locator to cancel the exact task with
   a factual reason. Do not treat the user's choice as permission for any
   repository effect, including stash, reset, clean, checkout, or modifying
   member files.
5. Report the task as ended only when the returned projection has all three
   terminal facts: `done: true`, `status: CANCELLED`, and
   `current_node: cancelled`.

If cancellation is unavailable at the current node or fails because the exact
repository set cannot be captured, report that the task remains active and
name the required finalizer, member restoration, or operator action.
Do not substitute another repository or describe the failed attempt as
terminal.

## Cancel and preserve user authority

Cancel only after explicit user instruction and only when the current node is
listed in the selected workflow's `cancel.stages` declaration:

```text
<ctl> cancel <task-id> --reason <text>
```

The six official workflows expose cancellation at a strict majority of their
normal nonterminal stages. Delivery finalizers never expose cancellation; let
their projected finalization action complete. Cancellation captures the
complete current repository set before appending its one record. If any member
is unavailable, it leaves task state unchanged; restore the exact canonical
member root and retry if cancellation is still requested.

Do not cancel without explicit user authorization for that exact action.
The following are not controller actions or supported Dev Flow workflow
effects: stash, reset, clean, checkout, force-push, rebase, merge, commit, push,
delete, create/switch branches or worktrees, open pull requests, or dispatch
external CI. The Delivery Dossier handoff marks any such follow-up as
user-owned. If the user separately and explicitly requests one, Codex may
perform it only as an independent operation outside Dev Flow and only with
authorization for that exact operation. The controller performs no implicit
Git mutation, publication, or cleanup and never delegates repository work to
parallel agents.
