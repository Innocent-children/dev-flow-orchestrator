## ADDED Requirements

### Requirement: Every post-creation mutation appends one typed replay record
Task creation SHALL atomically persist revision-zero initialization state containing the original contract and no records. Every later successful task mutation SHALL append exactly one immutable record and increment the task revision exactly once, preserving `task revision == record count`. Records SHALL identify their schema, kind, record ID, committed revision, timestamp, producer, payload, effective contract revision and digest, and workflow transition when applicable. Preflight, workflow actions, contract revisions, and decisions SHALL use the same replay ledger.

#### Scenario: Task is created
- **WHEN** a valid task is initialized
- **THEN** it has task revision zero, an immutable original contract, and an empty record ledger

#### Scenario: Preflight commits
- **WHEN** bounded repository inspection succeeds for a new task
- **THEN** revision one contains one preflight action record and replay advances from the workflow entry

#### Scenario: Stored record is tampered
- **WHEN** a record ID, payload, transition, digest, baseline, or input reference no longer matches its canonical content or workflow contract
- **THEN** direct task loading fails closed as invalid state

#### Scenario: Mutation tries to rewrite history
- **WHEN** a candidate state changes, removes, or reorders a prior record
- **THEN** store validation rejects the write before atomic replacement

### Requirement: Artifacts carry authoritative provenance and typed lineage
A typed artifact record SHALL include artifact type and schema, canonical digest, producer action and node, action attempt, task revision, effective contract revision and digest, declared workspace role, observed content-sensitive repository snapshot, and resolved upstream artifact record IDs, digests, and edge kinds. Workflow-v2 SHALL declare each artifact stage as `context`, `produces-source`, or `verifies-source` and each input edge as `governing`, `source-predecessor`, or `causal`. A governing edge SHALL track the latest current artifact of its type. A source-predecessor edge SHALL pin the source baseline that an intentional source-producing action replaces. A causal edge SHALL retain the reason for rework without treating addressed failed assurance as current completion proof. Artifact provenance fields SHALL be calculated by the controller and engine rather than trusted from agent payload.

#### Scenario: Artifact is produced from declared inputs
- **WHEN** a workflow action declares required input artifact types and current inputs exist
- **THEN** the new artifact records the latest current input IDs and digests

#### Scenario: Required input is missing
- **WHEN** an action requires an artifact type with no current producer record
- **THEN** the action fails without advancing the task

#### Scenario: Rework consumes a failed review causally
- **WHEN** a source-producing rework action pins the failed review as a causal edge and the current source as its source predecessor
- **THEN** the successor records both reasons, and later replacement of the failed review as assurance proof does not invalidate the addressed rework artifact

#### Scenario: Agent payload contradicts provenance
- **WHEN** submitted content attempts to supply authoritative baseline, task revision, producer, or digest values
- **THEN** those fields are rejected or ignored in favor of controller-derived provenance

### Requirement: Repository-backed artifacts bind declared resources
A stage that creates or updates repository-backed planning artifacts SHALL use the `produces-source` workspace role and a source-predecessor binding. Its payload MAY declare bounded repository-relative resource paths and `governing` or `reported` roles; the controller SHALL validate containment and calculate each content digest through the safe snapshot boundary. Governing resource digests SHALL participate in freshness even when the files are otherwise clean in Git. Reported resources SHALL remain provenance without governing plan validity. An OpenSpec `tasks.md` resource SHALL record its full raw digest as reported provenance and a governing semantic digest calculated by canonicalizing only Markdown task-list checkbox markers `- [ ]`, `- [x]`, and `- [X]` to `- [ ]` before hashing; every other byte, including task text, order, and test obligations, SHALL remain governing.

#### Scenario: OpenSpec planning creates repository files
- **WHEN** an OpenSpec planning action creates proposal, design, spec, and task files from its pinned source predecessor
- **THEN** apply records a successor source snapshot plus authoritative paths and digests, with proposal/design/spec resources governing plan freshness

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

### Requirement: Repository snapshots are content-sensitive and bounded
The Git boundary SHALL calculate a read-only workspace digest from `HEAD`, repository status, and canonical entries for tracked changed and untracked non-ignored paths. It SHALL validate repository-relative paths and parent containment. It SHALL use `lstat`, open regular files without following the final path, compare file identity metadata before and after the bounded read, and hash path, mode, and content. It SHALL hash symbolic-link target bytes without following the link. It SHALL hash a clean initialized gitlink as path, mode, index object ID, and current submodule `HEAD` without recursive content traversal; missing or dirty gitlinks SHALL fail. Unsupported special files SHALL fail before read. Snapshot collection SHALL repeat Git path/status enumeration and apply explicit time, path-count, path-byte, per-file, and total-content budgets. Any containment violation, replacement race, unstable enumeration, unsupported type, or budget breach SHALL fail without recording evidence.

