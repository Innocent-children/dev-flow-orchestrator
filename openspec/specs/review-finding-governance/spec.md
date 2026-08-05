# review-finding-governance Specification

## Purpose
TBD - created by archiving change introduce-task-scoped-adaptive-assurance. Update Purpose after archive.
## Requirements
### Requirement: Review findings carry strict causal provenance
Every review observation SHALL use `dev-flow-review-finding/0.3.0` and SHALL contain a task-unique stable finding ID, canonical fingerprint, severity, blocking flag, causal relation, criterion IDs, repository ID, bounded path, symbol, resource or integration label, evidence, smallest sufficient resolution, reviewer assurance, and the exact contract, assurance-plan, task-change-manifest, review-scope, guidance, and workspace digests inspected. `causal_relation` SHALL be exactly `introduced`, `affected`, `pre-existing`, `out-of-scope`, or `unknown`. One review execution SHALL contain at most 64 findings, subject also to the shared 64 KiB action payload and 8 KiB per-text limits; a 65th finding SHALL reject the complete review without truncation or a partial record. The controller SHALL validate shape, bounds, member and path identity, criterion references, input digests, and the canonical fingerprint before recording the review.

#### Scenario: Introduced defect is reported
- **WHEN** review identifies a defect in a task-owned changed path and binds it to the exact manifest entry and criterion
- **THEN** the controller records a current `introduced` finding with reproducible evidence

#### Scenario: Finding references an unknown member or path
- **WHEN** a finding names a repository outside immutable membership or an unsafe path
- **THEN** review application fails without advancing the task or recording a partial review

#### Scenario: Finding fingerprint is inconsistent
- **WHEN** any fingerprinted finding field differs from the canonical content used to derive its fingerprint
- **THEN** action validation rejects the finding

#### Scenario: Review input changes
- **WHEN** the contract, plan, task manifest, review scope, guidance, or workspace digest changes before review apply
- **THEN** the review binding is stale and none of its findings become current authority

#### Scenario: Review exceeds its finding bound
- **WHEN** one review execution supplies a 65th finding
- **THEN** the controller rejects the complete review without truncating findings, consuming review authority, or recording a partial outcome

### Requirement: Only current blocking causal findings request rework
A review finding SHALL schedule task rework only when it is current, `blocking: true`, and has causal relation `introduced` or `affected` within the current assurance plan's impact closure. Severity, blocking status, causality, and assurance effect SHALL all remain explicit; severity alone SHALL NOT schedule rework. A pre-existing or out-of-scope finding SHALL remain an adjacent observation unless a current operator disposition and contract revision make it accepted task scope. A `blocking: false` unknown finding SHALL remain advisory. A `blocking: true` unknown finding SHALL NOT schedule source rework, but SHALL leave the review obligation unresolved in `triage-required` until bounded causal refresh establishes another relation or a current authorized disposition resolves it. The controller SHALL derive `approved`, `changes-requested`, `triage-required`, or `unavailable` from validated findings, applicable decisions, reviewer availability, and independence; a submitted contradictory top-level outcome SHALL be rejected.

#### Scenario: Current blocking introduced finding exists
- **WHEN** independent review records one current blocking `introduced` finding
- **THEN** the controller derives `changes-requested` and schedules rework for that finding within remaining plan allowance

#### Scenario: Review reports only non-blocking findings
- **WHEN** independent review is available, every current finding is non-blocking, and none proves an affected relation outside the current impact closure
- **THEN** the controller derives approval while retaining every finding in review evidence and the Dossier

#### Scenario: Blocking finding has unknown causality
- **WHEN** independent review records a current `blocking: true` finding whose task causality cannot yet be established
- **THEN** the controller derives `triage-required`, keeps the review obligation unresolved, and projects bounded causal refresh rather than approval or source rework

#### Scenario: High-severity pre-existing issue is reported
- **WHEN** review reports a high-severity issue whose causal relation is `pre-existing`
- **THEN** the issue remains visible but does not consume task rework or verification allowance

#### Scenario: Reviewer submits contradictory approval
- **WHEN** a review payload claims approval while containing an unresolved current blocking causal finding
- **THEN** the controller rejects the claimed outcome or derives `changes-requested` according to the current payload contract

#### Scenario: Reviewer approves despite unresolved causal triage
- **WHEN** a review payload claims approval while containing a current blocking unknown-causality finding without a governing disposition
- **THEN** the controller rejects the claimed outcome or derives `triage-required`

#### Scenario: Independent assurance is unavailable
- **WHEN** no independent reviewer produces a current result
- **THEN** the controller derives unavailable assurance and applies only an exact current assurance waiver authorized for that review obligation

