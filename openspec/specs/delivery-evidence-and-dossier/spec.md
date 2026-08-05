# delivery-evidence-and-dossier Specification

## Purpose
TBD - created by archiving change complete-personal-delivery. Update Purpose after archive.
## Requirements
### Requirement: Every post-creation mutation appends one typed replay record
Task creation SHALL atomically persist revision-zero initialization state containing the original contract, the immutable canonical repository tuple, and no records. Every later successful task mutation SHALL append exactly one immutable record and increment the task revision exactly once, preserving `task revision == record count`. Records SHALL identify their current schema, kind, record ID, committed revision, timestamp, producer, payload, effective contract revision and digest, and workflow transition when applicable. Preflight, workflow actions, contract revisions, decisions, and cancellation SHALL use the same replay ledger. Every repository-backed action, cancellation, or contract-revision record SHALL place one validated repository-set snapshot in its `snapshot` field, including for a one-member set; no member observation SHALL be committed separately. Decision records SHALL retain `snapshot: null`, `artifact: null`, and `binding: null` and derive repository scope only from immutable task membership. Unsupported record or embedded snapshot identities SHALL fail closed without migration or fallback.

#### Scenario: Task is created
- **WHEN** a valid task and repository set are initialized
- **THEN** it has task revision zero, an immutable original contract and repository tuple, and an empty record ledger

#### Scenario: Preflight commits
- **WHEN** bounded repository inspection succeeds for every member of a new task
- **THEN** revision one contains one preflight action record and replay advances from the workflow entry

#### Scenario: Stored record is tampered
- **WHEN** a record ID, payload, transition, digest, baseline, input reference, nested member snapshot, or aggregate digest no longer matches its canonical content or workflow contract
- **THEN** direct task loading fails closed as invalid state

#### Scenario: Mutation tries to rewrite history
- **WHEN** a candidate state changes, removes, or reorders a prior record
- **THEN** store validation rejects the write before atomic replacement

#### Scenario: Member capture fails
- **WHEN** any member fails before the complete repository-set snapshot is accepted
- **THEN** no record or partial member evidence is committed

#### Scenario: Decision is recorded for any supported repository-set size
- **WHEN** a valid decision is appended to a task
- **THEN** its record has `snapshot: null`, `artifact: null`, and `binding: null`, and replay derives the task scope only from immutable `TaskState.repositories`

### Requirement: Artifacts carry authoritative provenance and typed lineage
A typed artifact record SHALL include artifact type and schema, canonical digest, producer action and node, action attempt, task revision, effective contract revision and digest, declared workspace role, observed content-sensitive repository-set snapshot, immutable preflight ownership-origin ID and digest, the applicable contract-revision `revision-source` interval anchor when one exists, current canonical roll-forward task-change-manifest ID and digest, the artifact's controller-derived task-change slice and slice digest, current assurance-plan and obligation fingerprints when applicable, and resolved upstream artifact record IDs, digests, edge kinds, and slice relations. The current workflow schema SHALL declare each artifact stage as `context`, `produces-source`, or `verifies-source` and each input edge as `governing`, `source-predecessor`, or `causal`. A governing edge SHALL track the latest current artifact or governing obligation input for the slice it governs. A source-predecessor edge SHALL pin the current source manifest and source observation consumed by an intentional source-producing action within the applicable preflight- or revision-anchored interval, without rebasing task ownership. A causal edge SHALL retain the exact finding, failed assurance, disposition, or other reason for rework without treating addressed failed assurance as current completion proof. Artifact provenance fields SHALL be calculated by the controller and engine rather than trusted from agent payload.

Every artifact's `snapshot` field SHALL contain the complete validated `dev-flow-repository-set-snapshot/0.3.0` for the current product model, including worktree and staged-index identity. Repository-set identity and complete scope SHALL be derived from immutable task membership and the embedded snapshot rather than copied into record, binding, or input fields. Source-producing lineage SHALL connect one aggregate predecessor to one aggregate successor and one prior task-change manifest to its controller-derived successor. Across a contract revision, that successor lineage SHALL preserve the immutable preflight ownership origin, the revision-source interval anchor, all still-material inherited task entries, every exactly adopted drift entry, and every later task entry. Context and verification lineage SHALL retain the same typed edge semantics for every supported repository-set size while permitting current evidence to bind only the obligation slice it proves. No agent-supplied manifest, slice, causal relation, finding resolution, or reuse claim SHALL replace controller-derived provenance.

Every current artifact, embedded value, action input, and replayed record handled by this capability SHALL use the exact `0.3.0` product schemas. An explicitly supplied non-`0.3.0` value inside the current namespace SHALL be rejected without appending a record. Retained `0.2.0` namespace bytes are outside this capability's product boundary: the `0.3.0` runtime SHALL NOT discover, enumerate, read, load, replay, migrate, translate, repair, rewrite, or delete them.

#### Scenario: Artifact is produced from declared inputs
- **WHEN** a workflow action declares required input artifact types and current inputs exist
- **THEN** the new artifact records the latest current input IDs and digests, binds the complete current repository-set snapshot and task-change manifest, and identifies the exact slices and obligations it consumes or proves

#### Scenario: Required input is missing
- **WHEN** an action requires an artifact, assurance obligation, manifest slice, or finding input with no current producer record
- **THEN** the action fails without advancing the task

#### Scenario: Rework consumes a failed review causally
- **WHEN** a source-producing rework action pins one or more current blocking `introduced` or `affected` finding fingerprints as causal inputs and the current manifest as its source predecessor
- **THEN** the successor records those exact reasons and its resulting manifest delta, and later replacement or closure of the review evidence does not invalidate the addressed rework artifact

#### Scenario: Agent payload contradicts provenance
- **WHEN** submitted content attempts to supply authoritative baseline, task revision, producer, contract, snapshot, task-change manifest, slice, causal relation, reuse status, or digest values
- **THEN** those fields are rejected or ignored in favor of controller-derived provenance

