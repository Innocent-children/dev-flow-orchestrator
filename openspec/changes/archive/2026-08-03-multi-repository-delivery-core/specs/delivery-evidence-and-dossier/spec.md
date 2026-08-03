## MODIFIED Requirements

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
A typed artifact record SHALL include artifact type and schema, canonical digest, producer action and node, action attempt, task revision, effective contract revision and digest, declared workspace role, observed content-sensitive repository snapshot, and resolved upstream artifact record IDs, digests, and edge kinds. The current workflow schema SHALL declare each artifact stage as `context`, `produces-source`, or `verifies-source` and each input edge as `governing`, `source-predecessor`, or `causal`. A governing edge SHALL track the latest current artifact of its type. A source-predecessor edge SHALL pin the source baseline that an intentional source-producing action replaces. A causal edge SHALL retain the reason for rework without treating addressed failed assurance as current completion proof. Artifact provenance fields SHALL be calculated by the controller and engine rather than trusted from agent payload.

Every artifact's `snapshot` field SHALL contain the complete validated repository-set snapshot for the current product model. Repository-set identity and complete scope SHALL be derived from immutable task membership and the embedded snapshot rather than copied into record, binding, or input fields. Source-producing lineage SHALL connect one aggregate predecessor to one aggregate successor; context and verification lineage SHALL retain the same typed edge semantics for every supported repository-set size.

#### Scenario: Artifact is produced from declared inputs
- **WHEN** a workflow action declares required input artifact types and current inputs exist
- **THEN** the new artifact records the latest current input IDs and digests and binds the complete current repository-set snapshot

#### Scenario: Required input is missing
- **WHEN** an action requires an artifact type with no current producer record
- **THEN** the action fails without advancing the task

#### Scenario: Rework consumes a failed review causally
- **WHEN** a source-producing rework action pins the failed review as a causal edge and the current source as its source predecessor
- **THEN** the successor records both reasons, and later replacement of the failed review as assurance proof does not invalidate the addressed rework artifact

#### Scenario: Agent payload contradicts provenance
- **WHEN** submitted content attempts to supply authoritative baseline, task revision, producer, contract, snapshot, or digest values
- **THEN** those fields are rejected or ignored in favor of controller-derived provenance

#### Scenario: Source action changes two members
- **WHEN** one implementation action changes API and client worktrees
- **THEN** its one artifact records one aggregate successor containing both members

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
The Git boundary SHALL calculate a read-only workspace digest from `HEAD`, repository status, and canonical entries for tracked changed and untracked non-ignored paths. It SHALL validate repository-relative paths and parent containment. It SHALL use `lstat`, open regular files without following the final path, compare file identity metadata before and after the bounded read, and hash path, mode, and content. It SHALL hash symbolic-link target bytes without following the link. It SHALL hash a clean initialized gitlink as path, mode, index object ID, and current submodule `HEAD` without recursive content traversal; missing or dirty gitlinks SHALL fail. Unsupported special files SHALL fail before read. Snapshot collection SHALL repeat Git path/status enumeration and apply explicit time, path-count, path-byte, per-file, and total-content budgets. Any containment violation, replacement race, unstable enumeration, unsupported type, or budget breach SHALL fail without recording evidence.

For every task, a `dev-flow-repository-set-snapshot/0.2.0` SHALL contain the derived set identity and each complete member `dev-flow-workspace-snapshot/0.2.0` in canonical order, and its aggregate digest SHALL cover the complete wrapper excluding its own digest. The wrapper SHALL exactly match `TaskState.repositories`, including a one-member tuple. The controller SHALL compare two complete observations before mutation. Any member identity mismatch, disappearance, or complete-set mismatch SHALL fail without recording aggregate or partial evidence.

#### Scenario: Modified file changes again
- **WHEN** a tracked modified file changes content while retaining the same porcelain status entry
- **THEN** the member workspace digest and, for a repository set, aggregate digest change, making evidence bound to the earlier content stale

#### Scenario: Untracked input changes
- **WHEN** an untracked non-ignored file included in a member workspace changes content
- **THEN** the member workspace digest and, for a repository set, aggregate digest change

#### Scenario: Snapshot exceeds its budget
- **WHEN** changed or untracked content in any member exceeds the declared snapshot budget or changes during collection
- **THEN** complete snapshot collection fails explicitly and the task does not advance with unverifiable or partial evidence

