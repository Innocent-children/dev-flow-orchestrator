# delivery-contract-and-decisions Specification

## Purpose
TBD - created by archiving change complete-personal-delivery. Update Purpose after archive.
## Requirements
### Requirement: Task start persists a structured delivery contract
The controller SHALL persist an immutable original delivery contract containing a schema, positive revision, summary, stable acceptance-criterion IDs and statements, scope, constraints, risks, non-goals, and open questions. Revision-zero initialization SHALL atomically store that contract with the complete immutable canonical repository tuple under the current task and product identities. A requirement-only start SHALL create a bounded minimal contract whose delivery scope is the complete repository set, while an explicitly supplied contract SHALL pass strict shape and size validation before any task state is written. Repository IDs and repository-set identity SHALL be controller-derived from task membership and SHALL NOT be accepted from caller contract fields or persisted as copied contract fields.

#### Scenario: Explicit contract starts a task
- **WHEN** a caller starts a task with a valid structured contract and one through eight valid repository roots
- **THEN** the original contract and canonical repository set are stored together in revision-zero initialization state, no ledger record exists yet, and the contract and repository-set digests are exposed in the task view

#### Scenario: Lite start omits a contract
- **WHEN** a caller starts `lite` with only a non-empty requirement and one or more valid repository roots
- **THEN** the controller derives a minimal contract at contract revision one covering that requirement and complete repository set while the task remains at task revision zero

#### Scenario: Caller permutes repository arguments
- **WHEN** otherwise-identical starts supply the same canonical repository set in different argument orders
- **THEN** both contracts bind the same canonical member ordering and repository-set identity

#### Scenario: Contract is invalid
- **WHEN** a contract has duplicate criterion IDs, missing required fields, unknown fields, invalid types, or exceeds its bounded size
- **THEN** task creation fails before state is written

#### Scenario: Repository set is invalid
- **WHEN** the contract is valid but any supplied repository is duplicate, overlapping, unavailable, bare, unsafe, or overlaps the controller data directory
- **THEN** task creation fails before persisting the contract or any partial repository membership

### Requirement: Contract revisions preserve original intent and reenter planning
The controller SHALL accept contract revision only after preflight has committed as the task's first record. Callers SHALL supply any different initial scope through the structured contract at creation, and later revision SHALL NOT add, remove, replace, relocate, or reorder the immutable repository set. The controller SHALL append every accepted later contract revision using the current typed record fields and payload, including the previous and new contract digests, reason, actor label, timestamp, monotonically increasing contract revision, and deterministic workflow reentry transition. Revision SHALL first capture one safe stable repository-set snapshot containing every canonical member, including the sole member of a one-member set, and the same record SHALL establish it as the `revision-source` artifact bound to the new contract. No member observation SHALL commit separately. This SHALL be the only cross-contract source bridge; all governing, causal, and assurance artifacts from the prior contract remain historical. Each current workflow SHALL declare its contract-revision target. Official delivery workflows SHALL return revised scope to impact/planning and `lite` SHALL return to implementation. The original contract and every earlier current-schema revision SHALL remain unchanged and replayable.

#### Scenario: Scope revision is accepted
- **WHEN** a non-terminal task records a valid replacement contract whose revision is exactly one greater than the effective contract
- **THEN** one contract-revision record is appended, the current node follows the definition's revision target, and subsequent planning and delivery actions bind to the new contract digest

#### Scenario: Repository-set scope revision is accepted
- **WHEN** a scope revision captures every member safely and stably
- **THEN** the same one contract-revision record establishes the aggregate revision source, and subsequent actions bind the new contract and repository-set digests

#### Scenario: Repository-set revision reenters planning
- **WHEN** scope is revised after repository-backed plans exist in multiple members
- **THEN** the one aggregate revision source becomes the required cross-contract predecessor and replacement planning records repository-scoped resources before implementation resumes

#### Scenario: One member changes during revision capture
- **WHEN** any member becomes unavailable, unsafe, over budget, or changes while the aggregate revision snapshot is collected or revalidated
- **THEN** revision fails without changing the effective contract, current node, ledger, repository set, or assurance budget and records no partial revision source

#### Scenario: Revision attempts to change repository membership
- **WHEN** a replacement contract request also proposes adding, removing, replacing, or reordering a member
- **THEN** the controller rejects the request and requires a new task for the different repository set

#### Scenario: Revision skips a contract version
- **WHEN** a replacement contract does not advance the effective contract revision by exactly one
- **THEN** the revision fails without advancing the task

#### Scenario: Contract revision is requested before preflight
- **WHEN** a revision-zero task receives a contract-revision request before its complete repository-set preflight record exists
- **THEN** the controller rejects the request, preserves revision zero and the original contract, and continues to project preflight as the first mutation

#### Scenario: Task resumes after a contract revision
- **WHEN** a new controller loads a task whose contract was revised
- **THEN** replay derives the same effective contract, repository-set-scoped revision source, and planning reentry while retaining the original and intermediate contracts

