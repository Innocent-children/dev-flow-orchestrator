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
The controller SHALL accept contract revision only after preflight has committed as the task's first record. Callers SHALL supply any different initial scope through the structured contract at creation, and later revision SHALL NOT add, remove, replace, relocate, or reorder the immutable repository set. The controller SHALL append every accepted later contract revision using current typed record fields and payload, including previous and new contract digests, reason, actor label, timestamp, monotonically increasing contract revision, deterministic workflow reentry, and any exact finding fingerprint that required scope expansion. Revision SHALL first capture one safe stable repository-set snapshot and SHALL establish it as the new contract's `revision-source`, subsequent source-interval anchor, and input to a replacement assurance plan. It SHALL simultaneously reconcile a roll-forward current task-change manifest that carries every still-material prior task-owned entry, adds every exactly claimed ambient path authorized for adoption, preserves original producer or adoption lineage, records current after identities, and maps every current entry to the replacement contract's criteria. The immutable preflight ownership origin SHALL NOT be replaced. No member observation or manifest subset SHALL commit separately. This SHALL be the only cross-contract source bridge; prior generation-local manifests, plans, findings, dispositions, and assurance attempts remain historical, while their still-material task-owned entries remain current assurance scope. Each current workflow SHALL declare its contract-revision target. Official planning workflows SHALL return revised scope to impact and planning, and `lite` SHALL return to bounded impact and implementation-plan derivation. Repository membership remains immutable.

#### Scenario: Scope revision is accepted
- **WHEN** a non-terminal task records a valid replacement contract whose revision is exactly one greater than the effective contract
- **THEN** one contract-revision record is appended, the current node follows the definition's revision target, and subsequent planning binds the new contract and revision-source digests

#### Scenario: Repository-set scope revision is accepted
- **WHEN** a scope revision captures every member safely and stably
- **THEN** the same contract-revision record establishes the aggregate revision source, rolls the complete current task-owned manifest into the new source interval, and binds subsequent actions to the new contract and repository-set digests

#### Scenario: Repository-set revision reenters planning
- **WHEN** scope is revised after repository-backed plans exist in multiple members
- **THEN** the aggregate revision source becomes the required cross-contract predecessor and replacement impact and assurance planning consume its roll-forward manifest before implementation resumes

#### Scenario: Revision establishes a new source interval without erasing ownership
- **WHEN** a valid revision captures every member safely and stably
- **THEN** the same record establishes the aggregate revision source, carries all still-material owned entries into the replacement manifest, adopts every exactly authorized drift entry, and retains the immutable preflight ownership origin

#### Scenario: Revision regenerates assurance
- **WHEN** revised scope changes criteria, impact, risk, or an accepted finding's implementation scope
- **THEN** the workflow requires a replacement assurance plan over the complete roll-forward manifest and excludes every prior-contract obligation result from current completion

#### Scenario: Revision would drop an existing task change
- **WHEN** a replacement contract or reconciliation omits, incompatibly remaps, or changes the identity of a still-material task-owned entry
- **THEN** revision fails atomically and the previous contract, current manifest, source authority, plan, and budgets remain unchanged

#### Scenario: One member changes during revision capture
- **WHEN** any member becomes unavailable, unsafe, over budget, or unstable during aggregate revision capture
- **THEN** revision fails without changing the contract, node, ledger, repository set, manifest, plan, or budgets

#### Scenario: Revision attempts to change repository membership
- **WHEN** a replacement contract proposes adding, removing, replacing, or reordering a member
- **THEN** the controller rejects the request and requires a new task for the different repository set

#### Scenario: Revision skips a contract version
- **WHEN** a replacement contract does not advance the effective contract revision by exactly one
- **THEN** revision fails without advancing the task

#### Scenario: Contract revision is requested before preflight
- **WHEN** a revision-zero task receives a contract-revision request before its complete preflight record exists
- **THEN** the controller rejects the request and continues to project preflight as the first mutation

#### Scenario: Task resumes after a contract revision
- **WHEN** a new controller loads a revised task
- **THEN** replay derives the same effective contract, revision source, immutable ownership origin, roll-forward manifest, planning reentry, and historical prior-contract evidence

### Requirement: Decisions and waivers are explicit post-preflight records
The controller SHALL accept decisions, waivers, and review-finding dispositions only after complete preflight has committed. Every decision SHALL have a task-unique stable decision ID, kind, subject, outcome, rationale, actor label, timestamp, and effective contract revision and digest. `(task_id, decision_id)` SHALL be globally unique, and a `(kind, subject)` pair SHALL occur at most once within one contract digest. A `criterion-waiver` SHALL target one exact criterion. An `assurance-waiver` SHALL target one exact review obligation or node and SHALL waive only unavailable independence, never verification or a blocking causal finding. A `finding-disposition` SHALL use the current structured finding fingerprint as subject and SHALL use `accepted-risk`, `confirmed-out-of-scope`, or `expand-contract` as outcome. `accepted-risk` MAY resolve a current blocking causal finding or a current blocking finding whose causality remains unknown, whether before or after the optional bounded triage route, but it SHALL preserve the evidence, uncertainty, and remaining risk. Dispositions SHALL remain bound to that finding, review fingerprint, assurance plan, and contract digest and SHALL become historical when any binding changes. A disposition SHALL NOT fabricate proof, relabel self-review as independent, alter repository membership, or silently change accepted scope.

#### Scenario: Criterion waiver is recorded
- **WHEN** an explicit waiver references a criterion in the effective contract
- **THEN** only that criterion may be classified as waived and the rationale remains in the Dossier

