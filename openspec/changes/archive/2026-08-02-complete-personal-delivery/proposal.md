## Why

The current product reliably advances one single-repository task through a linear preflight, implementation, and verification path, but it does not preserve a structured delivery contract, prove individual acceptance criteria, converge bounded verification or review rework, or produce a final delivery record. Stage 1 turns that reliable execution foundation into a complete personal delivery product for real features, bug fixes, investigations, and refactors.

## What Changes

- Introduce a versioned delivery contract containing acceptance criteria, scope, constraints, risks, non-goals, and open questions, plus append-only scope revisions and decisions.
- Add built-in `feature`, `bugfix`, `investigation`, `refactor`, and `full` workflows alongside the `lite` fast path.
- Add outcome-aware verification and review nodes with deterministic, bounded rework and an explicit exhausted outcome.
- Record typed artifacts and evidence with producer, repository baseline, contract revision, input lineage, digest, and derived freshness.
- Expose optional OpenSpec, codebase-memory, and independent-review driver instructions with an explicit declared fallback when an optional tool is unavailable.
- Finalize every non-cancelled official workflow with a Delivery Dossier covering changes, acceptance criteria, commands and results, review, documentation, risks, waivers, and handoff.
- **BREAKING** Advance the product, task, workflow, and plugin-data identities for the Stage 1 release while retaining V5 data as a separate installed namespace; V5 tasks remain readable only with a V5 installation.
- Update the controller, CLI, Hook projection, Skills, package validation, architecture, installation guidance, README files, and focused installed-user-journey evidence.

## Capabilities

### New Capabilities

- `delivery-contract-and-decisions`: Structured original intent, stable acceptance-criterion identities, append-only contract revisions, and attributable decisions or waivers.
- `personal-delivery-workflows`: The official personal workflow family, bounded verification and review rework, and explicit optional-driver fallback behavior.
- `delivery-evidence-and-dossier`: Typed artifacts, provenance and freshness, acceptance coverage, terminal readiness checks, and Delivery Dossier generation.

### Modified Capabilities

- `package-delivery-validation`: Package and public-skill validation must derive current product and workflow claims from the Stage 1 product catalog instead of requiring V5-only guidance.

## Impact

The change affects the domain model, workflow schema and catalog, engine replay and transition validation, controller and CLI start/mutation paths, Hook and agent projection, bundled Skills and workflows, package validation, tests, and English and Chinese documentation. Runtime code remains Python-standard-library-only. The supported execution scope remains one local task, one Git repository, the current worktree, and one Codex executor; workspace orchestration, multi-agent execution, multi-repository delivery, and team coordination remain later roadmap stages.