#### Scenario: Source action changes two members
- **WHEN** one implementation action changes task-owned API and client paths in two worktrees
- **THEN** its one artifact records one aggregate successor, one canonical manifest successor, and repository-scoped slice entries for both members

#### Scenario: Evidence proves one slice
- **WHEN** verification proves one obligation bound to a subset of the current task-change manifest
- **THEN** its artifact retains the complete snapshot for replay while its evidence authority and freshness are limited to the declared obligation slice

#### Scenario: Current input uses a non-current schema
- **WHEN** an apply, replay, or finalization input presented inside the current namespace uses a schema other than the exact `0.3.0` schema required at that position
- **THEN** validation rejects the input without translation, repair, fallback, or a new record

#### Scenario: Retained prior-version evidence exists
- **WHEN** retained `0.2.0` task, artifact, evidence, or Dossier bytes remain in the prior-version namespace
- **THEN** the `0.3.0` runtime does not discover, enumerate, read, load, replay, migrate, translate, repair, rewrite, or delete those bytes

### Requirement: Repository-backed artifacts bind declared resources
A stage that creates or updates repository-backed planning artifacts SHALL use the `produces-source` workspace role and a source-predecessor binding. Its payload MAY declare bounded repository-relative resource paths and `governing` or `reported` roles; the controller SHALL validate containment and calculate each content digest through the safe snapshot boundary. Governing resource digests SHALL participate in freshness even when the files are otherwise clean in Git. Reported resources SHALL remain provenance without governing plan validity. An OpenSpec `tasks.md` resource SHALL record its full raw digest as reported provenance and a governing semantic digest calculated by canonicalizing only Markdown task-list checkbox markers `- [ ]`, `- [x]`, and `- [X]` to `- [ ]` before hashing; every other byte, including task text, order, and test obligations, SHALL remain governing.

Every repository-backed resource SHALL resolve through an immutable task member and be identified by `(repository_id, path, role, normalizer)`. `repository_id` SHALL be explicit even when the set has one member. Unknown or omitted IDs, unsafe relative paths, cross-root resolution, and duplicate scoped keys SHALL be rejected. Equal relative paths in different members SHALL remain distinct.

#### Scenario: OpenSpec planning creates repository files
- **WHEN** an OpenSpec planning action creates proposal, design, spec, and task files from its pinned source predecessor
- **THEN** apply records a successor source snapshot plus authoritative repository-scoped paths and digests, with proposal, design, and spec resources governing plan freshness

#### Scenario: Implementation changes unrelated code
- **WHEN** a later implementation consumes the current repository-backed plan and changes files outside its governing resource paths
- **THEN** the plan remains current through source lineage and its unchanged governing resource digests

#### Scenario: Implementation changes a bound spec path
- **WHEN** a later source action changes or deletes a governing spec resource without producing a replacement plan artifact
- **THEN** the plan and governing descendants become stale even though the later source snapshot was recorded

#### Scenario: Plan is intentionally revised
- **WHEN** contract revision reenters planning and a new repository-backed planning action replaces the earlier plan and resource bindings
- **THEN** the new plan becomes current and later actions bind to its new artifact and governing resource digests

#### Scenario: OpenSpec task checkbox advances
- **WHEN** only task-list checkbox markers change in the bound `tasks.md`
- **THEN** the raw reported digest changes while the governing semantic digest and plan freshness remain unchanged

#### Scenario: OpenSpec task obligation changes
- **WHEN** task text, ordering, required test work, or any non-checkbox byte changes in the bound `tasks.md`
- **THEN** the governing semantic digest changes and the plan plus governing descendants become stale until a replacement plan is recorded

#### Scenario: Equal paths exist in two members
- **WHEN** API and client both bind `openspec/tasks.md`
- **THEN** their resources remain distinct by repository ID and are read only under their declared roots

#### Scenario: Repository-backed resource omits its ID
- **WHEN** an action submits a repository-backed resource path without `repository_id`
- **THEN** apply rejects it without selecting a default member

#### Scenario: Resource escapes its member
- **WHEN** a resource path traverses outside its declared root
- **THEN** containment validation rejects it without reading the target

### Requirement: Repository snapshots are content-sensitive and bounded
The Git boundary SHALL calculate a read-only workspace digest from `HEAD`, repository status, and canonical worktree and staged-index entries for every changed, untracked, or declared resource path. For every relevant path it SHALL bind the complete ordered `git ls-files --stage` entry set for stages zero through three. A regular file or symbolic link index entry SHALL bind its staged mode, blob object ID, and stage, thereby binding the staged blob content independently of the worktree observation; a gitlink SHALL bind its staged mode, object ID, and stage. Worktree observation and staged-index observation SHALL be distinct canonical fields so staged and unstaged content cannot alias. The boundary SHALL validate repository-relative paths and parent containment. It SHALL use `lstat`, open worktree regular files without following the final path, compare file identity metadata before and after the bounded read, and hash path, mode, and content. It SHALL hash worktree symbolic-link target bytes without following the link. It SHALL hash a clean initialized gitlink as path, worktree mode, staged object ID, and current submodule `HEAD` without recursive content traversal; missing or dirty gitlinks SHALL fail. Git object IDs SHALL be validated for the repository's object format, and repeated index and worktree enumeration SHALL prove stability. Unsupported special files SHALL fail before read. Each repository observation SHALL contain at most 4,096 bounded snapshot paths and at most 12,288 raw index stage entries, and its index-enumeration command output SHALL contain at most 2 MiB; the existing 1 MiB output limit for every other Git command remains unchanged. Snapshot collection SHALL also apply the existing explicit time, path-byte, index-entry-byte, per-file, and total-content budgets. No count or byte limit permits truncation. Any containment violation, invalid or substituted index entry, replacement race, unstable worktree or index enumeration, unsupported type, truncation, or budget breach SHALL fail without recording evidence. Unmerged stages SHALL remain available for read-only diagnosis but SHALL block source successors, assurance records, and successful finalization.

