## Why

Personal delivery work can span an API, service, client, SDK, documentation, database, or infrastructure repository. The product needs one delivery task that preserves one accepted intent, one current action, and trustworthy completion evidence across an exact set of user-prepared repositories. A one-repository task is the smallest valid repository set and follows the same protocol as every larger set.

## What Changes

- Allow every task to bind an immutable, canonical set of one to eight local Git worktree roots. Caller order does not imply repository priority or dependency order.
- Reject duplicate, overlapping, missing, bare, unsafe, data-directory-overlapping, or otherwise invalid members before task creation.
- Capture every repository-backed operation as one sealed `dev-flow-repository-set-snapshot/0.2.0` value containing a bounded `dev-flow-workspace-snapshot/0.2.0` member snapshot for every repository.
- Require every repository-backed resource to identify its repository explicitly and resolve its relative path only within that member root.
- Use `0.2.0` as the sole current product version. The plugin manifest, package metadata, task state, data namespace, workflow documents, schema identifiers, projections, evidence, Dossier, receipt, Skills, tests, and public guidance all use that same version from one runtime authority.
- Use `dev-flow-workflow/0.2.0` as the workflow language. Selected-workflow identity binds the selector, schema, and canonical document. Repository-topology authority and every accepted current schema participate in `PRODUCT_IDENTITY`.
- Emit only `dev-flow-agent/0.2.0` projections. Every projection describes one exact `repository_set`, one current action, and one Codex executor.
- Record verification coverage with one structure containing criterion results, an exact result for every repository, and one repository-set integration result.
- Generate only `dev-flow-delivery-dossier/0.2.0`, with canonical member provenance, aggregate freshness, complete verification history, current assurance, outcome, and handoff for the exact repository set.
- Preserve deterministic append-only replay, revision compare-and-swap, bounded retry and recovery, stale-evidence diagnostics, and one aggregate completion decision within the current data model.
- Discover and resume a task from any member repository while preserving strict task identity and explicit ambiguity handling.
- Update runtime, tests, Skills, Hook guidance, package validation, manifest metadata, architecture, installation guidance, and bilingual product documentation to express and validate the same current model.
- Remove generation-coded source, test, CI, documentation, and symbol names. No compatibility, migration, detection, recovery, or fallback path is added for earlier development versions.

## Capabilities

### New Capabilities

- `multi-repository-delivery`: Defines exact repository-set identity, admission, aggregate snapshots, repository-scoped execution evidence, recovery, and completion for one task executed by one Codex across one to eight user-prepared local worktrees.

### Modified Capabilities

- `delivery-contract-and-decisions`: Contract initialization, revision, planning reentry, decisions, and waivers bind the immutable exact repository set.
- `delivery-evidence-and-dossier`: Records, artifacts, resources, action bindings, freshness, verification, projection, and Delivery Dossier use one repository-set-aware protocol.
- `personal-delivery-workflows`: Every official workflow supports the exact repository-set model while retaining one current action and bounded assurance behavior.
- `task-discovery-boundaries`: Repository/data-directory disjointness and task pickup apply to every repository-set member.
- `package-delivery-validation`: Packaged Skills, Hook metadata, validation, installed journeys, and public guidance prove the current repository-set contract and schema authority.

## Impact

- Runtime: product identity, task and workflow models, replay validation, controller mutations, Git snapshot orchestration, resource validation, freshness, action bindings, terminal dossier generation, task discovery, Hook context, and CLI parsing.
- Product assets: OpenSpec, focused tests, Skills, agent metadata, plugin manifest, package validation, installed acceptance scripts, architecture, contribution guidance, installation documentation, README files, and roadmap language.
- Data boundary: task loading, replay, workflow selection, projection, and completion validate the exact current schema and identity authorities and fail closed on mismatch.
- Dependencies: runtime code continues to use only the Python standard library and performs no implicit Git-changing operation.