#### Scenario: Modified file changes again
- **WHEN** a tracked modified file changes content while retaining the same porcelain status entry
- **THEN** the workspace digest changes and evidence bound to the earlier content becomes stale

#### Scenario: Untracked input changes
- **WHEN** an untracked non-ignored file included in the workspace changes content
- **THEN** the workspace digest changes

#### Scenario: Snapshot exceeds its budget
- **WHEN** changed or untracked content exceeds the declared snapshot budget or changes during collection
- **THEN** snapshot collection fails explicitly and the task does not advance with unverifiable evidence

#### Scenario: Changed symbolic link points outside the repository
- **WHEN** a changed or untracked symbolic link targets a path outside the repository
- **THEN** the snapshot hashes the link-target bytes without opening the target and remains confined to the repository read boundary

#### Scenario: Gitlink is present
- **WHEN** a changed gitlink names an initialized clean submodule
- **THEN** the snapshot hashes its index object ID and current submodule `HEAD` without recursing; a missing or dirty submodule fails explicitly

#### Scenario: Special file is untracked
- **WHEN** Git enumeration returns a FIFO, socket, device, or another unsupported filesystem type
- **THEN** snapshot collection rejects the entry without opening or blocking on it

#### Scenario: Path is replaced during collection
- **WHEN** a file, link, parent path, or Git path list changes while snapshot collection is in progress
- **THEN** identity or repeated-enumeration checks fail and no task record is committed

### Requirement: Action bindings close the source-transition interval
Before work begins, the projection SHALL resolve a canonical action binding containing task revision, action and node IDs, effective contract digest, every pinned input record ID/digest/edge kind, the source predecessor when declared, and the starting workspace snapshot digest. Apply SHALL require the exact binding, verify its canonical digest, and compare-and-swap the task revision, contract, current node, action, and pinned ledger records. A `context` or `verifies-source` action SHALL require its apply-time snapshot to equal the starting snapshot. A `produces-source` action MAY observe a changed apply-time worktree and SHALL atomically record that successor snapshot after the binding passes. A stale or contradictory binding SHALL fail without appending a record.

#### Scenario: Documentation starts from current implementation
- **WHEN** `next` pins the current implementation and workspace `W1`, documentation intentionally changes the worktree to `W2`, and apply receives the unchanged action binding
- **THEN** apply accepts the pinned implementation as the source predecessor and atomically records documentation as the `W2` source authority

#### Scenario: Task advances after binding is projected
- **WHEN** a decision, contract revision, or workflow action commits after an action binding was issued
- **THEN** apply rejects the earlier binding by revision CAS and returns a fresh projection without recording the successor

#### Scenario: Read-only stage changes source
- **WHEN** a context or source-verification action applies after the worktree differs from its bound starting snapshot
- **THEN** apply rejects the action because that stage lacks source-producing authority

### Requirement: Freshness is stage-sensitive and derived from typed inputs
Artifact freshness SHALL be derived without rewriting historical records. Every current artifact SHALL match the effective contract. A governing edge SHALL continue to reference the latest current artifact of its type, so later governing replacement invalidates its descendants. A source-predecessor edge SHALL keep the explicitly consumed source lineage eligible through the current successor; only the newest source authority SHALL match the present worktree. A causal edge SHALL require an intact contract-compatible referenced record but SHALL not require that failed or superseded assurance record to remain current proof. Every governing resource path SHALL still match its recorded authoritative digest; reported resources SHALL not affect currentness. A `context` artifact SHALL remain current across a later declared source-producing stage. A `verifies-source` artifact SHALL observe the newest source authority exactly and SHALL become stale when a later source producer is recorded. Stale records SHALL retain their content and stale reasons and SHALL be excluded from valid completion proof.

#### Scenario: Contract revision invalidates earlier proof
- **WHEN** the delivery contract changes after verification
- **THEN** the earlier verification remains visible and is excluded from current acceptance coverage

#### Scenario: Upstream plan is replaced
- **WHEN** a new current plan artifact supersedes the plan used by an implementation artifact
- **THEN** the dependent implementation and downstream proof become stale through lineage

