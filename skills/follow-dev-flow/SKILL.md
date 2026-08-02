---
name: follow-dev-flow
description: Start or resume a Dev Flow V6 delivery task for code, configuration, tests, generated files, documentation, or OpenSpec work in one Git repository. Use the exact Hook-injected controller locator, select one of six official workflows or a pinned custom definition, follow the dev-flow-agent-v2 projection, and apply each action with its exact binding until a Delivery Dossier terminal.
---

# Follow Dev Flow

Invoke this workflow as `$follow-dev-flow`. Treat the V6 controller as the
only task-state writer and source of workflow truth. The current
single-repository boundary is one task, one Git repository, its current
worktree, and one Codex executor.

The V6 evidence model uses `governing`, `source-predecessor`, and `causal`
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
`--data-dir <PLUGIN_DATA>/v6`. Do not reconstruct, shorten, or append another
data directory. Never read or edit controller state files directly.

Require a V6 context: the Hook identifies Dev Flow V6 and `next` emits
`schema: dev-flow-agent-v2`. A V5 locator or `dev-flow-agent-v1` projection
belongs to the retained V5 installation and must be operated with its retained
V5 Skill; do not point either controller at the other namespace.

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

An absolute path to a valid linear workflow-v1 JSON/YAML document is accepted
for a new V6 task. The controller pins its document and adapter identity.

## Start with a contract

Prefer an explicit initial contract for normal delivery:

```json
{
  "schema": "dev-flow-delivery-contract/v1",
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
revision `1`. Serialize strict JSON and pass it as one argument:

```text
<ctl> start \
  --requirement <non-empty-text> \
  --workflow <lite|feature|bugfix|investigation|refactor|full|absolute-path> \
  --repo <absolute-worktree-root> \
  --contract-json <json-object>
```

For a requirement-only minimal start, omit `--contract-json`:

```text
<ctl> start --requirement <text> --workflow lite --repo <absolute-worktree-root>
```

The controller derives contract revision `1` with criterion ID `requirement`.
Save the returned task ID. Task creation writes revision-zero state; preflight
is the first ledger mutation.

Resume or obtain the first action with:

```text
<ctl> next <task-id>
```

## Execute exactly one projected action

For every non-terminal projection:

1. Read `projection.contract`, repository snapshot, freshness, current node,
   `action.inputs`, `action.retry_budget`, `action.driver`, exact payload field
   types, and the complete `action.binding`.
2. Perform only that action. A `context` or `verifies-source` stage must not
   change the worktree. A `produces-source` stage may intentionally replace its
   bound source predecessor.
3. Build one strict JSON payload containing every declared field and no unknown
   field.
4. Apply with the exact unmodified binding from the projection:

   ```text
   <ctl> apply <task-id> \
     --action <action-id> \
     --payload-json <json-object> \
     --binding-json <projection.action.binding-json>
   ```

   `task.preflight` also requires `--payload-json '{}'` and its projected
   binding. Never synthesize, trim, or reuse a binding.
5. Continue from the fresh projection returned by `apply`. Run `next` when a
   fresh projection is otherwise needed.

On `REVISION_CONFLICT`, read `error.details.projection`, run `next`, and
reassess the action. On `ACTION_BINDING_STALE`, `WORKSPACE_CHANGED`, or stale
input/resource evidence, obtain a fresh projection and repeat the affected
work only if the new action still requires it. Do not replay a stale intent.

## Official action payloads

Use the current projection as authority. The official workflow-v2 actions use
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
  "schema": "dev-flow-driver-result/v1",
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
the graph explicitly by workflow `phase`. Confirm every material graph
conclusion in source.

Place the complete impact artifact in `driver_result.details`. Set driver
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
every item has exactly `path`, `role`, and `normalizer`:

```json
{
  "items": [
    {"path": "openspec/changes/example/proposal.md", "role": "governing", "normalizer": "none"},
    {"path": "openspec/changes/example/design.md", "role": "governing", "normalizer": "none"},
    {"path": "openspec/changes/example/specs/capability/spec.md", "role": "governing", "normalizer": "none"},
    {"path": "openspec/changes/example/tasks.md", "role": "governing", "normalizer": "openspec-tasks-v1"},
    {"path": "openspec/changes/example/tasks.md", "role": "reported", "normalizer": "none"}
  ]
}
```

Bind every concrete proposal, design, and spec path returned for the plan as
`governing` with `normalizer: none`. Bind `tasks.md` twice: governing with
`openspec-tasks-v1` and reported with `none`. The semantic normalizer ignores
only checkbox state; task text, ordering, and test obligations remain
governing. Treat machine-generated status/instruction output as reported
driver evidence; if it is persisted as a repository file, bind it as
`reported`, never as governing plan content.

When OpenSpec is unavailable, create the equivalent repository-backed plan
from source and the delivery contract, keep the same governing/reported
resource rules, and record `status: degraded` with the exact limitation.

## Record verification and bounded rework

Run the smallest checks that directly prove the current contract. Record the
actual command and result. `coverage` must contain every current acceptance ID
with `proven` or `unverified`; the controller derives `waived` only from a
current explicit decision. For a waived-but-unproven criterion, submit
`unverified`.

Set `passed: true` only after the recorded command succeeds and every
non-waived criterion is proven. Persist a real failure with `passed: false`;
the controller routes it to declared rework while the retry budget remains and
to incomplete finalization when exhausted. Never hide a failed attempt or run
an undeclared extra retry outside the projection.

## Record independent review

Use a genuinely separate reviewer capability and `$review-dev-flow-change`
against the exact review action binding. The review artifact must bind
`base_revision`, `workspace_snapshot_digest`, `artifact_digest`, and
`guidance_snapshot_digest` and remain unchanged through completion.

Map the review result to the workflow payload:

- independent `PASS` → `outcome: approved`, `assurance: independent`;
- independent `FAIL` → `outcome: changes-requested`, `assurance: independent`;
- independent degraded `CONDITIONAL` → `outcome: changes-requested`,
  `assurance: independent`;
- snapshot drift → discard the attempt, obtain a fresh action binding, and
  rerun the review if the refreshed projection still requests it;
- no independent reviewer → run a bounded self-review; use
  `outcome: changes-requested`, `assurance: self` when it finds required
  changes, otherwise `outcome: unavailable`, `assurance: self`.

Put `findings` in an object such as `{"items": [...]}` and put the complete
fingerprinted review result in `driver_result.details`. Record independent
driver status as `available`, `degraded`, or `unavailable` exactly as returned.
Never record `approved` with self assurance.

An unavailable independent review follows the successful route only when a
current explicit `assurance-waiver` targets the exact review node. Without it,
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
  --reason <non-empty-text> \
  --actor-label <non-empty-text>
```

The revision must advance by exactly one. The controller captures a
new-contract `revision-source` and reenters the workflow's declared impact or
implementation node. Earlier-contract artifacts and waivers remain historical.

Record a criterion or review-assurance waiver:

```text
<ctl> decide <task-id> --decision-json <decision-json>
```

The object has exactly `id`, `kind`, `subject`, `outcome`, `rationale`, and
`actor_label`. Use `criterion-waiver` with an exact criterion ID or
`assurance-waiver` with an exact review node ID; `outcome` is `waived`.
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
risks, freshness, and handoff. Do not describe an incomplete or waived result
as independently approved.

## Cancel and preserve user authority

Cancel only after explicit user instruction:

```text
<ctl> cancel <task-id> --reason <text>
```

Do not stash, reset, clean, checkout, force-push, rebase, merge, commit, push,
delete, or cancel without explicit user authorization for that exact action.
The controller performs no implicit Git mutation or cleanup.