For every task, a `dev-flow-repository-set-snapshot/0.3.0` SHALL contain the derived set identity and each complete member `dev-flow-workspace-snapshot/0.3.0` in canonical order, and its aggregate digest SHALL cover the complete wrapper excluding its own digest. Each member digest SHALL cover both its worktree observation and staged-index observation. The wrapper SHALL exactly match `TaskState.repositories`, including a one-member tuple. The controller SHALL compare two complete observations before mutation. Any member identity mismatch, disappearance, index or worktree instability, or complete-set mismatch SHALL fail without recording aggregate or partial evidence.

#### Scenario: Modified file changes again
- **WHEN** a tracked modified file changes worktree content while retaining the same porcelain status entry and staged content
- **THEN** the member workspace digest and aggregate digest change, and evidence whose bound task slice includes that worktree content becomes stale

#### Scenario: Untracked input changes
- **WHEN** an untracked non-ignored file included in a member workspace changes content
- **THEN** the member workspace digest and aggregate digest change

#### Scenario: Staged blob changes under the same status shape
- **WHEN** a regular file or symbolic link is restaged with different index content while its porcelain status shape remains unchanged
- **THEN** the staged object or blob field, member digest, and aggregate digest change and any binding or evidence covering that staged slice becomes stale

#### Scenario: Snapshot exceeds its budget
- **WHEN** changed worktree content, staged index entries, or untracked content in any member exceeds a declared snapshot budget or changes during collection
- **THEN** complete snapshot collection fails explicitly and the task does not advance with unverifiable or partial evidence

#### Scenario: Snapshot exceeds an index-aware count or output bound
- **WHEN** one repository observation would contain a 4,097th bounded path, a 12,289th raw index stage entry, or index-enumeration command output larger than 2 MiB
- **THEN** complete repository-set capture fails without truncation, partial evidence, or a task mutation

#### Scenario: Changed symbolic link points outside the repository
- **WHEN** a changed or untracked symbolic link targets a path outside its member repository
- **THEN** the snapshot hashes the worktree link-target bytes without opening the target and binds the staged symbolic-link blob object ID through the index entry set

#### Scenario: Gitlink is present
- **WHEN** a changed gitlink names an initialized clean submodule
- **THEN** the member snapshot hashes its staged gitlink object ID and current submodule `HEAD` without recursing; a missing, dirty, or unstable submodule fails explicitly

#### Scenario: Special file is untracked
- **WHEN** Git enumeration returns a FIFO, socket, device, or another unsupported filesystem type
- **THEN** snapshot collection rejects the entry without opening or blocking on it

#### Scenario: Path is replaced during collection
- **WHEN** a file, link, parent path, worktree path list, index entry, staged object, or earlier member observation changes while snapshot collection is in progress
- **THEN** identity or repeated-observation checks fail and no task record is committed

#### Scenario: Set membership is forged
- **WHEN** a repository-set wrapper omits, adds, reorders, or misidentifies a member
- **THEN** snapshot validation rejects it against immutable task membership

### Requirement: Action bindings close the source-transition interval
Before work begins, the projection SHALL resolve a canonical `dev-flow-action-binding/0.3.0` containing task revision, action and node IDs, effective contract and assurance-plan digests, current obligation ID and fingerprint when applicable, every pinned input record ID, digest, edge kind, and slice relation, the source predecessor and task-change-manifest predecessor when declared, the bound task-change slice, and the starting complete repository-set snapshot digest including staged-index identity. Apply SHALL require the exact binding, verify its canonical digest, and compare-and-swap the task revision, contract, plan, current node, action, obligation, pinned ledger records, manifest predecessor, and complete snapshot. A `context` or `verifies-source` action SHALL require its apply-time complete snapshot to equal the starting snapshot. A `produces-source` action MAY observe a changed apply-time worktree or index and SHALL atomically derive and record its manifest and snapshot successor after the binding passes. A stale or contradictory binding SHALL fail without appending a record.

`starting_snapshot_digest` SHALL always be the repository-set aggregate digest and apply SHALL validate a complete current repository-set snapshot. Context and verifies-source equality SHALL apply to the complete aggregate to detect unresolved drift during the action interval, while evidence authority and later freshness SHALL be evaluated against the bound task-change slice. A produces-source action MAY produce a different aggregate snapshot only after its bound aggregate and manifest predecessors remain authoritative and every changed path is classified through the task-owned change-capsule rules.

#### Scenario: Documentation starts from current implementation
- **WHEN** `next` pins the current implementation, manifest `M1`, and aggregate workspace `W1`, documentation intentionally changes a task-owned path to produce `M2` and `W2`, and apply receives the unchanged action binding
- **THEN** apply accepts the pinned predecessors and atomically records documentation with controller-derived manifest and snapshot successors

#### Scenario: Task advances after binding is projected
- **WHEN** a decision, contract revision, manifest disposition, or workflow action commits after an action binding was issued
- **THEN** apply rejects the earlier binding by revision CAS, returns a fresh projection when current repositories can be captured, and records no successor

#### Scenario: Read-only stage changes source
- **WHEN** a context or source-verification action applies after any member's worktree or staged index differs from its bound starting snapshot
- **THEN** apply rejects the action because that stage lacks source-producing authority and reports the changed member and path when derivable

#### Scenario: Verification starts from a current task slice
- **WHEN** repository-set verification is projected for one obligation against manifest `M1`, slice `S1`, and aggregate snapshot `W1`
- **THEN** apply succeeds only while the complete action binding remains stable and records evidence whose authority is limited to `S1`

#### Scenario: Verification starts from current aggregate source
- **WHEN** repository-set verification is projected against aggregate snapshot `W1`
- **THEN** apply succeeds only while every member still matches `W1`

#### Scenario: Source action changes one or more members
- **WHEN** implementation uses its unchanged repository-set and manifest binding and produces stable aggregate snapshot `W2`
- **THEN** one record derives manifest successor `M2`, classifies every changed member path, and replaces `W1` with `W2` as the complete observed workspace authority