### Requirement: Indirectly affected findings prove their task relation
An `affected` finding MAY identify a defect that manifests in an unchanged path, member, integration boundary, or runtime behavior. It SHALL also reference at least one task-owned manifest entry and bounded causal evidence demonstrating how that change directly or indirectly affects the finding location or criterion. The evidence SHALL use source confirmation and MAY include a call, data-flow, configuration, schema, dependency, or cross-repository path. Missing, stale, degraded-without-source-confirmation, or circular causal evidence SHALL classify the relation as `unknown` and SHALL NOT schedule rework. When valid evidence proves an affected relation outside the current impact closure, the finding SHALL record an `impact-gap`; the controller SHALL invalidate that impact evidence and plan and reenter bounded impact planning under the same contract and remaining absolute counters. Only a replacement plan whose closure includes the proven relation may turn the finding into a source-rework input. Contract revision SHALL be required only when accepted scope or criteria must change.

#### Scenario: Changed API breaks an unchanged client path
- **WHEN** review confirms that a task-owned API schema change reaches an unchanged client consumer and violates a current criterion
- **THEN** the controller accepts an `affected` finding bound to both the API manifest entry and the confirmed cross-repository evidence

#### Scenario: Unchanged file has no causal path
- **WHEN** review reports a problem in an unchanged file without a confirmed path from any task-owned manifest entry
- **THEN** the finding is `unknown`, `pre-existing`, or `out-of-scope` and cannot request rework

#### Scenario: Graph evidence is stale
- **WHEN** an affected finding relies on a stale graph generation and has no direct source confirmation
- **THEN** the relation remains `unknown`, the limitation is recorded, and a blocking finding keeps the review obligation in causal triage

#### Scenario: Review proves an effect outside the current closure
- **WHEN** current source evidence proves that a task-owned change affects a location or criterion omitted from the governing impact closure
- **THEN** the controller records an impact gap, invalidates the plan, and reenters bounded impact planning without scheduling rework from the stale plan or requiring contract expansion by default

### Requirement: Non-causal observations remain reportable without scheduling rework
Independent and self review MAY record pre-existing, out-of-scope, unknown-causal, advisory, or otherwise non-rework observations. Each observation SHALL retain its evidence, severity, blocking flag, limitations, and proposed follow-up. Pre-existing, out-of-scope, and `blocking: false` unknown observations SHALL NOT alter the accepted contract, task change manifest, required assurance obligations, budgets, workflow node, or completion outcome by themselves. A `blocking: true` unknown observation SHALL alter only the governed review state to bounded causal triage; it SHALL NOT become task source scope or consume source-rework authority without current causal evidence or an authorized disposition. The Dossier SHALL distinguish task-rework findings, triage-required findings, resolved findings, accepted risks, and adjacent observations.

#### Scenario: Reviewer notices unrelated cleanup
- **WHEN** review identifies maintainability work outside the current task change and impact closure
- **THEN** it records an out-of-scope observation and the controller does not project review rework

#### Scenario: Adjacent observation is retained at completion
- **WHEN** all required task assurance succeeds while a non-causal observation remains
- **THEN** the task may reach `DONE` and the Dossier reports that observation as non-blocking follow-up

#### Scenario: Blocking unknown observation remains unresolved
- **WHEN** all other assurance succeeds but one current blocking unknown-causality finding has neither completed triage nor a valid disposition
- **THEN** the review obligation remains unresolved and the task cannot reach `DONE`

#### Scenario: Observation attempts to expand scope
- **WHEN** review output marks an out-of-scope observation as implementation scope without a contract revision
- **THEN** the controller preserves current scope and rejects any resulting source obligation

### Requirement: Finding dispositions are explicit and replayable
Only the user or another actor with explicit task authority MAY record a `finding-disposition` decision for an exact current finding fingerprint. `accepted-risk` SHALL make one current blocking causal or unresolved-causality finding non-blocking while retaining its evidence, uncertainty, risk, and rationale. `confirmed-out-of-scope` SHALL preserve one finding as an adjacent observation. `expand-contract` SHALL be accepted only with an atomic complete next contract revision, new revision source, roll-forward manifest reconciliation, and planning reentry. Every disposition SHALL bind its contract, review, finding, and plan digests, become historical when any binding changes, and replay deterministically.

#### Scenario: User accepts finding risk
- **WHEN** the user records `accepted-risk` with rationale for a current blocking finding
- **THEN** that finding no longer schedules rework under the same contract and remains explicit in terminal risk reporting

#### Scenario: User confirms finding is outside scope
- **WHEN** the user records `confirmed-out-of-scope` for a current finding
- **THEN** the controller keeps it as an observation and does not consume a rework attempt

#### Scenario: User expands accepted scope
- **WHEN** the user records `expand-contract` with a complete next contract
- **THEN** one atomic mutation revises scope, records the finding authority, establishes a new source interval, preserves inherited and adopted task-owned entries, and requires a replacement assurance plan

#### Scenario: Agent attempts to self-authorize disposition
- **WHEN** review or implementation payload embeds an unrecorded risk acceptance or scope disposition
- **THEN** the controller rejects that claimed authority

#### Scenario: Disposition replays after restart
- **WHEN** a controller reloads a task containing a valid current finding disposition
- **THEN** it derives the same blocking state, assurance obligations, budget use, and Dossier classification
