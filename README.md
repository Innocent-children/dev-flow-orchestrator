# Dev Flow Orchestrator

[简体中文](README_CN.md) · [Installation](INSTALL.md) ·
[Roadmap](ROADMAP.md) · [Architecture](ARCHITECTURE.md) ·
[Contributing](CONTRIBUTING.md)

Dev Flow Orchestrator V6 is a local-first delivery controller for Codex. It
turns one software requirement into a resumable, evidence-backed task and
projects one authoritative next action at a time. Codex performs the work;
the controller preserves the delivery contract, workflow state, decisions,
typed artifacts, assurance evidence, and final Delivery Dossier.

## Current product

V6 provides complete personal delivery in one Git repository:

- a structured, versioned delivery contract with stable acceptance-criterion
  IDs, scope, constraints, risks, non-goals, and open questions;
- six official workflows: `lite`, `feature`, `bugfix`, `investigation`,
  `refactor`, and `full`;
- append-only contract revisions and attributable criterion or review-
  assurance waivers;
- typed artifacts with producer metadata, contract binding, repository
  snapshots, input lineage, digests, and derived freshness;
- bounded verification and review rework with explicit `DONE` and
  `INCOMPLETE` dossier outcomes;
- optional OpenSpec, codebase-memory, and independent-review driver paths
  with explicit degraded or unavailable results;
- resumability across Codex sessions through the same controller and task ID.

The supported execution boundary is one task, one repository, the repository's
current worktree, and one Codex executor. The controller does not create or
switch branches or worktrees, coordinate parallel agents, or span
repositories. A dirty worktree and detached `HEAD` are supported when the
supplied repository path is the exact root of an initialized non-bare Git
worktree.

## Requirements

- macOS;
- Python 3.9–3.14;
- Git and a target worktree with an existing `HEAD` commit;
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
Hook definition. See [INSTALL.md](INSTALL.md) for upgrades, V5 retention and
rollback inspection, installed verification, troubleshooting, and removal.

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

Every official workflow begins with bounded, read-only Git preflight, supports
explicit cancellation from each unfinished stage, and finalizes every
non-cancelled result through a Delivery Dossier. A valid absolute path to a
linear workflow-v1 JSON or YAML document is also accepted for a new V6 task;
the selected definition and adapter identity are pinned for that task.

## Start and resume

Ask Codex to start a task with an explicit repository, workflow, and delivery
contract:

```text
Use $follow-dev-flow to start a feature task in:
/absolute/path/to/repository

Create a structured delivery contract for:
<what must be delivered>
```

The contract schema is `dev-flow-delivery-contract/v1`. It contains exactly
`schema`, `revision`, `summary`, `acceptance_criteria`, `scope`, `constraints`,
`risks`, `non_goals`, and `open_questions`; initial contract revision is `1`.
For a fast `lite` task, omitting `--contract-json` creates a bounded minimal
contract from the non-empty requirement.

Keep the returned task ID. Resume with:

```text
Use $follow-dev-flow to resume task <task-id>.
```

The installed Hook reconnects Codex when the current directory is inside the
task repository. Its locator already contains the installed launcher, CLI,
and exact V6 data directory. The Skill obtains a fresh `dev-flow-agent-v2`
projection with `next`, performs its single action, and passes the exact
`projection.action.binding` back with `apply --binding-json`. Bindings pin the
task revision, contract, inputs, source predecessor, and starting workspace
snapshot; stale work is rejected with a fresh projection.

## Evidence, decisions, and completion

Workflow-v2 artifacts declare one workspace role:

- `context` records read-only analysis;
- `produces-source` consumes a pinned source predecessor and records the
  successor worktree snapshot;
- `verifies-source` must observe the newest source authority exactly.

Inputs use `governing`, `source-predecessor`, or `causal` lineage. Governing
repository resources participate in freshness; reported resources preserve
provenance only. OpenSpec proposal, design, and spec files are governing.
`tasks.md` is recorded once as raw reported progress and once with the
`openspec-tasks-v1` semantic normalizer, which ignores only checkbox state.

Verification reports every acceptance criterion as `proven` or `unverified`.
Only a current explicit `criterion-waiver` decision can derive `waived`.
Review approval requires independent assurance. When independent review is
unavailable, a self-review can record findings but cannot claim approval; an
exact current `assurance-waiver` for the review node is required for the
unavailable result to follow the successful route. Otherwise bounded rework
ends with an `INCOMPLETE` dossier.

A later contract revision records the complete replacement contract, reason,
and actor label. The same record captures the current worktree as the new
contract's `revision-source` and returns the workflow to its declared impact
or implementation entry. Earlier artifacts remain immutable historical
evidence and cannot satisfy the revised scope.

`show <task-id>` exposes the complete read-only ledger and dossier. The
terminal dossier contains the effective contract, acceptance coverage,
current verification, review assurance, documentation evidence, decisions,
artifact provenance and freshness, repository snapshots, remaining risks,
outcome, and handoff recommendation.

## State, safety, and compatibility

- The controller is the only task-state writer. State uses locks, revision
  compare-and-swap, deterministic replay, and atomic replacement.
- Task state lives outside target repositories. The installed V6 Hook uses
  `<PLUGIN_DATA>/v6`; it protects the plugin data root from common direct
  shell and edit operations.
- Repository snapshots are bounded, content-sensitive, and read-only. The
  controller never automatically stashes, resets, cleans, commits, checks
  out, rebases, merges, pushes, force-pushes, or deletes user work.
- The Hook is a fail-open operational guardrail. Workflow validation and
  state-transition authority remain in the controller.
- V5 task data remains unchanged in `<PLUGIN_DATA>/v5`. V6 neither loads nor
  migrates it. Inspecting or resuming a V5 task requires the retained V5
  package snapshot and its V5 controller locator.

## Further documentation

- [INSTALL.md](INSTALL.md): installation, V5-to-V6 upgrade and rollback
  inspection, installed acceptance, and troubleshooting.
- [ARCHITECTURE.md](ARCHITECTURE.md): contracts, workflow-v2, bindings,
  lineage, replay, projections, and module ownership.
- [ROADMAP.md](ROADMAP.md): delivered Stage 1 capability and later product
  horizons.
- [CONTRIBUTING.md](CONTRIBUTING.md): focused validation and contribution
  rules.
- [LICENSE](LICENSE): license terms.