#### Scenario: Changed symbolic link points outside the repository
- **WHEN** a changed or untracked symbolic link targets a path outside its member repository
- **THEN** the snapshot hashes the link-target bytes without opening the target and remains confined to that member's read boundary

#### Scenario: Gitlink is present
- **WHEN** a changed gitlink names an initialized clean submodule
- **THEN** the member snapshot hashes its index object ID and current submodule `HEAD` without recursing; a missing or dirty submodule fails explicitly

#### Scenario: Special file is untracked
- **WHEN** Git enumeration returns a FIFO, socket, device, or another unsupported filesystem type
- **THEN** snapshot collection rejects the entry without opening or blocking on it

#### Scenario: Path is replaced during collection
- **WHEN** a file, link, parent path, Git path list, or earlier member observation changes while snapshot collection is in progress
- **THEN** identity or repeated-observation checks fail and no task record is committed

#### Scenario: Set membership is forged
- **WHEN** a repository-set wrapper omits, adds, reorders, or misidentifies a member
- **THEN** snapshot validation rejects it against immutable task membership

### Requirement: Action bindings close the source-transition interval
Before work begins, the projection SHALL resolve a canonical action binding containing task revision, action and node IDs, effective contract digest, every pinned input record ID, digest, and edge kind, the source predecessor when declared, and the starting workspace snapshot digest. Apply SHALL require the exact binding, verify its canonical digest, and compare-and-swap the task revision, contract, current node, action, and pinned ledger records. A `context` or `verifies-source` action SHALL require its apply-time snapshot to equal the starting snapshot. A `produces-source` action MAY observe a changed apply-time worktree and SHALL atomically record that successor snapshot after the binding passes. A stale or contradictory binding SHALL fail without appending a record.

`starting_snapshot_digest` SHALL always be the repository-set aggregate digest and apply SHALL validate a complete current repository-set snapshot. Context and verifies-source equality SHALL apply to the complete aggregate. A produces-source action MAY produce a different aggregate snapshot only after its bound aggregate predecessor remains authoritative.

#### Scenario: Documentation starts from current implementation
- **WHEN** `next` pins the current implementation and workspace `W1`, documentation intentionally changes the worktree to `W2`, and apply receives the unchanged action binding
- **THEN** apply accepts the pinned implementation as the source predecessor and atomically records documentation as the `W2` source authority

#### Scenario: Task advances after binding is projected
- **WHEN** a decision, contract revision, or workflow action commits after an action binding was issued
- **THEN** apply rejects the earlier binding by revision CAS, returns a fresh projection when current repositories can be captured, and records no successor

#### Scenario: Read-only stage changes source
- **WHEN** a context or source-verification action applies after any member differs from its bound starting snapshot
- **THEN** apply rejects the action because that stage lacks source-producing authority

#### Scenario: Verification starts from current aggregate source
- **WHEN** repository-set verification is projected against aggregate snapshot `W1`
- **THEN** apply succeeds only while every member still matches `W1`

#### Scenario: Source action changes one or more members
- **WHEN** implementation uses its unchanged repository-set binding and produces stable aggregate snapshot `W2`
- **THEN** one record replaces `W1` with `W2` as task-wide source authority

#### Scenario: Binding uses a non-current snapshot digest
- **WHEN** a binding references a bare member snapshot or another unsupported snapshot dialect
- **THEN** replay rejects the state without translating or repairing the binding

### Requirement: Freshness is stage-sensitive and derived from typed inputs
Artifact freshness SHALL be derived without rewriting historical records. Every current artifact SHALL match the effective contract. A governing edge SHALL continue to reference the latest current artifact of its type, so later governing replacement invalidates its descendants. A source-predecessor edge SHALL keep the explicitly consumed source lineage eligible through the current successor; only the newest source authority SHALL match the present workspace. A causal edge SHALL require an intact contract-compatible referenced record but SHALL not require that failed or superseded assurance record to remain current proof. Every governing resource path SHALL still match its recorded authoritative digest; reported resources SHALL not affect currentness. A `context` artifact SHALL remain current across a later declared source-producing stage. A `verifies-source` artifact SHALL observe the newest source authority exactly and SHALL become stale when a later source producer is recorded. Stale records SHALL retain their content and stale reasons and SHALL be excluded from valid completion proof.

