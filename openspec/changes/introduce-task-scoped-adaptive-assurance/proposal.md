## Why

Delivery assurance currently binds the complete Git-visible repository set to a fixed verification and review graph. The official `feature`, `bugfix`, and `refactor` flows require review regardless of whether the task activates a review-relevant risk, and review rework returns through shared assurance loops. Pre-existing or concurrent unrelated changes can therefore enter review or invalidate task evidence, while review findings have no controller-enforced causal boundary and rework can execute more verification than the declared budget. The product needs a task-owned evidence boundary and assurance effort derived from the accepted scope, affected behavior, and delivery risk.

## What Changes

- Establish a task-exclusive change capsule for every repository-set task. Preflight records the exact baseline, including worktree and Git index content, and later source actions and contract revisions maintain an explicit controller-derived roll-forward task change manifest with complete per-path ownership claims and adoption lineage.
- Separate task-owned changes from ambient workspace drift. Assurance consumes the task change capsule; unclaimed drift is reported with repository and path diagnostics and requires an explicit ownership or scope decision before repository-dependent progress continues.
- Add a structured assurance plan that maps acceptance criteria and affected behavior to required repository checks, integration checks, independent review, evidence reuse rules, and absolute execution budgets. A closed versioned policy fixes the six official profile floors, confidence fallback, risk triggers, canonical obligation grouping, and numeric product bounds.
- Project verification and review from outstanding assurance obligations. Unaffected proof remains reusable when its bound task-change slice, governing inputs, and declared impact closure remain current; unknown impact fails closed to the conservative obligation set.
- Replace free-form blocking review control with structured findings that bind severity, blocking status, causal relation, acceptance criteria, repository, path or symbol, evidence, and review fingerprint. The controller derives the review outcome; only current blocking findings causally related to the task can enter rework, while unresolved blocking causality requires bounded triage and newly proven out-of-closure effects force impact replanning.
- Add explicit operator dispositions for disputed causal scope, accepted risk, and contract expansion. Every disposition is contract- and finding-bound and remains visible in the Delivery Dossier.
- Enforce verification, review, rework, and total-action budgets as absolute per-contract ceilings across every workflow route. Persisted reuse and governance decisions consume total-action authority without pretending to be assurance executions; projections expose required obligations, completed evidence, remaining attempts, and the maximum remaining action count.
- Make Git snapshots bind the staged index blob for regular files, symlinks, and gitlinks in addition to the worktree observation, so any reviewed index-content change invalidates the binding.
- **BREAKING** Introduce the `0.3.0` product and schema family for task change manifests, assurance plans, verification coverage, structured review findings, action bindings, snapshots, projections, records, and Delivery Dossiers.
- **BREAKING** Treat every `0.2.0` task and artifact as unsupported input. The `0.3.0` runtime performs no historical discovery, replay, migration, translation, or compatibility handling and does not delete retained old-version bytes.
- **BREAKING** Enforce one active task lease per canonical worktree-specific identity. The same physical worktree cannot join another task until the owner reaches a controller-confirmed terminal state, while distinct linked worktrees remain independently leasable. Unresolved corruption in the current 0.3 task inventory blocks new admission rather than releasing a lease implicitly.

## Capabilities

### New Capabilities

- `task-owned-change-capsules`: Defines worktree-specific membership leases, exact preflight baselines, controller-derived per-path change ownership, ambient-drift handling, contract-revision carry-forward, and canonical task-change manifests.
- `adaptive-assurance-planning`: Defines risk-derived assurance plans, obligation projection, selective evidence invalidation and reuse, absolute budgets, and explainable completion decisions.
- `review-finding-governance`: Defines structured causal review findings, controller-derived review outcomes, non-rework adjacent observations, unresolved-causality triage, impact-gap replanning, and explicit operator dispositions.

### Modified Capabilities

- `personal-delivery-workflows`: Replaces fixed assurance loops with obligation-driven verification, review, rework, and hard per-contract ceilings under the `0.3.0` workflow language.
- `delivery-evidence-and-dossier`: Adds task-change and assurance-plan provenance, index-aware snapshot identity, slice-aware freshness, structured finding lineage, and Dossier reporting for required, reused, skipped, waived, and exhausted assurance.
- `multi-repository-delivery`: Applies ownership, leases, impact closure, selective member evidence, and integration obligations across the exact canonical repository set.
- `delivery-contract-and-decisions`: Adds finding-bound dispositions and contract-expansion authority while preserving explicit user ownership and deterministic replay.
- `task-discovery-boundaries`: Prevents overlapping active task leases and reports the exact owning task for every conflicting repository root.
- `package-delivery-validation`: Validates the `0.3.0` schema family, adaptive workflow catalog, Skill guidance, and end-to-end task-scoped assurance journeys.

## Impact

- Runtime: `product.py`, `model.py`, `snapshot.py`, `git_client.py`, `workflow.py`, `workflows.py`, `engine.py`, `delivery.py`, `controller.py`, `store.py`, `hook.py`, and `cli.py`.
- Public workflow assets: all official definitions under `workflows/` and the custom-workflow validation contract.
- Agent behavior: `follow-dev-flow`, `analyze-change-impact`, and `review-dev-flow-change` Skills and their packaged metadata.
- Persistence and protocols: a new versioned controller data namespace and `0.3.0` task, record, snapshot, binding, projection, assurance, review, and Dossier schemas.
- Installation and validation: candidate validation, installed journeys, replay tests, multi-repository tests, and package metadata.
- Public documentation: English source documents followed by complete Simplified Chinese synchronization for workflow selection, evidence boundaries, budgets, the clean protocol cut, and recovery.
- Runtime dependencies remain Python standard-library-only; OpenSpec, codebase-memory, and independent review remain optional drivers with explicit evidence status.
