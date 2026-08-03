# package-delivery-validation Specification

## Purpose
TBD - created by archiving change fix-v5-confirmed-defects. Update Purpose after archive.
## Requirements
### Requirement: Candidate validation uses candidate content
The package validator SHALL evaluate the source, workflow definitions, product catalog, and public assets belonging to the candidate root supplied by the caller.

#### Scenario: Candidate workflow is invalid
- **WHEN** a copied candidate contains an invalid workflow while the invoking checkout remains valid
- **THEN** validation of that candidate fails

#### Scenario: Candidate is valid
- **WHEN** a complete candidate is validated from a different filesystem path
- **THEN** validation succeeds without using already imported modules from the invoking checkout

### Requirement: Verification evidence reflects an executed command
The installation smoke procedure SHALL record passing test evidence only after the documented verification command has executed successfully.

#### Scenario: Verification succeeds
- **WHEN** the documented verification command exits successfully
- **THEN** the smoke procedure records `passed: true` with that command

#### Scenario: Verification fails
- **WHEN** the documented verification command exits unsuccessfully
- **THEN** the smoke procedure does not record passing evidence

### Requirement: Public skill guidance matches the current product
The packaged `follow-dev-flow` Skill and agent metadata SHALL describe candidate version `0.2.0` and its repository topology as one exact set of one to eight user-prepared local Git worktrees. They SHALL invoke `$follow-dev-flow` in the default prompt and SHALL explain official workflow selection, repeatable repository selection, one-task/one-current-action/one-Codex execution, structured contracts, explicit repository-scoped resources, repository-set snapshot bindings, bounded assurance, optional-driver fallback, scope decisions, and aggregate Delivery Dossier completion without claiming later roadmap capabilities. Guidance SHALL specifically keep branch/worktree creation, Git publication, multi-Agent execution, and external CI/PR/release effects outside the controller's supported authority.

#### Scenario: Packaged agent metadata is inspected
- **WHEN** package validation reads the main Skill and agent metadata
- **THEN** stale or component-specific version, workflow-catalog, controller-namespace, single-repository-only, managed-workspace, or parallel-executor guidance causes validation to fail

#### Scenario: Multi-repository start guidance is inspected
- **WHEN** package validation reads the documented start path
- **THEN** it requires repeatable `--repo` usage, canonical exact-set semantics, user-prepared worktrees, and one Codex executor, with one `--repo` producing a one-member set under the same model

### Requirement: Candidate validation proves supported repository topology
The candidate package SHALL expose one authoritative repository-topology capability definition and SHALL validate runtime, CLI, Hook, Skills, official workflow coverage, installed journeys, and public documentation against it. Validation evidence SHALL cover a one-member set and a larger exact set that resumes from a secondary member, detects member drift, records explicitly scoped resources, and generates the current aggregate Dossier.

The same candidate validation SHALL require exact version `0.2.0` in the plugin manifest, package metadata, lock file, runtime authority, workflow documents, schema identifiers, Hook/Skill guidance, installed evidence, and current public documentation. Generation-coded V5/V6 names and component-coded v1/v2/v3 identities SHALL be rejected from current product assets. Historical OpenSpec archives are records rather than executable current-product assets.

Runtime action validation SHALL require every `driver_result` to identify `dev-flow-driver-result/0.2.0` and every verification `coverage` object to identify `dev-flow-verification-coverage/0.2.0`. Missing or unsupported embedded schemas SHALL fail closed during initial application and replay without conversion.

#### Scenario: Runtime and capability definition drift
- **WHEN** the candidate advertises exact-set topology but the CLI, task model, projection, Hook, or artifact boundary remains limited to the first repository
- **THEN** candidate validation fails

#### Scenario: Embedded current-product schema is missing or unsupported
- **WHEN** an action submits a `driver_result` or verification `coverage` value without its exact current schema
- **THEN** action validation fails without recording a partial result

#### Scenario: Unsupported later-stage capability is claimed
- **WHEN** candidate assets claim automatic branch/worktree management, parallel repository executors, per-repository partial assurance reuse, or external CI/PR/release orchestration
- **THEN** candidate validation fails because those capabilities are outside the multi-repository personal delivery core

#### Scenario: Installed exact-set journey succeeds
- **WHEN** the installed candidate executes a task over two user-prepared worktrees, resumes it from the second repository, verifies current aggregate evidence, and finalizes delivery
- **THEN** the recorded dossier identifies both repositories and candidate validation accepts the journey

#### Scenario: Installed one-member journey succeeds
- **WHEN** the installed candidate executes and finalizes a task with one `--repo` argument
- **THEN** its snapshot, projection, structured verification, scoped resources, and Dossier use the same current repository-set schemas as the larger-set journey
