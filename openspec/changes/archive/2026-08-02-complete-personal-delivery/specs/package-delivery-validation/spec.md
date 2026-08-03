## ADDED Requirements

### Requirement: Candidate validation covers the official delivery portfolio
Candidate validation SHALL derive required workflow assets from the candidate product catalog and SHALL validate every official workflow's schema, identity, artifact declarations, bounded assurance routes, driver fallback metadata, terminal dossier path, Skill guidance, package version, and bilingual documentation references.

#### Scenario: Official workflow loses its exhausted route
- **WHEN** a candidate official workflow declares rework without a finite attempt budget and exhausted target
- **THEN** candidate validation fails

#### Scenario: Optional driver loses its fallback
- **WHEN** a candidate official workflow declares an optional driver without a produced artifact type or fallback instructions
- **THEN** candidate validation fails

#### Scenario: Complete candidate is validated elsewhere
- **WHEN** a copied Stage 1 candidate has a coherent product catalog, official workflow family, Skills, manifest, package version, and documentation
- **THEN** candidate-root validation succeeds using only that candidate's content

### Requirement: Installed acceptance evidence covers Stage 1 journeys
Release evidence SHALL identify the installed package version and immutable snapshot path/digest and SHALL exercise the installed launcher, Hook, Skills, controller, and packaged assets. It SHALL cover real `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full` journeys. Across that installed matrix it SHALL cover interruption recovery, accepted contract revision followed by recovery, criterion and review-waiver decisions, cancellation, bounded verification and review rework, exhausted incomplete delivery, optional tools both available and degraded, current acceptance coverage, and successful/incomplete Delivery Dossier inspection. It SHALL also prove that retained V5 data is untouched, V6 uses its own namespace, and reinstalling the retained V5 snapshot can inspect its V5 task. Source-checkout tests SHALL remain distinct from installed evidence, and any Hook or Skill pickup condition that requires external/manual observation SHALL be labeled with that exact verification status.

#### Scenario: Source tests pass without installed journeys
- **WHEN** runtime tests pass but the installed Stage 1 journey evidence is absent
- **THEN** the Stage 1 release gate remains unverified

#### Scenario: Installed journeys complete
- **WHEN** the declared installed workflows run through the installed launcher, Hook, Skills, controller, and package snapshot
- **THEN** release evidence records snapshot identity, task IDs, repository baselines, verification commands and results, driver paths, and dossier outcomes

#### Scenario: Contract scope changes after interruption
- **WHEN** an installed task records an accepted contract revision and a later session resumes it
- **THEN** the installed controller replays the original and revised contracts, revision-source snapshot, planning reentry, and fresh assurance budget, then completes with replacement planning and evidence bound to the revised scope

#### Scenario: Installed OpenSpec plan governs repository resources
- **WHEN** an installed OpenSpec-backed planning stage creates repository artifacts, implementation changes unrelated code, a bound spec is then changed, and contract revision reenters planning
- **THEN** evidence shows the original plan and semantic task digest survive unrelated code and checkbox progress, become stale on governing spec or substantive task changes, and are replaced from the new contract's revision source before delivery resumes

#### Scenario: V5 and V6 coexistence is exercised
- **WHEN** installed V6 runs beside retained V5 task data and the retained V5 snapshot is reinstalled for rollback inspection
- **THEN** evidence shows isolated namespace paths, unchanged V5 files, successful V6 task operation, and successful V5 inspection with the retained package

#### Scenario: External pickup cannot be automated
- **WHEN** a release environment cannot directly observe a new Codex task loading the installed Hook or Skill
- **THEN** that exact installed pickup condition remains explicitly manual or unverified and cannot be replaced by source-checkout test claims

## REMOVED Requirements

### Requirement: Public skill guidance matches V5
**Reason**: Stage 1 advances the product to V6 and adds a catalog-backed official workflow family, so a V5-specific public-guidance requirement would reject the current product.

**Migration**: Validate public Skill and agent metadata against the candidate's current product generation, supported repository topology, controller namespace, built-in workflow catalog, and `$follow-dev-flow` invocation.

## ADDED Requirements

### Requirement: Public skill guidance matches the current product
The packaged `follow-dev-flow` Skill and agent metadata SHALL describe the candidate's current single-repository product generation, SHALL invoke `$follow-dev-flow` in its default prompt, and SHALL explain official workflow selection, structured contracts, bounded assurance, optional-driver fallback, scope decisions, and Delivery Dossier completion without claiming later roadmap capabilities.

#### Scenario: Packaged agent metadata is inspected
- **WHEN** package validation reads the main Skill and agent metadata
- **THEN** stale product-generation, workflow-catalog, controller-namespace, or multi-repository guidance causes validation to fail
