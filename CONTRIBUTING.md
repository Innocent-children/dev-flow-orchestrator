# Contributing

[简体中文](CONTRIBUTING_CN.md)

Contributions preserve the 0.2.0 product contract: one task over an exact
canonical set of one to eight user-prepared local Git worktrees, one Codex
executor, one projected action, and one controller-owned append-only ledger.

## Product and authority boundaries

- Start with the user journey and supported product matrix. Workflow depth,
  repository topology, workspace strategy, and execution topology are
  independent dimensions.
- Keep current policy in one authoritative source and derive catalog,
  validation, tests, Skills, and documentation from it.
- Keep task state outside target repositories. The controller is the sole
  state-transition writer; Hook, CLI, Skills, and optional drivers submit to
  that boundary.
- Treat `TaskState.repositories` as immutable membership authority. Admission,
  snapshotting, mutation, replay, freshness, recovery, and finalization must
  cover the complete canonical set atomically; never default to one member,
  drop an unavailable member, or reconstruct caller order.
- Keep repository inspection bounded and read-only. Do not add implicit
  stash, reset, clean, checkout, commit, rebase, merge, push, force-push, or
  deletion behavior.
- Do not couple repository topology to workflow depth, managed branch/worktree
  effects, Git publication, parallel agents, or external CI/PR/release effects.
  The current core performs none of those and does not reuse partial assurance
  from unchanged members.
- Preserve action-binding, contract, input-lineage, resource, source-
  predecessor, snapshot, and revision CAS checks across every mutation path.
- Treat codebase-memory as discovery evidence. For each `repository_id`, use
  distinct baseline and current-workspace project IDs, never share graph IDs
  across members or generations, select by workflow phase, and confirm material
  conclusions in the named repository source.
- Ask OpenSpec for current JSON status and instructions. Repository-backed
  planning is source-producing and binds concrete governing/reported
  resources; no fixed phase sequence belongs in runtime code.
- Keep driver execution outside the engine. Optional-driver fallbacks record
  degraded or unavailable assurance and retain the same terminal conditions.
- Runtime code uses only the Python standard library.

## Module ownership

- `product.py`: 0.2.0 identity vocabulary, official workflow catalog, and the
  authoritative repository-topology capability.
- `model.py`: immutable task values and canonical repository membership,
  strict JSON, errors, and receipts.
- `snapshot.py`: aggregate repository-set snapshots and nested member
  workspace snapshots, validation, lookup, and digests.
- `workflow.py`: `dev-flow-workflow/0.2.0` contracts, stage-scoped cancellation, graph
  validation, and selected-definition identity.
- `delivery.py`: contracts, decisions, seals, bindings, resources, freshness,
  coverage, and dossiers.
- `engine.py`: replay, mutation plans, assurance routing, records, projections,
  and task views.
- `store.py`: path safety, locks, revision CAS, and atomic persistence.
- `git_client.py`: bounded content-sensitive read-only snapshots.
- `controller.py`: application coordination and all state mutations.
- `cli.py` and `hook.py`: wire interfaces; neither owns workflow policy.

Keep these dependencies explicit. Avoid global execution order, string-based
late binding, overlapping service layers, or filesystem/process access in the
pure domain modules.

## Current workflow and identity changes

Official workflows are `lite`, `feature`, `bugfix`, `investigation`,
`refactor`, and `full`. `dev-flow-workflow/0.2.0` nodes declare typed artifacts, workspace
roles, inputs, finite assurance rework, exhausted dossier paths, and optional-
driver degraded/unavailable metadata. Every workflow declares a shared cancel
action with explicit `cancel.stages`; official definitions cover the normal
majority of non-terminal stages and exclude all `delivery.finalize` nodes.

`PRODUCT_IDENTITY` is the authority for the current task, record, artifact,
action-binding, repository-set snapshot, nested workspace snapshot,
workflow, agent, verification-coverage, Delivery-Dossier, data
namespace, and one-to-eight topology. Selected-workflow identity binds only the
selector, schema, and canonical document. Any change to these current
authorities must update the corresponding product contract and focused proof.

Repository topology is selected independently of the official workflow. Every
cardinality uses `dev-flow-agent/0.2.0`, an exact
`dev-flow-repository-set-snapshot/0.2.0`, required `repository_id` resources,
structured `criteria`/`repositories`/`integration` verification, aggregate
freshness/review, and Delivery Dossier 0.2.0.

## Validation

Run only the smallest test modules or individual cases that directly cover the
changed behavior. Full unittest discovery is prohibited, including release or
milestone requests. On this macOS host, leave native Windows and Linux checks
explicitly unverified.

Typical focused commands are:

```sh
python3 -I -S tests/test_workflow_validation.py -v
python3 -I -S tests/test_yaml_subset.py -v
python3 -I -S tests/test_package.py -v
python3 -I -S tests/test_install_script.py -v
python3 -I -S tests/test_multi_repository_assets.py -v
python3 -I -S tests/test_delivery_runtime.py -v
python3 -I -S tests/test_controller_contracts.py -v
python3 -I -S tests/test_store_integrity.py -v
python3 -I -S tests/test_stale_mutations.py -v
python3 -I -S tests/test_cli.py -v
python3 -I -S tests/test_hook.py -v
python3 -I -S tests/test_git_snapshot.py -v
python3 -I -S tests/test_multi_repository_core.py -v
python3 -I -S tests/test_multi_repository_controller.py -v
python3 -I -S tests/test_multi_repository_delivery.py -v
python3 -I -S tests/test_installed_journeys.py -v
python3 -I -S scripts/validate_package.py
python3 -m json.tool .codex-plugin/plugin.json
```

Choose only the applicable commands from the 0.2.0 focused CI matrix. Validate
the active OpenSpec change with its current CLI instructions.

Validate every bundled Skill after editing it:

```sh
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/analyze-change-impact
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/follow-dev-flow
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/review-dev-flow-change
python3 /Users/innocent-children/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

The bundled validators require a development interpreter with PyYAML; this is
not a plugin runtime dependency.

Release evidence distinguishes source-checkout checks from installed behavior.
An installed acceptance pass identifies the immutable installed snapshot and
covers the six official workflows, Hook/Skill pickup, structured/minimal
starts, binding-required apply, contract revision recovery, decisions and
waivers, optional-driver available/degraded paths, bounded assurance success
and exhaustion, one-member and larger exact-set admission through the same
protocol, any-member Hook pickup, member-loss recovery, structured
member/integration verification, and aggregate dossier inspection. Conditions
that require a real new Codex task remain marked
manual or unverified when the environment cannot observe them.

Before handoff:

- inspect the complete tracked and untracked diff;
- run whitespace/error checks for changed files;
- confirm English and Chinese product claims have the same scope and strength;
- perform one independent read-only review against the exact current aggregate
  repository-set snapshot;
- report every skipped or manual check precisely.
