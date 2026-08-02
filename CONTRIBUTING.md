# Contributing

Contributions preserve the V6 product contract: one task, one Git repository,
the current worktree, one Codex executor, one projected action, and one
controller-owned append-only ledger.

## Product and authority boundaries

- Start with the user journey and supported product matrix. Workflow depth,
  repository topology, workspace strategy, and execution topology are
  independent dimensions.
- Keep current policy in one authoritative source and derive catalog,
  validation, tests, Skills, and documentation from it.
- Keep task state outside target repositories. The controller is the sole
  state-transition writer; Hook, CLI, Skills, and optional drivers submit to
  that boundary.
- Keep repository inspection bounded and read-only. Do not add implicit
  stash, reset, clean, checkout, commit, rebase, merge, push, force-push, or
  deletion behavior.
- Preserve action-binding, contract, input-lineage, resource, source-
  predecessor, snapshot, and revision CAS checks across every mutation path.
- Treat codebase-memory as discovery evidence. Use distinct baseline and
  current-workspace project IDs, select by workflow phase, and confirm material
  conclusions in source.
- Ask OpenSpec for current JSON status and instructions. Repository-backed
  planning is source-producing and binds concrete governing/reported
  resources; no fixed phase sequence belongs in runtime code.
- Keep driver execution outside the engine. Optional-driver fallbacks record
  degraded or unavailable assurance and retain the same terminal conditions.
- Runtime code uses only the Python standard library.

## Module ownership

- `product.py`: V6 identity vocabulary and official workflow catalog.
- `model.py`: immutable task values, strict JSON, errors, and receipts.
- `workflow.py`: workflow-v1/v2 contracts, adapters, graph validation, and
  selected-definition identity.
- `delivery.py`: contracts, decisions, seals, bindings, resources, freshness,
  coverage, and dossiers.
- `engine.py`: replay, mutation plans, assurance routing, records, projections,
  and task views.
- `store.py`: path safety, locks, revision CAS, and atomic persistence.
- `git_client.py`: bounded content-sensitive read-only snapshots.
- `controller.py`: application coordination and all state mutations.
- `cli.py` and `hook.py`: wire adapters; neither owns workflow policy.

Keep these dependencies explicit. Avoid global execution order, string-based
late binding, overlapping service layers, or filesystem/process access in the
pure domain modules.

## Workflow and compatibility changes

Official workflows are `lite`, `feature`, `bugfix`, `investigation`,
`refactor`, and `full`. Workflow-v2 nodes declare typed artifacts, workspace
roles, inputs, finite assurance rework, exhausted dossier paths, and optional-
driver fallback metadata. Linear workflow-v1 files remain accepted through
their explicit adapter for new V6 tasks.

Changes to task schema, workflow language/adapter, selected workflow, catalog,
record, artifact, driver, projection, package, and data namespace have
different compatibility effects. Update only the identity domain owned by the
changed contract and prove the expected isolation. V5 data remains in the V5
namespace and requires a V5 installation for inspection.

## Validation

Run only the smallest test modules or individual cases that directly cover the
changed behavior. Full unittest discovery is prohibited, including release or
milestone requests. On this macOS host, leave native Windows and Linux checks
explicitly unverified.

Typical focused commands are:

```sh
python3 -I -S tests/test_v6_workflow_validation.py -v
python3 -I -S tests/test_workflow_v1_validation.py -v
python3 -I -S tests/test_yaml_subset.py -v
python3 -I -S tests/test_v6_package.py -v
python3 -I -S tests/test_v6_delivery_runtime.py -v
python3 -I -S tests/test_workflow_v1_runtime.py -v
python3 -I -S tests/test_v6_controller_contracts.py -v
python3 -I -S tests/test_v6_store_integrity.py -v
python3 -I -S tests/test_v6_stale_mutations.py -v
python3 -I -S tests/test_v6_cli.py -v
python3 -I -S tests/test_v6_hook.py -v
python3 -I -S tests/test_v6_git_snapshot.py -v
python3 -I -S tests/test_v6_installed_journeys.py -v
python3 -I -S scripts/validate_package.py
python3 -m json.tool .codex-plugin/plugin.json
```

Choose only the applicable commands from the V6 focused CI matrix. Validate
the active OpenSpec change with its current CLI instructions.

Validate every bundled Skill after editing it:

```sh
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/analyze-change-impact
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/follow-dev-flow
python3 /Users/innocent-children/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/review-dev-flow-change
```

Release evidence distinguishes source-checkout checks from installed behavior.
An installed acceptance pass identifies the immutable installed snapshot and
covers the six official workflows, Hook/Skill pickup, structured/minimal
starts, binding-required apply, contract revision recovery, decisions and
waivers, optional-driver available/degraded paths, bounded assurance success
and exhaustion, dossier inspection, V5 retention, and explicit V5 rollback
inspection. Conditions that require a real new Codex task remain marked
manual or unverified when the environment cannot observe them.

Before handoff:

- inspect the complete tracked and untracked diff;
- run whitespace/error checks for changed files;
- confirm English and Chinese product claims have the same scope and strength;
- perform an independent read-only review against the exact current snapshot;
- report every skipped or manual check precisely.