#### Scenario: Binding uses a non-current snapshot or manifest digest
- **WHEN** a binding references a bare member snapshot, an earlier task-change manifest, a mismatched obligation slice, or another unsupported dialect
- **THEN** replay rejects the state without translating or repairing the binding

#### Scenario: Binding uses a non-current snapshot digest
- **WHEN** a binding references a bare member snapshot or another unsupported snapshot dialect
- **THEN** replay rejects the state without translating or repairing the binding

#### Scenario: Staged content changes after projection
- **WHEN** a path is restaged after `next` without changing the apparent porcelain status shape
- **THEN** apply rejects the binding because its complete index-aware snapshot digest changed

### Requirement: Freshness is stage-sensitive and derived from typed inputs
Artifact and evidence freshness SHALL be derived without rewriting historical records. Every current artifact SHALL match the effective contract and current assurance plan. A governing edge SHALL continue to reference the latest current artifact or obligation input for the slice it governs, so replacement invalidates only descendants whose governing or declared impact closure intersects that slice. A source-predecessor edge SHALL keep the explicitly consumed source-manifest lineage eligible through the current successor. A causal edge SHALL require an intact contract-compatible referenced finding, disposition, or assurance record but SHALL not require addressed or superseded assurance to remain current completion proof. Every governing resource path SHALL still match its authoritative digest; reported resources SHALL not affect currentness. A `context` artifact SHALL remain current across later source-producing stages when its governing slice is unaffected. A `verifies-source` artifact SHALL bind its obligation fingerprint, task-change-manifest digest, slice digest, governing inputs, and impact closure; it SHALL become stale only when one of those authorities changes or intersects a later manifest delta. Stale records SHALL retain their content and structured stale reasons and SHALL be excluded from obligations they no longer prove.

Source authority SHALL retain the complete index-aware repository-set snapshot for replay, while assurance freshness SHALL be evaluated per controller-derived task-change slice. Governing resources and slice entries SHALL be keyed by repository ID and path or symbol identity. Unclassified ambient drift SHALL block repository-dependent progress until the user restores the latest accepted source, accepts a complete contract revision that claims the drift, or cancels at an authorized stage; it SHALL NOT silently become task evidence or blanket-invalidate historical disjoint proof. A later valid source-producing record SHALL preserve earlier context, verification, or review evidence when the current assurance plan authorizes reuse and the obligation fingerprint, bound slice, governing inputs, criterion meaning, review guidance, and declared impact closure remain current. Stale reasons and reuse decisions SHALL identify affected obligation IDs, repository IDs, paths or symbols, manifest transitions, and governing inputs.

#### Scenario: Contract revision invalidates earlier proof
- **WHEN** the delivery contract changes after verification
- **THEN** the earlier verification remains visible and is excluded from current acceptance coverage because its effective contract and assurance plan no longer match

#### Scenario: Upstream plan is replaced
- **WHEN** a new current plan artifact supersedes the plan used by an implementation artifact
- **THEN** dependent artifacts and proof whose governing inputs or impact closure changed become stale while provably disjoint evidence remains eligible for declared reuse

#### Scenario: Repository has not changed
- **WHEN** contract or adopted obligation fingerprint, manifest slice, latest input references, governing resources, impact closure, and applicable index-aware member observations still match
- **THEN** the artifact remains current across controller restart

#### Scenario: Implementation consumes a plan and changes source
- **WHEN** a current implementation artifact explicitly consumes the latest current plan and records new task-change manifest and snapshot successors
- **THEN** the plan remains current where its governing resources match, the implementation becomes the latest source authority, and downstream obligations consume the new manifest slices

#### Scenario: Documentation changes source after implementation
- **WHEN** a documentation artifact consumes the current implementation and changes only a documentation slice
- **THEN** both artifacts remain current through lineage and only obligations whose slices or impact closure intersect the documentation change require new evidence

#### Scenario: Review rework changes source
- **WHEN** review rework causally consumes current blocking `introduced` or `affected` findings, pins the current manifest predecessor, and records a successor affecting bounded slices
- **THEN** the addressed findings remain historical lineage and only verification and review obligations invalidated by those successor slices become outstanding

#### Scenario: Source successor is eligible before commit
- **WHEN** a source-producing action has current bound snapshot and manifest predecessors but its intentional edits make the live workspace differ before apply
- **THEN** binding validation uses the pinned predecessors rather than re-resolving them against the changed workspace

#### Scenario: Source successor is current after commit
- **WHEN** the same bound source-producing action commits its snapshot and manifest successors
- **THEN** freshness follows the recorded predecessor edges, manifest delta, and affected slices while preserving eligible disjoint evidence

#### Scenario: Source changes outside a declared producer
- **WHEN** any present member differs from the latest complete snapshot and no source-producing record or ownership disposition classifies the drift
- **THEN** repository-dependent progress is blocked with repository and path diagnostics while historical task evidence retains its recorded freshness state and no ambient path is silently claimed

#### Scenario: Ambient drift is restored or adopted
- **WHEN** unclassified ambient drift blocks assurance and the user either restores the latest accepted source or completes a contract revision that claims every drift path
- **THEN** repository-dependent progress resumes from a complete current snapshot without silently excluding the drift through an evidence-only disposition

#### Scenario: Staged content in an evidence slice changes
- **WHEN** the staged blob or gitlink object for a path bound to current evidence changes
- **THEN** the affected slice digest changes and that evidence becomes stale even if the porcelain status text is unchanged

#### Scenario: One member is unavailable
- **WHEN** current state cannot be captured safely for one member
- **THEN** repository-dependent projection and final proof requiring that member are unavailable, while historical records and independently current evidence for other slices remain unchanged and inspectable

### Requirement: Acceptance coverage is explicit and authority-aware
Verification coverage SHALL use `dev-flow-verification-coverage/0.3.0` and SHALL report every effective acceptance criterion as `proven` or `unverified`; a current criterion waiver MAY derive `waived`. Coverage SHALL also identify the current assurance-plan digest and, for every criterion proof, the obligation ID and fingerprint, executed or reused evidence record, task-change-manifest and slice digests, governing inputs, impact closure, repository or integration target, command and result when executed, reuse authority when reused, and currentness. Successful delivery SHALL require every criterion to be proven or validly waived and every required assurance obligation to be satisfied, validly reused, or validly waived.

