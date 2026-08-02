## ADDED Requirements

### Requirement: The product ships an official personal workflow family
The product SHALL provide built-in `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full` workflows. Each workflow SHALL begin with bounded read-only repository preflight, remain within one task and one repository, declare the artifacts it produces, support cancellation from every non-terminal stage, and finalize non-cancelled delivery through a Delivery Dossier.

#### Scenario: User selects each official workflow
- **WHEN** a caller starts a task with any official workflow ID
- **THEN** the controller loads the packaged definition, pins its identity, and projects its preflight action

#### Scenario: Investigation has no implementation
- **WHEN** an investigation task reaches its delivery path without a code change
- **THEN** its workflow records investigation and verification artifacts without requiring a fabricated implementation artifact

#### Scenario: Workflow catalog and files drift
- **WHEN** an official ID lacks a file or a packaged official file is absent from the catalog
- **THEN** package validation fails

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

### Requirement: V6 compatibility identities are independently scoped
V6 SHALL use distinct identities for installed release, task schema/namespace, workflow language/adapter, selected workflow, built-in catalog, records, artifacts, driver capabilities, and agent projection. V6 SHALL leave V5 task data unchanged. The selected-workflow identity SHALL bind the exact canonical definition, language, and adapter without binding the whole built-in catalog. A catalog-only or projection-only change SHALL not invalidate stored task replay. An unsupported task or record schema SHALL fail closed. A selected-definition change SHALL invalidate only tasks pinned to that definition. The V6 loader SHALL continue to accept existing absolute-path linear workflow-v1 documents for new V6 tasks and SHALL pin the exact selected definition.

#### Scenario: V6 starts beside retained V5 data
- **WHEN** V5 task directories already exist during V6 installation
- **THEN** V6 writes new tasks only below the V6 namespace and does not read, copy, alter, or delete V5 task files

#### Scenario: Existing linear custom definition starts a new V6 task
- **WHEN** a caller selects a valid absolute-path workflow-v1 document
- **THEN** V6 adapts its linear node contracts to the V6 replay boundary and pins the document identity for that new task

#### Scenario: Official catalog gains an unrelated workflow
- **WHEN** the catalog identity changes while a task's selected workflow document and adapter remain unchanged
- **THEN** that existing task continues to load and replay while package discovery exposes the new catalog

#### Scenario: Selected workflow changes
- **WHEN** the canonical selected workflow document or its adapter identity differs from the pinned identity
- **THEN** only tasks pinned to that changed definition fail with a workflow identity mismatch

#### Scenario: Record schema is unsupported
- **WHEN** replay encounters a record whose schema is not in the installed record vocabulary
- **THEN** task loading fails closed without treating catalog, package, or projection identities as substitutes

#### Scenario: Agent projection schema changes
- **WHEN** the installed agent-protocol identity changes while persisted task and selected-workflow identities remain supported
- **THEN** the store continues to replay the task and emits the new projection contract to compatible consumers

#### Scenario: V5 task must be inspected after upgrade
- **WHEN** a user needs to resume or inspect a retained V5 task
- **THEN** published guidance directs the user to a V5 installation and its unchanged V5 data namespace
