## MODIFIED Requirements

### Requirement: The product ships an official personal workflow family
The product SHALL provide built-in `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full` workflows using the current `dev-flow-workflow/0.2.0` language. Each workflow SHALL begin with bounded read-only preflight over the task's exact repository set, remain within one task, one current action, and one Codex executor, declare the artifacts it produces, and finalize non-cancelled delivery through the current aggregate Delivery Dossier. Cancellation availability SHALL be declared explicitly by workflow stage. Official workflows SHALL make cancellation available from the normal majority of non-terminal stages while allowing a stage to omit cancellation when its product semantics require completion or another operator action. Repository topology SHALL be independently selectable as an exact set of one to eight user-prepared local Git worktrees; workflow depth SHALL NOT imply repository count, workspace management, parallel execution, or external delivery effects.

#### Scenario: User selects each official workflow
- **WHEN** a caller starts a task with any official workflow ID and one or more valid repository roots
- **THEN** the controller validates the packaged current-version workflow definition, pins its identity and exact repository set, and projects its preflight action using the same current product version

#### Scenario: Official workflow uses multiple repositories
- **WHEN** a caller starts any official workflow with two valid user-prepared worktrees
- **THEN** that workflow retains one task, one current action, one assurance budget, and one Codex executor while its artifacts and final dossier bind the complete repository set

#### Scenario: Investigation has no implementation
- **WHEN** an investigation task reaches its delivery path without a code change
- **THEN** its workflow records investigation and verification artifacts without requiring a fabricated implementation artifact

#### Scenario: A stage declares cancellation
- **WHEN** the current non-terminal stage declares a cancellation contract
- **THEN** the controller may cancel through the declared complete-snapshot, action-binding, revision-CAS, and one-record mutation boundary

#### Scenario: A stage does not declare cancellation
- **WHEN** the current non-terminal stage has no cancellation contract
- **THEN** the controller preserves the current action and rejects cancellation according to that workflow definition

#### Scenario: Workflow catalog and files drift
- **WHEN** an official ID lacks a file or a packaged official file is absent from the catalog
- **THEN** package validation fails

#### Scenario: Repository topology changes workflow semantics
- **WHEN** package or runtime metadata binds a workflow ID to one repository count, managed workspace strategy, or execution topology
- **THEN** validation fails because workflow depth and repository, workspace, and execution topology are independent product dimensions

## REMOVED Requirements

### Requirement: V6 compatibility identities are independently scoped
**Reason**: The current early-development product has one authoritative semantic version, workflow language, and repository-set protocol. Retaining independent task, workflow, projection, Dossier, adapter, or replay versions would create product paths with no current user data to serve.

**Migration**: None. Tasks and embedded values must match the current product identity and current schema vocabulary.

## ADDED Requirements

### Requirement: One pre-release version seals the supported protocol
The product SHALL expose exact semantic version `0.2.0` from one `PRODUCT_VERSION` runtime authority. Plugin/package metadata, task state, workflow documents, controller data namespace, every current schema identifier and digest domain, projections, evidence, Dossier, receipt, Skills, tests, and public guidance SHALL use that same value. The product SHALL derive one current `PRODUCT_IDENTITY` from the shared version, accepted schema vocabulary, and one-to-eight repository topology authorities. Selected-workflow identity SHALL bind only the workflow selector, current schema, and canonical document. Any unsupported task version, workflow schema, selected-workflow digest, record schema, or embedded value SHALL fail closed without migration, detection, translation, repair, or fallback.

#### Scenario: Current task loads
- **WHEN** a task and every persisted value match the installed current identities and schemas
- **THEN** deterministic replay derives the same state and current action

#### Scenario: Product surfaces are inspected
- **WHEN** package validation inspects runtime constants, plugin/package metadata, workflow assets, Skills, tests, and public guidance
- **THEN** every current version equals `0.2.0` and any generation-coded or component-specific current version causes validation to fail

#### Scenario: Workflow document changes
- **WHEN** the canonical selected workflow document differs from the pinned selected-workflow identity
- **THEN** the task fails with a workflow identity mismatch

#### Scenario: Unsupported schema is encountered
- **WHEN** task loading encounters any unsupported workflow, record, snapshot, projection, verification, or Dossier identity
- **THEN** loading fails closed without invoking an alternate parser or compatibility path

#### Scenario: Repository topology authority changes
- **WHEN** the supported topology or current schema vocabulary changes
- **THEN** the derived product identity changes and persisted tasks under the prior identity are not reinterpreted