Coverage SHALL contain exact structured results for the repositories, paths or symbols, and integrations required by the current assurance plan rather than fabricating results for unaffected members. Each executed check's top-level command and pass aggregate SHALL agree with the exact repository and integration targets declared by that obligation. A command result that passes while its bound criterion remains unverified and unwaived SHALL be recorded as an unsuccessful obligation execution. One member or slice result SHALL NOT substitute for another, and member-local success SHALL NOT substitute for a required integration obligation. Dimensions omitted because policy establishes them as unnecessary SHALL appear as controller-derived `not-required` obligation states with their plan rationale; they SHALL NOT be agent-declared successes.

One assurance execution SHALL contain at most 64 canonical evidence items, subject also to the existing shared 64 KiB action-payload and 8 KiB per-text limits. A 65th item or any existing payload or text bound violation SHALL reject the complete result without truncation or a partial record. Reusing evidence by read-only controller derivation SHALL consume no verification, review, rework, or total-action unit. A separately persisted reuse decision, waiver, finding disposition, or prerequisite refresh SHALL consume exactly one total-action unit and no verification, review, or source-rework execution unit.

#### Scenario: All criteria are proven
- **WHEN** current executed or validly reused evidence proves every effective criterion and satisfies every required repository and integration obligation
- **THEN** completion coverage reports every criterion as proven and is eligible for successful finalization

#### Scenario: One criterion has a current waiver
- **WHEN** a current explicit waiver governs one effective criterion and all other criteria and required obligations are satisfied
- **THEN** completion coverage reports that criterion as waived and retains the waiver rationale and decision provenance

#### Scenario: Criterion remains unverified
- **WHEN** an exhausted path reaches incomplete finalization with an unverified criterion
- **THEN** the Dossier names the criterion, its outstanding obligations, consumed ceilings, and latest evidence, and the task cannot report a successful delivery outcome

#### Scenario: One required member result is absent
- **WHEN** criterion coverage appears complete but a current assurance obligation requires a repository or slice with no executed, reused, or waived result
- **THEN** apply rejects the malformed coverage without advancing the task

#### Scenario: One member result is absent
- **WHEN** criterion coverage is complete but one canonical repository ID has no current result
- **THEN** apply rejects the malformed coverage without advancing the task

#### Scenario: Unaffected member has no check obligation
- **WHEN** impact closure and policy establish that one canonical repository member is outside all current check obligations
- **THEN** coverage records that member's obligations as not required with plan provenance and does not require a fabricated command result

#### Scenario: Integration evidence fails
- **WHEN** every required member-local result passes but a required integration result fails
- **THEN** the integration obligation remains unsatisfied and its execution consumes the applicable absolute budget

#### Scenario: Integration evidence is not required
- **WHEN** the assurance plan establishes that no affected behavior crosses an integration boundary and policy does not otherwise require integration evidence
- **THEN** coverage reports the integration obligation as `not-required` with plan rationale and does not execute an integration command

#### Scenario: Commands pass while a criterion remains unverified
- **WHEN** every command for one obligation passes but one bound criterion remains unverified without a current waiver
- **THEN** the valid execution is recorded as unsuccessful assurance and the criterion obligation remains outstanding subject to the absolute ceilings

#### Scenario: Prior evidence is reused
- **WHEN** an obligation's fingerprint, manifest slice, governing inputs, criterion meaning, and impact closure remain current after a disjoint task change
- **THEN** coverage identifies the original evidence and reuse rule without charging a new verification, review, or rework execution, and a read-only reuse derivation consumes no total-action unit

#### Scenario: Reuse is persisted separately
- **WHEN** the controller appends a separate mutation to persist an authorized reuse decision instead of deriving reuse read-only
- **THEN** that mutation consumes exactly one total-action unit and no verification, review, or source-rework execution unit

#### Scenario: Governance prerequisite is persisted
- **WHEN** an authorized waiver, finding disposition, or prerequisite refresh is appended inside the assurance region
- **THEN** the mutation consumes exactly one total-action unit and no verification, review, or source-rework execution unit

#### Scenario: Evidence item limit is exceeded
- **WHEN** one assurance execution submits a 65th canonical evidence item
- **THEN** apply rejects the complete execution without truncation, a partial record, or allowance consumption

### Requirement: Delivery Dossier is generated from current records
Every non-cancelled official workflow SHALL finalize through the current typed Delivery Dossier generated by the pure domain layer. For every supported repository-set size, `dev-flow-delivery-dossier/0.3.0` SHALL contain the effective contract and scope; derived repository-set identity and canonical member inventory; the immutable index-aware preflight ownership origin; every contract-revision `revision-source` interval anchor; the final snapshot summary; every task-change-manifest version; the canonical current roll-forward manifest with all still-material inherited entries, exactly adopted drift entries, later task entries, and their producer, adoption, revision, and source-successor lineage; final owned path inventory and ambient-drift status; governing resources; current impact evidence, assurance plan, workflow profile, and risk derivation; every obligation and its exact `required`, `blocked`, `outstanding`, `satisfied`, `reused`, `not-required`, `waived`, or `exhausted` state, including every skipped non-required dimension and rule basis; per-obligation execution allowances and aggregate verification, review, rework, and total-action ceilings with consumed and remaining counts; `maximum_remaining_actions`; every verification execution and reuse link; structured review findings and reviewer fingerprints; finding causal, `triage-required`, `impact-gap`, dispute, disposition, resolution, replacement, and re-review lineage; structured repository and integration results; slice-aware freshness and stale reasons; documentation impact; current artifacts and provenance; remaining risks; decisions and waivers; delivery outcome; and handoff recommendation.

