## ADDED Requirements

### Requirement: Task start persists a structured delivery contract
The controller SHALL persist an immutable original delivery contract containing a schema, positive revision, summary, stable acceptance-criterion IDs and statements, scope, constraints, risks, non-goals, and open questions. A requirement-only start SHALL create a bounded minimal contract, while an explicitly supplied contract SHALL pass strict shape and size validation before any task state is written.

#### Scenario: Explicit contract starts a task
- **WHEN** a caller starts a task with a valid structured contract
- **THEN** the original contract is stored in revision-zero initialization state, no ledger record exists yet, and its digest is exposed in the task view

#### Scenario: Lite start omits a contract
- **WHEN** a caller starts `lite` with only a non-empty requirement
- **THEN** the controller derives a minimal contract at contract revision one with a stable acceptance criterion covering that requirement while the task remains at task revision zero

#### Scenario: Contract is invalid
- **WHEN** a contract has duplicate criterion IDs, missing required fields, unknown fields, invalid types, or exceeds its bounded size
- **THEN** task creation fails before state is written

### Requirement: Contract revisions preserve original intent and reenter planning
The controller SHALL accept contract revision only after preflight has committed as the task's first record. Callers SHALL supply any different initial scope through the structured contract at creation. The controller SHALL append every accepted later contract revision as a complete typed record containing the previous and new contract digests, reason, actor label, timestamp, monotonically increasing contract revision, and deterministic workflow reentry transition. Revision SHALL first capture a safe current workspace snapshot and the same record SHALL establish it as a `revision-source` artifact bound to the new contract. This SHALL be the only cross-contract source bridge; all governing, causal, and assurance artifacts from the prior contract remain historical. Each workflow SHALL declare its contract-revision target. Official delivery workflows SHALL return revised scope to impact/planning, `lite` SHALL return to implementation, and the workflow-v1 adapter SHALL return to preflight. The original contract and every earlier revision SHALL remain unchanged and replayable.

#### Scenario: Scope revision is accepted
- **WHEN** a non-terminal task records a valid replacement contract whose revision is exactly one greater than the effective contract
- **THEN** one contract-revision record is appended, the current node follows the definition's revision target, and subsequent planning and delivery actions bind to the new contract digest

#### Scenario: Revision skips a contract version
- **WHEN** a replacement contract does not advance the effective contract revision by exactly one
- **THEN** the revision fails without advancing the task

#### Scenario: Contract revision is requested before preflight
- **WHEN** a revision-zero task receives a contract-revision request before its preflight record exists
- **THEN** the controller rejects the request, preserves revision zero and the original contract, and continues to project preflight as the first mutation

#### Scenario: Task resumes after a contract revision
- **WHEN** a new controller loads a task whose contract was revised
- **THEN** replay derives the same effective contract and retains the original and intermediate contracts

### Requirement: Decisions and waivers are explicit post-preflight records
The controller SHALL accept decisions and waivers only after preflight has committed as the task's first record. It SHALL then append decisions with a task-unique stable decision ID, kind, subject, outcome, rationale, actor label, timestamp, and the effective contract revision and digest. `(task_id, decision_id)` SHALL be the global decision identity, and a decision ID SHALL never be reused within its task ledger. A `(kind, subject)` pair SHALL occur at most once within one contract digest; correction requires a later contract revision and a new decision ID. A criterion waiver SHALL use kind `criterion-waiver`, subject equal to one acceptance-criterion ID, and outcome `waived`. A review waiver SHALL use kind `assurance-waiver`, subject equal to one review node ID, and outcome `waived`. Every waiver SHALL become stale when its contract digest changes.

#### Scenario: Criterion waiver is recorded
- **WHEN** an explicit waiver decision references a criterion in the effective contract
- **THEN** the decision is appended and terminal coverage may classify that criterion as waived

#### Scenario: Decision is requested before preflight
- **WHEN** a revision-zero task receives any decision or waiver request before its preflight record exists
- **THEN** the controller rejects the request, preserves the empty ledger and revision zero, and continues to project preflight as the first mutation

#### Scenario: Agent evidence claims a waiver
- **WHEN** verification output directly classifies a criterion as waived without a current waiver decision
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

#### Scenario: Decisions replay after restart
- **WHEN** a controller restarts after criterion and review-waiver decisions were recorded
- **THEN** replay derives the same unique applicable decisions and rejects any duplicate or conflicting ledger history as invalid state

### Requirement: Contract and decision mutations preserve workflow authority
Contract revisions and decisions SHALL be controller mutations protected by the task lock, revision compare-and-swap, deterministic replay, terminal-state rejection, and bounded payload validation. A decision SHALL append exactly one record without changing the current workflow node. A contract revision SHALL append exactly one record and may change the node only to the workflow's declared revision target recorded in that same record. Neither mutation SHALL expose a second projected workflow action. Task creation SHALL be the explicit revision-zero initialization exception; it persists the original contract atomically and appends no record.

#### Scenario: Revised scope refreshes repository-backed planning
- **WHEN** a contract is revised after a repository-backed plan was recorded
- **THEN** the revision record binds the current workspace as a new-contract revision source, the workflow reenters its declared planning stage, old-contract artifacts remain historical, and a replacement plan consumes that revision source before implementation resumes

#### Scenario: Snapshot fails during contract revision
- **WHEN** a post-preflight contract revision cannot capture a stable safe bounded workspace snapshot
- **THEN** the revision fails without changing the effective contract, node, ledger, or assurance budget

#### Scenario: Concurrent decision loses the revision race
- **WHEN** another mutation commits before a decision or contract revision acquires the current revision
- **THEN** the losing mutation receives a revision conflict with the fresh projection and writes no partial record

#### Scenario: Terminal task receives a scope revision
- **WHEN** a caller attempts to revise a terminal task
- **THEN** the controller rejects the mutation and preserves the terminal state