For all evidence, source authority and source verification SHALL use the repository-set aggregate digest, and governing resources SHALL be keyed by repository ID and path. Any unrecorded drift in any member SHALL make the latest aggregate source authority and all assurance bound to it stale. A later valid source-producing record MAY preserve an earlier context artifact when its typed lineage and governing resources remain current, but the controller SHALL NOT reuse prior verification, review assurance, or completion proof for unchanged members independently of the aggregate result. Stale reasons SHALL identify affected repository IDs when derivable.

#### Scenario: Contract revision invalidates earlier proof
- **WHEN** the delivery contract changes after verification
- **THEN** the earlier verification remains visible and is excluded from current acceptance coverage

#### Scenario: Upstream plan is replaced
- **WHEN** a new current plan artifact supersedes the plan used by an implementation artifact
- **THEN** the dependent implementation and downstream proof become stale through lineage

#### Scenario: Repository has not changed
- **WHEN** contract, latest input references, governing resources, and every applicable member snapshot still match
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
- **WHEN** a source-producing action has a current bound predecessor but its intentional edits make the live workspace differ before apply
- **THEN** binding validation uses the pinned predecessor and starting snapshot rather than re-resolving that predecessor against the changed workspace

#### Scenario: Source successor is current after commit
- **WHEN** the same bound source-producing action commits its successor snapshot
- **THEN** freshness follows the recorded predecessor edge to the successor and treats the successor as the newest source authority

#### Scenario: Source changes outside a declared producer
- **WHEN** any present member differs from the latest current source producer and no later source-producing record consumes it
- **THEN** that aggregate source authority and its verification descendants are stale while unrelated contract-only context artifacts remain current

#### Scenario: One member is unavailable
- **WHEN** current state cannot be captured safely for any member
- **THEN** aggregate freshness and completion proof are unavailable while historical records remain unchanged and inspectable

### Requirement: Acceptance coverage is explicit and authority-aware
Verification SHALL report every effective acceptance criterion as `proven` or `unverified`. A current waiver decision MAY convert its exact criterion to `waived`. Successful delivery SHALL require every effective criterion to be proven or validly waived using current evidence.

Coverage SHALL contain exactly an effective-criterion `criteria` map, structured results for every repository ID, and one integration result, all bound to the current aggregate snapshot. This shape SHALL apply to every supported repository-set size. Its top-level command SHALL equal the integration command, and its top-level `passed` command aggregate SHALL equal the conjunction of all member and integration pass flags. Assurance success SHALL additionally require all criteria to be proven or currently waived. A well-shaped command aggregate that passes while a criterion remains unverified and unwaived SHALL be recorded as an unsuccessful attempt and follow bounded rework or exhaustion. One member result SHALL NOT substitute for another, and member-local success SHALL NOT substitute for failed integration evidence.

#### Scenario: All criteria are proven
- **WHEN** fresh passing verification proves every effective criterion and, for a repository set, every member and integration command passes
- **THEN** completion coverage reports every criterion as proven and is eligible for successful finalization

#### Scenario: One criterion has a current waiver
- **WHEN** a current explicit waiver governs one effective criterion and all others are proven
- **THEN** completion coverage reports that criterion as waived and retains the waiver rationale

#### Scenario: Criterion remains unverified
- **WHEN** an exhausted path reaches incomplete finalization with an unverified criterion
- **THEN** the dossier names the criterion and the task cannot report a successful delivery outcome

#### Scenario: One member result is absent
- **WHEN** criterion coverage is complete but one canonical repository ID has no current result
- **THEN** apply rejects the malformed coverage without advancing the task

#### Scenario: Integration evidence fails
- **WHEN** every member-local result passes but the integration result fails
- **THEN** the command aggregate is false and verification is unsuccessful

#### Scenario: Commands pass while a criterion remains unverified
- **WHEN** every member and integration command passes but one criterion is unverified without a current waiver
- **THEN** the valid verification attempt is recorded as unsuccessful assurance and follows the declared failure or exhaustion route