The Dossier SHALL expose whether any blocking unknown-causality finding still requires bounded causal refresh or authorized disposition, whether any proven affected relation still leaves an impact gap requiring replacement impact evidence and a replacement plan under the same contract, and whether every current obligation remains present and covered. It SHALL report separately persisted reuse, waiver, disposition, and prerequisite-refresh mutations as one total-action unit each without misclassifying them as verification, review, or rework executions. The initial plan SHALL reserve `review_ceiling × 64` total-action units for distinct finding dispositions, reject a duplicate current-contract disposition before mutation, and reject the plan before dispatch if the complete conservative route exceeds 256. Its referenced current manifest SHALL contain at most 4,096 entries, current impact report at most 128 entries, current assurance plan at most 64 obligations, each review at most 64 findings, each assurance execution at most 64 evidence items, and each effective contract at most 256 total actions. None of these limits, nor the existing shared payload and text limits, permits truncation.

`DONE` SHALL require fresh successful evidence for every current required obligation, no missing current obligation or criterion coverage, no unresolved blocking `introduced` or `affected` finding or required disposition, no unresolved `triage-required` or `impact-gap` state, no unclassified ambient drift, and no consumed allowance beyond an obligation, aggregate, or total-action ceiling. Exhausted or otherwise unfinishable routes SHALL retain failed or missing slice details, finding and planning lineage, complete execution and governance-mutation history, and the precise blocking states in `INCOMPLETE`. Any explicitly supplied non-`0.3.0` Dossier or embedded current input SHALL fail closed without conversion, migration, translation, or repair; retained `0.2.0` namespace bytes SHALL remain uninspected and unchanged.

#### Scenario: Successful delivery finalizes
- **WHEN** every current required obligation is present and satisfied, validly reused, or validly waived, every criterion is proven or validly waived, no unresolved causal blocker, `triage-required`, `impact-gap`, ambient drift, or required disposition remains, and all absolute ceilings are respected
- **THEN** the engine records one `DONE` `dev-flow-delivery-dossier/0.3.0` bound to the current task-change manifest and index-aware repository-set snapshot and advances to the successful terminal node

#### Scenario: Independent review is explicitly waived
- **WHEN** the assurance plan requires independent review, the driver is unavailable, and a current assurance waiver exactly governs that obligation fingerprint
- **THEN** successful finalization may proceed while the Dossier reports the obligation as waived, retains its actor and rationale, and names the remaining assurance risk rather than reporting approval

#### Scenario: Assurance budget exhausts
- **WHEN** an absolute verification, review, rework, or total-action ceiling cannot permit completion of all outstanding obligations
- **THEN** the engine records an `INCOMPLETE` `dev-flow-delivery-dossier/0.3.0` containing the exhausted ceiling, consumed executions, outstanding obligations, affected slices, and unresolved findings before entering the incomplete terminal node

#### Scenario: Success finalization uses stale proof
- **WHEN** any required obligation relies on evidence whose obligation fingerprint, task-change slice, governing input, impact closure, review guidance, or index-aware snapshot authority is stale
- **THEN** finalization fails without advancing the task

#### Scenario: Successful repository-set delivery finalizes
- **WHEN** all obligations required across the exact repository set and affected integrations are satisfied and all other completion conditions hold
- **THEN** one `DONE` `dev-flow-delivery-dossier/0.3.0` binds the exact repository set, final manifest, final aggregate snapshot, and per-obligation evidence inventory

#### Scenario: Unaffected member evidence is reused
- **WHEN** one member changes on a slice disjoint from current evidence for another member and the assurance plan authorizes reuse
- **THEN** the Dossier reports the original evidence as reused, its unchanged slice and governing provenance, and why no new execution was charged

#### Scenario: Member proof is stale
- **WHEN** a member's task-owned worktree or staged-index slice changes after evidence was recorded for that slice
- **THEN** successful finalization fails until the affected obligation is satisfied again, validly waived, or the task reaches incomplete finalization

#### Scenario: Review reports an unrelated issue
- **WHEN** current review evidence contains a finding established as `pre-existing` or `out-of-scope`
- **THEN** the Dossier reports the finding and causal evidence without treating it as rework, consumed source-rework budget, or task-owned scope

#### Scenario: Finding causality is dispositioned
- **WHEN** an operator resolves disputed finding causality through a finding- and contract-bound disposition
- **THEN** the Dossier retains the dispute, actor, rationale, decision, resulting obligation transition, and any contract or manifest expansion

#### Scenario: Triage remains unresolved at finalization
- **WHEN** a current blocking unknown-causality finding remains `triage-required` without a completed bounded causal refresh or current authorized disposition
- **THEN** the Dossier exposes the finding and remaining triage route and successful finalization rejects `DONE`

#### Scenario: An impact gap remains at finalization
- **WHEN** a proven affected relation remains outside the current impact closure and replacement impact evidence and planning have not completed
- **THEN** the Dossier exposes the invalidated plan and same-contract reentry state and successful finalization rejects `DONE`

#### Scenario: A current obligation is missing
- **WHEN** finalization cannot resolve one obligation required by the current canonical assurance plan even though an earlier plan contained evidence for related scope
- **THEN** the Dossier identifies the missing current obligation and successful finalization rejects `DONE`

#### Scenario: Unsupported Dossier is encountered
- **WHEN** replay encounters a Dossier body that does not use the current schema
- **THEN** state validation fails without conversion, migration, or fallback

### Requirement: Projections remain compact and resumable
The agent projection SHALL continue to expose exactly one current workflow action and SHALL include its canonical action binding plus compact contract, immutable preflight ownership-origin, applicable revision-source anchor, canonical roll-forward task-change-manifest and lineage, assurance-plan, current obligation, typed current-input, slice-aware freshness, absolute-budget, and terminal Dossier summaries. It SHALL expose `required`, `blocked`, `outstanding`, `satisfied`, `reused`, `not-required`, `waived`, and `exhausted` obligation counts; any current `triage-required` finding or `impact-gap` planning state; the current action's obligation and affected slice; used and remaining per-obligation allowances and aggregate verification, review, rework, and total-action ceilings; and deterministic `maximum_remaining_actions`. Full artifact, manifest, finding, evidence, and Dossier content SHALL remain available through the read-only task view rather than being injected into every Hook context.