#### Scenario: Repository has not changed
- **WHEN** contract, workspace snapshot, and latest input references still match
- **THEN** the artifact remains current across controller restart

#### Scenario: Implementation consumes a plan and changes source
- **WHEN** a current implementation artifact explicitly consumes the latest current plan and records a new source snapshot
- **THEN** the plan remains current, the implementation becomes the source authority, and downstream actions may consume both

#### Scenario: Documentation changes source after implementation
- **WHEN** a documentation artifact explicitly consumes the current implementation and produces a later source snapshot
- **THEN** both artifacts remain current through lineage and final verification must observe the documentation snapshot

#### Scenario: Review rework changes source
- **WHEN** review rework causally consumes the failed review, pins the current source predecessor, and records a new source baseline
- **THEN** the successor remains current, the addressed review remains historical evidence rather than current proof, and verification plus review must be repeated against the successor

#### Scenario: Source successor is eligible before commit
- **WHEN** a source-producing action has a current bound predecessor but its intentional edits make the live worktree differ before apply
- **THEN** binding validation uses the pinned predecessor and starting snapshot rather than re-resolving that predecessor against the changed worktree

#### Scenario: Source successor is current after commit
- **WHEN** the same bound source-producing action commits its successor snapshot
- **THEN** freshness follows the recorded predecessor edge to the successor and treats the successor as the newest source authority

#### Scenario: Source changes outside a declared producer
- **WHEN** the present worktree differs from the latest current source producer and no later source-producing record consumes it
- **THEN** that source authority and its verification descendants are stale while unrelated contract-only context artifacts remain current

### Requirement: Acceptance coverage is explicit and authority-aware
Verification SHALL report every effective acceptance criterion as `proven` or `unverified`. A current waiver decision MAY convert its exact criterion to `waived`. Successful delivery SHALL require every effective criterion to be proven or validly waived using current evidence.

#### Scenario: All criteria are proven
- **WHEN** fresh passing verification proves every effective criterion
- **THEN** completion coverage reports every criterion as proven

#### Scenario: One criterion has a current waiver
- **WHEN** a current explicit waiver governs one effective criterion and all others are proven
- **THEN** completion coverage reports that criterion as waived and retains the waiver rationale

#### Scenario: Criterion remains unverified
- **WHEN** an exhausted path reaches incomplete finalization with an unverified criterion
- **THEN** the dossier names the criterion and the task cannot report a successful delivery outcome

### Requirement: Delivery Dossier is generated from current records
Every non-cancelled official workflow SHALL finalize through a typed Delivery Dossier generated by the pure domain layer. The dossier SHALL contain the effective contract and scope, change or investigation summary, criterion coverage, current verification commands and results, review status, assurance level and findings, documentation impact, current artifacts and provenance, remaining risks, criterion and review waivers, delivery outcome, and handoff recommendation.

#### Scenario: Successful delivery finalizes
- **WHEN** required current verification passes, every required review has current independent approval or an exact current review-assurance waiver, and all criteria are proven or validly waived
- **THEN** the engine records a `DONE` dossier bound to the current repository snapshot and advances to the successful terminal node

#### Scenario: Independent review is explicitly waived
- **WHEN** a review record is unavailable and a current `assurance-waiver` decision exactly governs that review node
- **THEN** successful finalization may proceed while the dossier reports the review as waived, retains its actor and rationale, and names the remaining assurance risk rather than reporting approval

#### Scenario: Assurance budget exhausts
- **WHEN** an official workflow reaches its exhausted finalization node
- **THEN** the engine records an `INCOMPLETE` dossier containing failed attempts and unresolved coverage before entering the incomplete terminal node

#### Scenario: Success finalization uses stale proof
- **WHEN** required verification, review, or upstream artifacts are stale
- **THEN** finalization fails without advancing the task

### Requirement: Projections remain compact and resumable
The agent projection SHALL continue to expose exactly one current workflow action and SHALL include its canonical action binding plus compact contract, typed current-input, retry-budget, freshness, and terminal dossier summaries. Full artifact and dossier content SHALL remain available through the read-only task view rather than being injected into every Hook context.

#### Scenario: Task resumes mid-rework
- **WHEN** a new Codex session attaches after a failed assurance attempt and rework transition
- **THEN** the projection identifies the one current action, required current input summaries, and remaining retry budget

#### Scenario: Terminal task is projected
- **WHEN** a completed or incomplete task is viewed
- **THEN** the projection has no action, reports `done: true`, and includes the dossier ID, digest, outcome, coverage summary, and freshness without embedding the full dossier
