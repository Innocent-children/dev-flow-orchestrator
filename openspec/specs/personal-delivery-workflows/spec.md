# personal-delivery-workflows Specification

## Purpose
TBD - created by archiving change complete-personal-delivery. Update Purpose after archive.
## Requirements
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

### Requirement: Assurance failures are persisted and rework is bounded
Verification and review nodes SHALL persist passing and failing outcomes. A failing outcome SHALL follow the node's declared rework target while attempts remain and SHALL follow its declared exhausted target when the finite attempt budget is consumed. Attempts SHALL be counted by `(node_id, effective_contract_digest)`, so contract revision preserves prior attempts historically and starts a fresh budget for revised scope. Workflow validation SHALL reject any graph that can cycle without consuming a bounded failure edge.

#### Scenario: Verification fails and later passes
- **WHEN** verification records a failed command within its attempt budget, rework completes, and the next verification passes
- **THEN** both attempts remain in history and the task advances on the passing route

#### Scenario: Review requests changes
- **WHEN** review records changes requested within its attempt budget
- **THEN** the task enters review rework and returns through fresh verification before re-review

#### Scenario: Rework budget is exhausted
- **WHEN** a verification or review node records its final allowed failing attempt
- **THEN** the task advances deterministically to incomplete dossier finalization with the failed assurance retained

#### Scenario: Contract changes after a failed attempt
- **WHEN** a contract revision reenters planning after one or all assurance attempts were consumed under the prior digest
- **THEN** the revised contract projects the full declared budget for its first assurance attempt while retaining all prior-contract attempts in history across restart

#### Scenario: Workflow contains an unbounded cycle
- **WHEN** removing all declared finite failure edges leaves a cycle in the workflow graph
- **THEN** workflow validation rejects the definition

### Requirement: Optional drivers have an explicit degraded path
An official workflow stage that names an optional OpenSpec, codebase-memory, or independent-review driver SHALL declare its tool, produced artifact type, and fallback instructions. The runtime SHALL project driver metadata without dynamically loading or executing driver code. The main Skill SHALL use the named tool when available or follow the declared fallback and record the resulting driver status. Review records SHALL distinguish `independent` and `self` assurance and `approved`, `changes-requested`, and `unavailable` outcomes.

#### Scenario: Optional tool is available
- **WHEN** Codex can invoke an official stage's named optional tool
- **THEN** the produced artifact records that tool as its source path

#### Scenario: Optional tool is unavailable
- **WHEN** an optional tool cannot be invoked
- **THEN** the Skill follows the declared fallback, records degraded driver status, and preserves the same terminal acceptance requirements

#### Scenario: Independent tool approves
- **WHEN** the independent-review driver produces an approved result bound to the exact current snapshot
- **THEN** the review records independent approval and may follow the success target

#### Scenario: Fallback self-review finds changes
- **WHEN** the independent-review tool is unavailable and fallback self-review requests changes
- **THEN** the review records self assurance and follows the bounded failure route

#### Scenario: Fallback cannot provide independence
- **WHEN** fallback self-review finds no blocking issue but no current review-assurance waiver exists
- **THEN** the review records unavailable independent assurance, consumes the bounded failure budget, and eventually reaches incomplete finalization if independence remains unavailable

#### Scenario: Operator waives unavailable independent review
- **WHEN** an exact current `assurance-waiver` decision governs the review node and the review records unavailable independent assurance
- **THEN** the workflow may follow the success target while the dossier reports a waiver and never labels self-review as independent approval

### Requirement: Optional tool outputs follow tool-specific correctness contracts
OpenSpec stages SHALL request current machine-readable status and instructions for the selected change and SHALL record the concrete artifact paths and digests they used. An OpenSpec stage that creates or updates repository files SHALL be a source-producing stage with a pinned source predecessor and authoritative governing resource bindings for proposal, design, and specs. Its `tasks.md` SHALL record a raw progress digest and a governing semantic digest that ignores only task-list checkbox state while preserving text, order, and test obligations. Machine-generated status output MAY be reported without governing plan freshness. Codebase-memory stages SHALL keep baseline and current-generation workspace project IDs separate, select the graph appropriate to the current workflow phase, confirm material conclusions in source, and record stale, unavailable, or unconfirmed graph evidence as degraded. Independent review SHALL bind its verdict, findings, base revision, artifact digest, and guidance snapshot digest to the exact reviewed snapshot. These contracts SHALL be enforced by Skill guidance and package validation while runtime execution remains outside the controller.

#### Scenario: OpenSpec stage uses current instructions
- **WHEN** an OpenSpec-backed stage runs
- **THEN** its source-producing artifact records the selected change, current JSON status/instructions, concrete returned artifact paths and authoritative digests, and governing versus reported resource roles

#### Scenario: Code graph generation changes
- **WHEN** impact analysis compares a baseline with current code
- **THEN** it uses separate project IDs, selects each by phase, and confirms every material graph conclusion against source before recording it

#### Scenario: Graph evidence cannot be confirmed
- **WHEN** codebase-memory output is unavailable, stale, or materially unconfirmable in source
- **THEN** the fallback artifact records degraded coverage and does not present the graph conclusion as complete proof

#### Scenario: Independent review snapshot drifts
- **WHEN** the base revision, artifact digest, or guidance snapshot changes during review
- **THEN** the review cannot record independent approval for the new snapshot and must be rerun

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