The `dev-flow-agent/0.3.0` projection SHALL expose compact derived repository-set and index-aware member-snapshot summaries for every supported set size. Its verification guidance SHALL identify `dev-flow-verification-coverage/0.3.0` and the exact current obligation targets rather than requiring fabricated results for unaffected members. Its review guidance SHALL identify the structured finding schema, reviewed manifest and slice digests, required reviewer and guidance fingerprints, causal fields, the bounded causal-refresh route for `triage-required`, and same-contract impact/planning reentry for an `impact-gap`. It SHALL NOT project direct source rework for a blocking unknown relation or for an affected relation outside the current closure. A member capture or manifest-classification failure SHALL make the affected repository-dependent projection fail closed with member, path, and obligation diagnostics without creating per-member actions or mutating task state; an impact gap SHALL instead invalidate the current impact evidence and plan and project bounded impact/planning reentry under the same contract and remaining counters. The stored task view SHALL remain available in every case.

#### Scenario: Task resumes mid-rework
- **WHEN** a new Codex session attaches after a failed assurance execution or finding-bound rework transition
- **THEN** the current projection identifies the one current obligation and action, required current input and slice summaries, absolute allowance consumption, and `maximum_remaining_actions`

#### Scenario: Terminal task is projected
- **WHEN** a completed or incomplete task is viewed
- **THEN** the projection has no action, reports `done: true`, and includes the Dossier ID, digest, outcome, obligation and coverage summaries, budget consumption, and freshness without embedding the full Dossier

#### Scenario: Repository-set verification is projected
- **WHEN** the current action executes a verification obligation
- **THEN** the projection identifies `dev-flow-verification-coverage/0.3.0`, the exact criterion, repository, path, symbol, or integration targets, and any reusable evidence for that obligation

#### Scenario: Review is projected
- **WHEN** the current action executes an independent-review obligation
- **THEN** the projection supplies the reviewed task-change manifest and slice, obligation and guidance fingerprints, and required structured finding fields without an agent-authoritative aggregate outcome

#### Scenario: Blocking unknown causality is projected
- **WHEN** current review governance derives `triage-required` for a `blocking: true` unknown finding
- **THEN** the projection exposes the unresolved finding and only its bounded causal-refresh or authorized-disposition route, not approval, `DONE`, or direct source rework

#### Scenario: Impact gap is projected
- **WHEN** current review evidence proves an affected relation outside the current impact closure
- **THEN** the projection exposes the invalidated impact evidence and assurance plan and reenters bounded impact and planning under the same contract unless accepted scope or criteria must change

#### Scenario: One-member set is projected
- **WHEN** the task has one repository
- **THEN** the current projection exposes one `repository_set` member and the same obligation, manifest, snapshot, and coverage contracts used by every larger set

#### Scenario: Member blocks projection
- **WHEN** one member cannot be captured safely or has unclassified drift for a repository-dependent `next` call
- **THEN** projection fails with that member's path and obligation diagnostics, does not advance or omit task state, and leaves the stored task view available

### Requirement: Task change manifests are authoritative evidence provenance
Every successful source-producing action SHALL atomically record a controller-derived `dev-flow-task-change-manifest/0.3.0` successor. The manifest SHALL bind the task, effective contract, canonical repository set, immutable preflight ownership origin, every applicable contract-revision `revision-source` interval anchor, predecessor manifest, complete index-aware successor snapshot, and canonical per-path entries for the current roll-forward task-owned change set. A contract revision's revision source SHALL anchor only the subsequent source interval; it SHALL NOT replace the immutable preflight origin, rebase an inherited entry's before identity, or erase ownership established by earlier task actions. The replacement current manifest SHALL carry every inherited task-owned entry whose task-owned after identity remains material, add every exact ambient-drift entry explicitly adopted by that revision, and include every later source-producing entry. A path restored exactly to its immutable preflight identity MAY leave the current net manifest, but its production and reversion lineage SHALL remain immutable history.

Each entry SHALL be keyed by `(repository_id, path)` and SHALL include its change kind; original and current before and after worktree kind, mode, content digest, and Git worktree object ID; original and current before and after complete index entry sets; original producer or adoption record; later producer and revision lineage; bounded agent-supplied classification, current acceptance-criterion IDs, and purpose; and controller-derived ownership provenance. When a clean tracked path is first modified after preflight, the controller SHALL reconstruct its immutable original identity from the bound pre-change `HEAD`-tree mode and object ID rather than from an already modified stage-zero entry or by classifying the original as missing. Source apply SHALL require claims to cover exactly every changed manifest path. Revision reconciliation SHALL require claims to cover every retained inherited path and every exactly adopted drift path under the replacement contract, and SHALL reject unknown, omitted, duplicate, cross-root, silently dropped inherited, or contract-incompatible claims. The manifest digest SHALL cover the canonical complete document excluding its own digest. The current manifest SHALL contain at most 4,096 net entries across the task, remain subject to all existing payload, text, path, and byte bounds, and SHALL NOT be truncated. Ambient or unclaimed differences SHALL be represented separately with their observed identities and SHALL NOT be included in a task-owned slice unless a complete authorized contract revision exactly admits them. Artifacts, verification, review, findings, reuse decisions, action bindings, assurance plans, projections, and the Delivery Dossier SHALL reference the canonical current manifest, its slices, immutable ownership origin, revision anchors, and lineage rather than infer task scope from an unrestricted repository diff.

#### Scenario: First implementation records owned changes
- **WHEN** implementation changes one claimed path relative to the exact preflight baseline
- **THEN** apply derives the first manifest successor with that repository-scoped path and its separate worktree and staged-index identities

#### Scenario: Later source action changes an owned path
- **WHEN** documentation or rework changes a path already owned by the task
- **THEN** its manifest successor references the prior manifest and records the new per-path identity and producing action without losing earlier lineage