### Requirement: Delivery Dossier is generated from current records
Every non-cancelled official workflow SHALL finalize through the current typed Delivery Dossier generated by the pure domain layer. For every supported repository-set size it SHALL contain the effective contract and scope, derived repository-set identity, canonical member inventory, per-member baseline and final snapshot summaries, changed-member diagnostics, scoped resources, every verification and review attempt with current or stale status, current structured repository and integration results, aggregate final snapshot and freshness, current review status, assurance level and findings, documentation impact, current artifacts and provenance, remaining risks, decisions and waivers, delivery outcome, and handoff recommendation. `DONE` SHALL require fresh successful aggregate evidence. Exhausted paths SHALL retain failed or missing member details and attempt history in `INCOMPLETE`. Any unsupported Dossier schema SHALL fail closed without conversion.

#### Scenario: Successful delivery finalizes
- **WHEN** required current verification passes, every required review has current independent approval or an exact current review-assurance waiver, and all criteria are proven or validly waived
- **THEN** the engine records one `DONE` `dev-flow-delivery-dossier/0.2.0` bound to the current repository-set snapshot and advances to the successful terminal node

#### Scenario: Independent review is explicitly waived
- **WHEN** a review record is unavailable and a current `assurance-waiver` decision exactly governs that review node
- **THEN** successful finalization may proceed while the dossier reports the review as waived, retains its actor and rationale, and names the remaining assurance risk rather than reporting approval

#### Scenario: Assurance budget exhausts
- **WHEN** an official workflow reaches its exhausted finalization node
- **THEN** the engine records an `INCOMPLETE` `dev-flow-delivery-dossier/0.2.0` containing failed attempts and unresolved coverage before entering the incomplete terminal node

#### Scenario: Success finalization uses stale proof
- **WHEN** required verification, review, upstream artifacts, or any required member evidence is stale
- **THEN** finalization fails without advancing the task

#### Scenario: Successful repository-set delivery finalizes
- **WHEN** every required current member and integration result passes and all other completion obligations are satisfied
- **THEN** one `DONE` `dev-flow-delivery-dossier/0.2.0` binds the exact repository set and final aggregate snapshot

#### Scenario: Member proof is stale
- **WHEN** any member changes after verification
- **THEN** successful repository-set finalization fails without advancing the task

#### Scenario: Unsupported Dossier is encountered
- **WHEN** replay encounters a Dossier body that does not use the current schema
- **THEN** state validation fails without conversion, migration, or fallback

### Requirement: Projections remain compact and resumable
The agent projection SHALL continue to expose exactly one current workflow action and SHALL include its canonical action binding plus compact contract, typed current-input, retry-budget, freshness, and terminal dossier summaries. Full artifact and dossier content SHALL remain available through the read-only task view rather than being injected into every Hook context.

The `dev-flow-agent/0.2.0` projection SHALL expose compact derived repository-set and member-snapshot summaries for every supported set size, and its verification guidance SHALL identify `dev-flow-verification-coverage/0.2.0` and describe the nested `schema`, `criteria`, `repositories`, and `integration` coverage body without changing the pinned workflow document's top-level fields. A member capture failure SHALL make repository-dependent projection fail with member-specific diagnostics without creating per-member actions or mutating task state; the stored task view SHALL remain available.

#### Scenario: Task resumes mid-rework
- **WHEN** a new Codex session attaches after a failed assurance attempt and rework transition
- **THEN** the current projection identifies the one current action, required current input summaries, and remaining retry budget

#### Scenario: Terminal task is projected
- **WHEN** a completed or incomplete task is viewed
- **THEN** the projection has no action, reports `done: true`, and includes the dossier ID, digest, outcome, coverage summary, and freshness without embedding the full dossier

#### Scenario: Repository-set verification is projected
- **WHEN** the current action uses `verification.record`
- **THEN** the current projection identifies `dev-flow-verification-coverage/0.2.0` and describes the exact nested `schema`, `criteria`, `repositories`, and `integration` coverage fields

#### Scenario: One-member set is projected
- **WHEN** the task has one repository
- **THEN** the current projection exposes one `repository_set` member and the same nested verification shape used by every larger set

#### Scenario: Member blocks projection
- **WHEN** one member cannot be captured safely for a repository-dependent `next` call
- **THEN** projection fails with that member's diagnostics, does not advance or omit task state, and leaves the stored task view available
