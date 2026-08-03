# Dev Flow Orchestrator

[简体中文](README_CN.md) · [Installation](INSTALL.md) ·
[Roadmap](ROADMAP.md) · [Architecture](ARCHITECTURE.md) ·
[Contributing](CONTRIBUTING.md)

Dev Flow Orchestrator 0.2.0 is a local-first delivery controller for Codex. It
turns one software requirement into a resumable, evidence-backed task and
projects one authoritative next action at a time. Codex performs the work;
the controller preserves the delivery contract, workflow state, decisions,
typed artifacts, assurance evidence, and final Delivery Dossier.

## Current product

Dev Flow 0.2.0 provides complete personal delivery over one exact canonical set of one to
eight local Git worktrees:

- a structured, versioned delivery contract with stable acceptance-criterion
  IDs, scope, constraints, risks, non-goals, and open questions;
- six official workflows: `lite`, `feature`, `bugfix`, `investigation`,
  `refactor`, and `full`;
- append-only contract revisions and attributable criterion or review-
  assurance waivers;
- typed artifacts with producer metadata, contract binding, per-repository
  snapshots, aggregate repository-set bindings, input lineage, digests, and
  derived freshness;
- bounded verification and review rework with explicit `DONE` and
  `INCOMPLETE` dossier outcomes;
- optional OpenSpec, codebase-memory, and independent-review driver paths
  with explicit degraded or unavailable results;
- resumability across Codex sessions from any member repository through the
  same controller and task ID.

The supported execution boundary is one task, one immutable repository set,
one current action, and one Codex executor. Repository topology is independent
of workflow depth: every official workflow accepts either one member or an
exact set of up to eight members. All worktrees are prepared and owned by the
user. The controller does not create or switch branches/worktrees, coordinate
parallel agents, commit or publish Git changes, dispatch external CI, or open
pull requests. There is no partial assurance reuse after aggregate drift and
no external release effects; any CI, PR, or release follow-up is user-owned
outside Dev Flow. A dirty worktree and detached `HEAD` are supported when
every supplied path is the exact root of an initialized non-bare Git worktree.

## Requirements

- macOS;
- Python 3.9–3.14;
- Git and one to eight target worktrees with existing `HEAD` commits;
- Codex with plugin and Hook support.

Runtime code uses only the Python standard library. OpenSpec,
codebase-memory, and an independent reviewer are optional workflow
capabilities; their absence is recorded explicitly and never silently raises
the assurance level.

## Install

For a new personal marketplace:

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"

cd "$HOME/plugins/dev-flow-orchestrator"
python3 -I -S scripts/validate_package.py

mkdir -p "$HOME/.agents/plugins"
cp templates/personal-marketplace.example.json \
  "$HOME/.agents/plugins/marketplace.json"

codex plugin add dev-flow-orchestrator@personal
```

Run the `cp` command only when
`~/.agents/plugins/marketplace.json` does not exist. Otherwise merge
`templates/marketplace-entry.json` into its `plugins` array. Start a new Codex
task after installation, open `/hooks`, and review and trust the installed
Hook definition. See [INSTALL.md](INSTALL.md) for replacement installs,
installed verification, troubleshooting, and removal.

## Choose a workflow

Daily use goes through `$follow-dev-flow`.

| Workflow | Delivery path | Assurance budget |
|---|---|---|
| `lite` | preflight → implementation → verification → dossier | 2 verification attempts |
| `feature` | impact → repository-backed plan → implementation → documentation → verification → independent review → dossier | 2 verification and 2 review attempts |
| `bugfix` | diagnosis → repository-backed fix plan → implementation → documentation → regression verification → independent review → dossier | 2 verification and 2 review attempts |
| `investigation` | impact → investigation report → verification → dossier | 2 verification attempts; no fabricated implementation |
| `refactor` | structural impact → invariant-backed plan → implementation → documentation → verification → independent review → dossier | 2 verification and 2 review attempts |
| `full` | complete impact and planning → implementation → documentation → verification → independent review → dossier | 3 verification and 3 review attempts |

Every official workflow begins with bounded, read-only Git preflight over the
complete repository set and finalizes every non-cancelled result through one
aggregate Delivery Dossier 0.2.0. `dev-flow-workflow/0.2.0` definitions declare cancellation
availability through `cancel.stages`; official workflows enable it for the
normal majority of non-terminal stages and exclude every `delivery.finalize`
stage. A custom workflow must be a valid `dev-flow-workflow/0.2.0` JSON or YAML document
selected by absolute path. Its identity binds the selector, schema, and
canonical document. Repository count never selects or changes a workflow.

## Start and resume

Ask Codex to start a task with an explicit workflow, delivery contract, and
one or more user-prepared repository roots:

```text
Use $follow-dev-flow to start one feature task across these prepared worktrees:
/absolute/path/to/api-repository
/absolute/path/to/client-repository

Create a structured delivery contract for:
<what must be delivered>
```

The CLI repeats `--repo` once per member. One occurrence creates a one-member
repository set through the same admission and evidence path:

```text
<ctl> start --requirement <text> --workflow feature \
  --repo /absolute/path/to/api-repository \
  --repo /absolute/path/to/client-repository \
  --contract-json <json-object>