#### Scenario: Contract revision follows implementation
- **WHEN** implementation has produced still-material task-owned entries and an accepted contract revision records a new aggregate revision source
- **THEN** the revision source anchors later source intervals, the immutable preflight origin remains the ownership baseline, and the current manifest carries every still-material implementation entry with its original producer and before identity

#### Scenario: Contract revision adopts ambient drift
- **WHEN** an authorized contract revision exactly claims ambient drift paths while earlier task-owned entries remain material
- **THEN** one replacement current manifest carries all inherited task entries, adds every and only exactly adopted drift entry with revision-decision provenance, and permits later source successors to extend that lineage

#### Scenario: Ambient path appears
- **WHEN** the complete workspace snapshot contains a changed path for which the task has no current ownership claim
- **THEN** the controller reports ambient drift and blocks repository-dependent progress until the user restores the accepted source, expands the contract to claim every drift path, or cancels at an authorized stage without silently inserting that path into task assurance scope

#### Scenario: Manifest is tampered
- **WHEN** a manifest path, ownership provenance, predecessor, worktree identity, staged-index identity, slice digest, or canonical digest is changed after commit
- **THEN** replay fails closed before treating any dependent artifact or evidence as current

#### Scenario: Staged-only task change is recorded
- **WHEN** a task-owned path's staged blob changes while its worktree bytes remain equal to the prior observation
- **THEN** the manifest successor records the staged-index transition and every dependent slice digest reflects it

#### Scenario: Current manifest exceeds its entry bound
- **WHEN** a source successor or revision reconciliation would require a 4,097th current net manifest entry
- **THEN** the complete mutation is rejected without truncating ownership, omitting an inherited entry, or appending a partial manifest

### Requirement: Structured findings retain causal and resolution lineage
Every review execution SHALL record one `dev-flow-independent-review/0.3.0` result and a set of `dev-flow-review-finding/0.3.0` values bound to the current review obligation, reviewer fingerprint, guidance fingerprint, task-change manifest, assurance plan, complete snapshot, reviewed slice, and review evidence digest. One review execution SHALL contain at most 64 findings, subject also to the existing shared 64 KiB action-payload and 8 KiB per-text limits; a 65th finding or any existing payload or text violation SHALL reject the complete review without truncation or a partial record. Each finding SHALL have a task-unique stable ID and canonical fingerprint derived from its normalized severity, blocking flag, causal relation and evidence, criterion bindings, repository ID, bounded path, symbol, resource, or integration locator, smallest sufficient resolution, and reviewed slice. Controller-derived finding state SHALL record whether the finding is current; causally `introduced`, `affected`, `pre-existing`, `out-of-scope`, or `unknown`; dispositioned; rework-bound; `triage-required`; `impact-gap`; resolved; replaced; or stale.

A finding SHALL become a direct source-rework input only when it is current, `blocking: true`, causally `introduced` or `affected`, and within the current impact closure. A `blocking: true` unknown finding SHALL keep the review obligation unresolved in `triage-required`; it SHALL NOT yield approval, `DONE`, or direct source rework until a bounded causal refresh establishes a supported relation or a current authorized disposition resolves the finding. When valid causal evidence proves an `affected` relation outside the current impact closure, the controller SHALL record an `impact-gap`, invalidate the governing impact evidence and assurance plan, and reenter bounded impact and planning under the same effective contract and remaining absolute counters. Direct source rework SHALL remain unavailable until the replacement closure contains the proven relation. Contract revision SHALL occur only when accepted delivery scope or criteria change, not merely because the plan's impact closure was incomplete.

A rework artifact SHALL reference every addressed `introduced` or `affected` finding fingerprint and its manifest successor; a later review SHALL explicitly close, retain, or replace each current finding. Finding IDs SHALL NOT be silently reused for different canonical content, and historical finding, triage, impact-gap, disposition, rework, re-review, and planning-reentry records SHALL remain replayable and visible in projections and the Delivery Dossier.

#### Scenario: Rework resolves one finding
- **WHEN** a rework artifact names one current blocking `introduced` or `affected` finding and later current review evidence confirms its absence on the successor slice
- **THEN** the finding is marked resolved with links to the original review, rework record, manifest transition, and closing review

#### Scenario: Review replaces a finding
- **WHEN** later review determines that an earlier issue persists with materially different location, criterion binding, severity, or causal evidence
- **THEN** it records a new fingerprint and explicit replacement link rather than mutating the earlier finding

#### Scenario: Finding is unrelated to the task
- **WHEN** validated causal evidence classifies a review finding as `pre-existing` or `out-of-scope`
- **THEN** the finding remains visible with non-task status and cannot become a causal source-rework input

#### Scenario: Blocking finding has unknown causality
- **WHEN** a current review reports a `blocking: true` finding whose validated causal relation is `unknown`
- **THEN** the controller derives `triage-required`, keeps the review obligation unresolved, blocks approval and `DONE`, and projects bounded causal refresh or authorized disposition without direct source rework

#### Scenario: Affected finding proves an impact gap
- **WHEN** current review evidence proves that a task-owned change affects a location or behavior outside the current impact closure
- **THEN** the controller records an `impact-gap`, invalidates the governing impact evidence and assurance plan, and reenters impact and planning under the same contract before any source rework; contract revision is required only if accepted scope or criteria change

#### Scenario: Finding disposition changes scope
- **WHEN** an authorized finding-bound disposition expands the effective contract to include a previously non-task issue
- **THEN** the lineage records the disposition and new contract digest, and only subsequent manifests and obligations may treat the issue as task scope

#### Scenario: Finding payload is tampered
- **WHEN** a finding's fingerprint, reviewer binding, reviewed slice, causal evidence, resolution link, or disposition provenance no longer matches its canonical record
- **THEN** replay fails closed and no dependent assurance or Dossier can use it

#### Scenario: Review exceeds its finding bound
- **WHEN** one review execution submits a 65th finding
- **THEN** apply rejects the complete review without truncation, partial findings, a record, or allowance consumption