#### Scenario: Finding risk is accepted
- **WHEN** the user records `accepted-risk` for a current blocking causal finding
- **THEN** that finding no longer schedules rework under the current contract while remaining visible as accepted risk

#### Scenario: Finding is confirmed outside scope
- **WHEN** the user records `confirmed-out-of-scope` for a current finding after inspecting its causal evidence
- **THEN** the finding remains an observation and does not become task implementation scope or assurance completion proof

#### Scenario: Finding expands the contract
- **WHEN** the user selects `expand-contract` and supplies a complete next contract revision
- **THEN** one authorized mutation records the finding-bound scope decision and replacement contract, establishes a new revision source, rolls inherited and adopted changes into the current manifest, and reenters impact planning

#### Scenario: User accepts unresolved causal risk
- **WHEN** bounded triage cannot resolve a current blocking unknown-causality finding and the user records `accepted-risk` with its uncertainty and rationale
- **THEN** the finding no longer blocks the review obligation under that contract but remains visible as accepted uncertain risk and supplies no missing criterion proof

#### Scenario: Disposition targets stale finding evidence
- **WHEN** a finding, review fingerprint, plan digest, or contract digest no longer matches the disposition request
- **THEN** the controller rejects the decision without changing the task

#### Scenario: Decision is requested before preflight
- **WHEN** a revision-zero task receives any decision request
- **THEN** the controller rejects it and continues to project preflight

#### Scenario: Agent evidence claims a waiver or disposition
- **WHEN** verification or review output directly claims a criterion waiver, assurance waiver, risk acceptance, or scope disposition
- **THEN** action validation rejects that claimed authority unless a current controller decision record supplies it

#### Scenario: Agent evidence claims a waiver
- **WHEN** repository or integration verification output directly classifies a criterion as waived without a current waiver decision
- **THEN** the action fails without advancing the task

#### Scenario: Contract changes after a decision
- **WHEN** the contract is revised after a waiver or finding disposition
- **THEN** the earlier decision remains historical and is excluded from current coverage and routing

#### Scenario: Contract changes after a waiver
- **WHEN** the contract is revised after a waiver was recorded
- **THEN** the earlier waiver remains historical and is excluded from current acceptance coverage

#### Scenario: Decision ID is reused in a task
- **WHEN** a decision attempts to reuse any earlier decision ID in the same task
- **THEN** the mutation is rejected without appending a record

#### Scenario: Conflicting decision targets the same subject
- **WHEN** a second decision uses the same kind and subject under the same contract digest
- **THEN** the mutation is rejected and correction requires a contract revision plus a new decision ID

#### Scenario: Decision attempts to add repository membership
- **WHEN** a decision payload attempts to change the immutable repository set
- **THEN** exact payload validation rejects it without changing the ledger or current action

#### Scenario: Decisions replay after restart
- **WHEN** a controller restarts after waivers and finding dispositions were recorded
- **THEN** replay derives the same applicable authorities and rejects duplicate or contradictory history

### Requirement: Contract and decision mutations preserve workflow authority
Contract revisions and decisions SHALL be controller mutations protected by the task lock, revision compare-and-swap, deterministic replay, terminal-state rejection, bounded payload validation, immutable repository-set validation, and current task-change and assurance bindings. A simple decision SHALL append exactly one current-shape record without changing the workflow node. A contract revision SHALL append exactly one record and may change the node only to the workflow's declared revision target. A finding-bound `expand-contract` mutation SHALL atomically contain the authorized disposition, complete replacement contract, aggregate revision source, roll-forward manifest reconciliation, and recorded planning reentry; it SHALL NOT expose an intermediate state in which scope changed without a new source boundary or in which existing task-owned bytes disappear from current assurance scope. Task creation remains the revision-zero exception with no ledger record. Unsupported task, workflow, snapshot, manifest, plan, finding, projection, record, artifact, or binding identities SHALL fail closed without reinterpretation.

#### Scenario: Revised scope refreshes planning and assurance
- **WHEN** a contract revision is accepted after repository-backed planning and assurance evidence exist
- **THEN** the revision record establishes the new source interval, complete roll-forward manifest, planning reentry, and requirement for a replacement assurance plan while retaining old evidence historically

#### Scenario: Revised scope refreshes repository-backed planning
- **WHEN** a contract is revised after repository-backed plans were recorded in one or more members
- **THEN** the revision record binds the complete aggregate workspace as the new source interval, rolls forward the current task-owned manifest, and requires replacement impact and assurance planning before implementation resumes

#### Scenario: Snapshot fails during contract revision
- **WHEN** revision cannot capture a stable safe complete repository-set snapshot
- **THEN** it fails without changing the contract, node, ledger, manifest, plan, membership, lease, or budget

#### Scenario: Concurrent decision loses the revision race
- **WHEN** another mutation commits before a decision or revision acquires the expected task revision
- **THEN** the losing mutation receives a revision conflict with the fresh single-action projection and writes no partial record

#### Scenario: Terminal task receives a scope revision
- **WHEN** a caller attempts to revise a terminal task
- **THEN** the controller rejects the mutation and preserves the terminal state, released lease, and Dossier

#### Scenario: Finding expansion is interrupted
- **WHEN** validation of any finding, contract, snapshot, or planning-reentry field fails during `expand-contract`
- **THEN** no decision, contract revision, snapshot, manifest, budget, or workflow transition is committed

#### Scenario: Current decision history loads
- **WHEN** a task contains valid current-schema revisions and decisions
- **THEN** replay preserves every record and derives the same current contract, finding dispositions, ownership boundary, and assurance authority