### Requirement: Decisions and waivers are explicit post-preflight records
The controller SHALL accept decisions and waivers only after complete preflight has committed as the task's first record. It SHALL append decisions with the existing exact decision payload fields: a task-unique stable decision ID, kind, subject, outcome, rationale, actor label, timestamp, and effective contract revision and digest. `(task_id, decision_id)` SHALL be the global decision identity, and a decision ID SHALL never be reused within its task ledger. A `(kind, subject)` pair SHALL occur at most once within one contract digest; correction requires a later contract revision and a new decision ID. A criterion waiver SHALL use kind `criterion-waiver`, subject equal to one acceptance-criterion ID, and outcome `waived`; it SHALL waive only that criterion rather than all evidence for a member. A review waiver SHALL use kind `assurance-waiver`, subject equal to one review node ID, and outcome `waived`. Every waiver SHALL become stale when its contract digest changes. The decision's task ownership implicitly binds it to immutable task membership; it SHALL NOT add copied repository-set fields, change membership, or fabricate a fresh snapshot.

#### Scenario: Criterion waiver is recorded
- **WHEN** an explicit waiver decision references a criterion in the effective contract
- **THEN** the existing decision payload is appended under the task and terminal coverage may classify only that criterion as waived

#### Scenario: Decision is requested before preflight
- **WHEN** a revision-zero task receives any decision or waiver request before its complete preflight record exists
- **THEN** the controller rejects the request, preserves the empty ledger and revision zero, and continues to project preflight as the first mutation

#### Scenario: Agent evidence claims a waiver
- **WHEN** repository or integration verification output directly classifies a criterion as waived without a current waiver decision
- **THEN** the action fails without advancing the task

#### Scenario: Contract changes after a waiver
- **WHEN** the contract is revised after a waiver was recorded
- **THEN** the earlier waiver is retained historically and excluded from current acceptance coverage

#### Scenario: Decision ID is reused in a task
- **WHEN** a decision attempts to reuse any earlier stable decision ID in the same task ledger
- **THEN** the mutation is rejected without appending a record

#### Scenario: Conflicting decision targets the same subject
- **WHEN** a second decision uses the same kind and subject under the same effective contract digest
- **THEN** the mutation is rejected and correction requires a contract revision plus a new decision ID

#### Scenario: Decision attempts to add repository membership
- **WHEN** a candidate decision payload adds repository-set fields or attempts to change membership
- **THEN** exact payload validation rejects it without changing the ledger or current action

#### Scenario: Decisions replay after restart
- **WHEN** a controller restarts after criterion and review-waiver decisions were recorded
- **THEN** replay derives the same unique applicable decisions and repository-set binding and rejects any duplicate or conflicting ledger history as invalid state

### Requirement: Contract and decision mutations preserve workflow authority
Contract revisions and decisions SHALL be controller mutations protected by the one task lock, revision compare-and-swap, deterministic replay, terminal-state rejection, bounded payload validation, and immutable repository-set validation. A decision SHALL append exactly one current-shape record without changing the current workflow node. A contract revision SHALL append exactly one record and may change the node only to the workflow's declared revision target recorded in that same record. That one record SHALL contain the complete aggregate revision source for every supported repository-set size and SHALL NOT be split into per-repository subrecords. Neither mutation SHALL expose a second projected workflow action. Task creation SHALL be the explicit revision-zero initialization exception; it persists the original contract and canonical repository tuple atomically and appends no record. Task, workflow, snapshot, projection, record, artifact, and action-binding values SHALL be accepted only under the current product identity and current schemas; unsupported identities or shapes SHALL fail closed without migration or fallback.

#### Scenario: Revised scope refreshes repository-backed planning
- **WHEN** a contract is revised after repository-backed plans were recorded in one or more members
- **THEN** the revision record binds the complete current aggregate workspace as a new-contract revision source, the workflow reenters its declared planning stage, old-contract artifacts remain historical, and replacement plans consume that source with explicit repository-scoped resources before implementation resumes

#### Scenario: Snapshot fails during contract revision
- **WHEN** a post-preflight contract revision cannot capture or revalidate a stable safe bounded snapshot for every member
- **THEN** the revision fails without changing the effective contract, node, ledger, repository set, or assurance budget

#### Scenario: Concurrent decision loses the revision race
- **WHEN** another mutation commits before a decision or contract revision acquires the current revision
- **THEN** the losing mutation receives a revision conflict with the fresh single-action projection and writes no partial record

#### Scenario: Terminal task receives a scope revision
- **WHEN** a caller attempts to revise a terminal task
- **THEN** the controller rejects the mutation and preserves the terminal state and aggregate dossier

#### Scenario: Current decision history loads
- **WHEN** a task contains valid current-schema contract revisions or decisions for any supported repository-set size
- **THEN** replay preserves every record and digest and derives repository scope from immutable task membership