```

Caller order has no priority meaning. Before task creation the controller
canonicalizes the complete set and rejects missing, bare, duplicate,
Git-identity-sharing, overlapping, unsafe, or data-directory-overlapping roots.
Membership is immutable; use a new task when the repository set must change.

The contract schema is `dev-flow-delivery-contract/0.2.0`. It contains exactly
`schema`, `revision`, `summary`, `acceptance_criteria`, `scope`, `constraints`,
`risks`, `non_goals`, and `open_questions`; initial contract revision is `1`.
For a fast `lite` task, omitting `--contract-json` creates a bounded minimal
contract from the non-empty requirement and complete repository set.

Keep the returned task ID. Resume with:

```text
Use $follow-dev-flow to resume task <task-id>.
```

The installed Hook reconnects Codex when the current directory is inside any
member repository. It returns the same task once even when inspecting a nested
path; multiple active tasks remain an explicit ambiguity. Its locator already
contains the installed launcher, CLI, and exact 0.2.0 data directory. The Skill
obtains one `dev-flow-agent/0.2.0` projection with a `repository_set` summary,
performs its one current action, and passes the exact
`projection.action.binding` back with `apply --binding-json`. Bindings pin the
task revision, contract, inputs, source predecessor, and aggregate starting
snapshot; stale work is rejected with a fresh projection. A one-member set has
one entry in `repository_set.repositories` and otherwise uses this same shape.

## Evidence, decisions, and completion

`dev-flow-workflow/0.2.0` artifacts declare one workspace role:

- `context` records read-only analysis;
- `produces-source` consumes a pinned source predecessor and records the
  successor worktree snapshot;
- `verifies-source` must observe the newest source authority exactly.

Inputs use `governing`, `source-predecessor`, or `causal` lineage. Governing
repository resources participate in freshness; reported resources preserve
provenance only. Every repository resource includes an explicit
`repository_id`, so equal relative paths in different members remain distinct.
OpenSpec proposal, design, and spec files are governing.
`tasks.md` is recorded once as raw reported progress and once with the
`openspec-tasks/0.2.0` semantic normalizer, which ignores only checkbox state.

Verification uses the `dev-flow-verification-coverage/0.2.0` contract with an
exact current `schema` plus `criteria`, `repositories`, and `integration`
objects for every set size:
every member and the integration command must be present, the top-level command
equals the integration command, and top-level `passed` is their conjunction.
Verification reports every acceptance criterion as
`proven` or `unverified`. Only a current explicit `criterion-waiver` decision
can derive `waived`.
Review approval requires independent assurance. When independent review is
unavailable, a self-review can record findings but cannot claim approval; an
exact current `assurance-waiver` for the review node is required for the
unavailable result to follow the successful route. Otherwise bounded rework
ends with an `INCOMPLETE` dossier.

A later contract revision records the complete replacement contract, reason,
and actor label. The same record captures the complete current repository set
as the new contract's aggregate `revision-source` and returns the workflow to
its declared impact or implementation entry. It cannot add, remove, reorder,
or relocate members. Earlier artifacts remain immutable historical evidence
and cannot satisfy the revised scope.

`show <task-id>` exposes the complete read-only ledger and dossier. The
terminal `dev-flow-delivery-dossier/0.2.0` body contains the effective contract,
repository-set identity and canonical inventory, acceptance coverage, current
structured verification, review assurance, documentation evidence, decisions,
artifact provenance and freshness, per-member baseline/final summaries,
changed-member diagnostics, scoped resources, remaining risks, outcome,
handoff recommendation, and current or stale verification and review attempts.
If a member cannot currently be captured, `show` still returns the stored
ledger and Dossier. `current_snapshot` and `artifact_freshness` are then
unavailable, and `snapshot_error` identifies the blocked member.

## State and safety

- The controller is the only task-state writer. State uses locks, revision
  compare-and-swap, deterministic replay, and atomic replacement.
- Task state lives outside every target repository. The installed Dev Flow 0.2.0 Hook uses
  `<PLUGIN_DATA>/0.2.0`; it protects the plugin data root from common direct
  shell and edit operations.
- Repository snapshots are bounded, content-sensitive, read-only, and captured
  all-or-none for a repository set. If a canonical member is missing or moved,
  repository-backed progress stops without ledger mutation; restore that exact
  root and retry. The controller never substitutes another worktree. The
  controller never automatically stashes, resets, cleans, commits, checks
  out, rebases, merges, pushes, force-pushes, or deletes user work.
- The Hook is a fail-open operational guardrail. Workflow validation and
  state-transition authority remain in the controller.
- Every cardinality uses `dev-flow-repository-set-snapshot/0.2.0`,
  `dev-flow-agent/0.2.0`, repository-scoped resources, structured member and
  integration verification, and Delivery Dossier 0.2.0. Each aggregate snapshot
  nests one `dev-flow-workspace-snapshot/0.2.0` member value per canonical member.

## Further documentation

- [INSTALL.md](INSTALL.md): installation, replacement, installed acceptance,
  and troubleshooting.
- [ARCHITECTURE.md](ARCHITECTURE.md): contracts, `dev-flow-workflow/0.2.0`, bindings,
  lineage, replay, projections, and module ownership.
- [ROADMAP.md](ROADMAP.md): delivered Stage 1 capability and later product
  horizons.
- [CONTRIBUTING.md](CONTRIBUTING.md): focused validation and contribution
  rules.
- [LICENSE](LICENSE): license terms.
