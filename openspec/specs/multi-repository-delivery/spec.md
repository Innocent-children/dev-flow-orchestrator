# multi-repository-delivery Specification

## Purpose
TBD - created by archiving change multi-repository-delivery-core. Update Purpose after archive.
## Requirements
### Requirement: A task binds one exact canonical repository set
The controller SHALL accept one through eight caller-supplied local repository roots as an order-insensitive set. Before writing task state, it SHALL resolve and inspect every root, require the exact top-level root of an existing non-bare Git worktree, and reject an empty or over-limit input, path aliases or duplicate roots, two members sharing one canonical Git common directory, ancestor-descendant member overlap, and equality or containment in either direction between any member and the controller data directory. It SHALL assign each member a task-stable repository ID, sort members by byte-stable canonical path and then ID, persist the complete tuple in `TaskState.repositories`, and derive a repository-set identity from that tuple. Membership SHALL remain immutable. The CLI SHALL accept repeatable `--repo`; one occurrence creates a one-member set through the same controller path. The Python controller API SHALL accept only the plural repository collection and SHALL NOT expose a singular repository alias.

#### Scenario: Multi-repository task starts
- **WHEN** a caller supplies two through eight distinct safe Git worktree roots
- **THEN** revision-zero state stores the complete canonical member tuple, derives one stable repository-set identity, stores the original contract, and has an empty ledger

#### Scenario: One-member repository set starts
- **WHEN** a caller supplies one `--repo` argument
- **THEN** the controller creates a canonical one-member repository set and uses the same task, snapshot, projection, verification, and Dossier model used for larger sets

#### Scenario: Repository count is outside the bound
- **WHEN** a caller supplies zero or more than eight repository roots
- **THEN** task creation fails before any task state is written

#### Scenario: Two supplied paths identify the same repository
- **WHEN** two paths resolve to the same worktree root or to distinct worktrees sharing one Git common directory
- **THEN** task creation rejects the duplicate repository instead of silently collapsing it

#### Scenario: Member roots overlap
- **WHEN** one canonical member root contains another canonical member root
- **THEN** task creation rejects the repository set before state is written

#### Scenario: One member is invalid
- **WHEN** one supplied path is missing, is not the exact worktree root, is bare, is unsafe, is unavailable, or overlaps the controller data directory
- **THEN** task creation identifies the offending input and writes no partial task state

#### Scenario: Membership change is requested
- **WHEN** a caller attempts to add, remove, replace, reorder, or relocate a member after task creation
- **THEN** the controller rejects the change and requires a new task for the different set

### Requirement: Worktrees remain user-prepared and Git-unmanaged
Every member worktree SHALL exist before task start and remain under user ownership. The controller SHALL use Git only for bounded read-only identity, preflight, and snapshot operations. It SHALL NOT create or remove worktrees or branches, switch branches, edit the index, stage, commit, merge, rebase, stash, clean, push, create pull requests, dispatch external CI, or clean up member worktrees. Workflow and Skill guidance SHALL identify required operator steps when those operations are needed.

#### Scenario: User supplies prepared worktrees
- **WHEN** a task starts from prepared API and client worktrees
- **THEN** the controller inspects and binds those exact roots without changing either Git repository

#### Scenario: Delivery needs publication
- **WHEN** completion requires a commit, push, pull request, or external CI run
- **THEN** handoff identifies the user-owned step and the controller performs no implicit delivery effect

#### Scenario: Task is cancelled
- **WHEN** a repository-set task is cancelled from a stage that declares cancellation
- **THEN** cancellation changes only controller state and leaves every member worktree untouched

### Requirement: Repository-set snapshots are bounded and all-or-none
For every task, preflight and every repository-backed operation SHALL capture a `dev-flow-repository-set-snapshot/0.4.0` value containing the derived repository-set identity and one complete validated `dev-flow-workspace-snapshot/0.4.0` per member in canonical order. This model SHALL apply to repository sets of every supported size, including one member. Each member snapshot SHALL bind `HEAD`, branch, Git status, bounded worktree content, the complete relevant Git index entry set, and declared resources. Each repository observation SHALL contain at most 4,096 bounded snapshot paths and at most 12,288 raw index stage entries, and its index-enumeration command output SHALL contain at most 2 MiB. The existing 1 MiB output limit for every other Git command and every existing time, path-byte, index-entry-byte, per-file, total-content, action-payload, and text bound SHALL remain in force; no limit permits truncation.

The aggregate digest SHALL cover the complete wrapper excluding its own digest. The controller SHALL capture and compare two complete observations with identical resource requests before mutation. If any member is missing, invalid, unstable, over budget, truncated, changes between observations, or no longer matches persisted identity, the operation SHALL fail without appending a record or retaining partial evidence. Successful preflight SHALL seal this snapshot as the immutable ownership origin for the complete repository set. Every accepted later contract revision SHALL capture a complete aggregate `revision-source` as an interval anchor, but it SHALL NOT replace the preflight origin or erase still-material task ownership.

Every current snapshot and embedded repository value SHALL use the exact `0.4.0` schema required at its position. A bare member snapshot or another explicit non-`0.4.0` current input SHALL be rejected. The `0.4.0` runtime SHALL NOT discover, enumerate, read, load, replay, migrate, translate, repair, rewrite, or delete retained `0.2.0` namespace bytes.

#### Scenario: Repository-set preflight commits
- **WHEN** both complete observations match for every member
- **THEN** revision one appends exactly one preflight record containing one sealed repository-set snapshot and the task ownership baseline

#### Scenario: Later member fails capture
- **WHEN** an early member is captured but a later member fails or becomes unstable
- **THEN** the mutation commits no record or partial member evidence

#### Scenario: Earlier member changes during aggregate capture
- **WHEN** an earlier member changes before the second complete observation finishes
- **THEN** repository-set capture fails and task revision remains unchanged

#### Scenario: Caller order differs
- **WHEN** two starts supply the same canonical members in different orders
- **THEN** both derive the same member order and repository-set identity

#### Scenario: One-member snapshot uses the current wrapper
- **WHEN** a repository-backed operation runs for a task with one member
- **THEN** its top-level snapshot is the same repository-set wrapper used for every larger set and contains exactly one member snapshot

#### Scenario: Staged blob changes
- **WHEN** one member's staged blob changes while its `HEAD`, porcelain status, path, and worktree bytes remain unchanged
- **THEN** that member and aggregate snapshot digest change because the canonical index entry set is part of snapshot identity

#### Scenario: Member snapshot exceeds an index-aware bound
- **WHEN** one member observation would contain a 4,097th bounded path, a 12,289th raw index stage entry, or index-enumeration command output larger than 2 MiB
- **THEN** complete repository-set capture fails without truncation, partial member evidence, or a task mutation

#### Scenario: Non-current snapshot is supplied
- **WHEN** apply or current-namespace replay encounters a bare member snapshot or another explicit non-`0.4.0` snapshot schema
- **THEN** validation rejects the current input without loading it as authority, translation, migration, repair, fallback, or a new record

#### Scenario: Retained prior-version namespace exists
- **WHEN** retained `0.2.0` task or snapshot bytes remain in the prior-version namespace
- **THEN** the `0.4.0` runtime does not discover, enumerate, read, load, replay, migrate, translate, repair, rewrite, or delete those bytes

### Requirement: One Codex executes one current action across the complete set
Every repository-set task SHALL retain one task state machine, one lock, one revision sequence, one assurance plan, and exactly one projected current action for one Codex executor. Current action bindings SHALL bind the complete aggregate workspace observation, current canonical roll-forward task-change-manifest digest, assurance-plan digest, declared inputs, and any projected obligation; the manifest digest SHALL transitively bind its immutable preflight origin, applicable revision anchors, and ownership lineage. A source-producing action MAY claim changes in one or more members, but its successor SHALL observe every member and SHALL record one aggregate source plus one complete controller-derived task manifest. Context and assurance actions SHALL reject apply-time change to their bound task-owned slice, governing inputs, or required member observation. Ambient drift in any member SHALL be detected and reported separately and SHALL block repository-dependent assurance until it is restored or exactly adopted through an authorized contract revision. Apply SHALL use one revision compare-and-swap and append at most one task record.

A contract revision's complete aggregate revision source SHALL anchor only subsequent source-action intervals. Revision reconciliation SHALL roll the current assurance-facing manifest forward from the immutable preflight origin by retaining every still-material inherited task entry, adding every and only exactly adopted ambient-drift entry, and permitting later source successors to extend that lineage. A revision SHALL NOT silently drop inherited entries, rebase their ownership origin, or treat its interval anchor as a clean replacement baseline. The current manifest SHALL contain at most 4,096 net entries; the current impact report at most 128 entries; the current assurance plan at most 64 obligations; one review at most 64 findings; one assurance execution at most 64 evidence items; and one effective contract at most 256 total actions. None of these count ceilings or the existing payload and text bounds permits truncation.

#### Scenario: Action changes API and client
- **WHEN** one source-producing action claims contract-compatible changes in two members and the complete apply-time capture is stable
- **THEN** one apply mutation records one aggregate successor snapshot and repository-scoped manifest entries for both members

#### Scenario: Action changes one member
- **WHEN** one source-producing action changes only the API member
- **THEN** its successor snapshot still includes the unchanged client member while its task change manifest names only the claimed API paths

#### Scenario: Source action contains an unclaimed member change
- **WHEN** apply derives a changed path in any member that is absent from the submitted ownership claims
- **THEN** apply rejects the successor without recording or silently absorbing the path

#### Scenario: Read-only action observes task-slice drift
- **WHEN** a bound context or assurance action observes a change to its task-owned slice, governing inputs, or required member observation
- **THEN** apply rejects the action and writes no record

#### Scenario: Read-only action observes drift
- **WHEN** any member changes after a context or verification action was projected
- **THEN** apply rejects the action and writes no record

#### Scenario: Unrelated ambient drift is present
- **WHEN** a member differs from the latest accepted source outside a projected source-producing action
- **THEN** the projection identifies the member and paths as ambient drift and withholds repository-dependent assurance until the drift is restored or exactly adopted by an authorized contract revision

#### Scenario: Revision follows a multi-member implementation
- **WHEN** an implementation has produced still-material entries in one or more members and a later contract revision records a new aggregate revision source
- **THEN** the revision source anchors later intervals while the current manifest preserves the immutable preflight origin and every still-material implementation entry with its original ownership lineage

#### Scenario: Revision adopts drift in one member
- **WHEN** a contract revision exactly authorizes ambient drift in one member while prior task entries in either member remain material
- **THEN** its replacement current manifest carries every inherited task entry, adds every and only the adopted drift paths with revision provenance, and keeps all unchanged members in the aggregate source observation

#### Scenario: Another mutation wins
- **WHEN** another mutation commits after a repository-set action binding is issued
- **THEN** the earlier apply loses revision compare-and-swap and writes no per-member partial result

### Requirement: Repository-set verification is structured and complete
Every `verification.record` SHALL identify one current assurance-plan obligation and SHALL use `dev-flow-verification-coverage/0.4.0`. Coverage SHALL contain the obligation ID, exact effective criterion results, required repository results, an optional required integration result, commands or manual evidence, the task-change-manifest digest, impact-closure digest, and evidence limitations. Repository results SHALL exactly cover the member IDs required by that obligation; an integration result SHALL be present exactly when the obligation requires integration. Every result SHALL contain a non-empty bounded command or declared manual-evidence reference and a truthful status. One assurance execution SHALL contain at most 64 canonical evidence items, subject also to the existing shared 64 KiB action-payload and 8 KiB per-text limits; a 65th item or another existing payload or text violation SHALL reject the complete execution without truncation or a partial record. Assurance success SHALL require the obligation's criteria to be proven or covered by a current valid waiver. Members and integration outside the obligation SHALL be represented in the assurance plan and Dossier as not required with an explainable rule basis rather than fabricated passing results.

A read-only controller derivation that reuses current evidence SHALL consume no action or execution unit. A separately persisted evidence-reuse decision, waiver, finding disposition, or prerequisite refresh SHALL consume exactly one total-action unit and no verification, review, or source-rework execution unit.

#### Scenario: Required repository and integration verification passes
- **WHEN** the current obligation requires two members plus integration and every required result passes against the bound task capsule
- **THEN** one verification record satisfies that obligation and binds its criterion and impact coverage

#### Scenario: Complete repository-set verification passes
- **WHEN** every nested member result and the repository-set integration result pass and the aggregate `passed` value is true
- **THEN** one verification record binds that structured evidence to the current aggregate snapshot

#### Scenario: Obligation requires one affected member
- **WHEN** a validated plan requires a focused check for one changed member and no integration check
- **THEN** coverage contains exactly that required member, omits integration evidence, and records why other members and integration are not required

#### Scenario: Required member result is missing
- **WHEN** coverage omits a repository ID required by the current obligation or includes an undeclared ID
- **THEN** apply rejects the payload without advancing the task

#### Scenario: Member result is missing
- **WHEN** repository-aware coverage omits one repository ID or includes an unknown repository ID
- **THEN** apply rejects the payload without advancing the task

#### Scenario: Required integration result fails
- **WHEN** every required member result passes but a required integration result fails
- **THEN** the obligation remains unsatisfied and follows its bounded failure handling

#### Scenario: Integration result fails
- **WHEN** all member results pass but the integration result fails
- **THEN** aggregate `passed` must be false and successful completion remains unavailable

#### Scenario: Commands pass but a criterion remains unverified
- **WHEN** all required commands pass and one obligation criterion remains unverified without a current waiver
- **THEN** the valid attempt is recorded as unsuccessful assurance and consumes one absolute execution allowance

#### Scenario: One-member verification uses the current shape
- **WHEN** a one-member task has no cross-repository integration obligation
- **THEN** its coverage records the exact member obligation without duplicating the same command as synthetic integration evidence

#### Scenario: Verification exceeds its evidence-item bound
- **WHEN** one repository-set assurance execution submits a 65th canonical evidence item
- **THEN** apply rejects the complete execution without truncation, partial member evidence, a record, or allowance consumption

#### Scenario: Reuse is derived or persisted
- **WHEN** current evidence remains reusable for a repository slice
- **THEN** read-only derivation consumes no unit, while a separate persisted reuse mutation consumes exactly one total-action unit and no verification, review, or source-rework execution unit

### Requirement: Recovery and completion preserve exact membership
New task admission SHALL acquire the controller-data-directory membership lock and derive each cross-task lease identity from the member's canonical worktree root plus its worktree-specific Git administrative directory. Either component matching a member of another valid non-terminal current task SHALL reject the entire new repository set. A Git common directory SHALL remain same-task topology evidence rather than cross-task lease identity: distinct linked worktrees with different canonical roots and worktree-specific Git directories MAY be leased concurrently by different tasks even when they share one common directory, while two members of the same task that share one common directory SHALL still be rejected.

Before any new task is admitted, every entry in the current `0.4.0` inventory SHALL be validated sufficiently to establish immutable membership and controller-confirmed terminal state. Any corrupt or unreadable current entry SHALL make the complete lease inventory unavailable and all new admissions SHALL fail closed. The controller SHALL preserve the corrupt bytes, keep stored-ledger corruption diagnostics readable, and SHALL NOT infer a terminal state or lease release. This inventory check SHALL NOT inspect retained `0.2.0` namespace bytes.

Every repository-dependent projection, apply, contract revision, cancellation, and non-cancelled finalization SHALL validate all persisted canonical member roots, worktree-specific Git administrative directories, same-task Git-common topology, and active-task leases. A missing or moved root, canonical-root or worktree-specific-directory mismatch, newly duplicated same-task Git-common directory, overlapping root, or conflicting active owner SHALL block repository-dependent progress with member-specific diagnostics and SHALL NOT substitute another worktree. Pure stored-ledger inspection and stored diagnostics SHALL remain available when capture fails. Lease release SHALL be inferred only from a valid controller-confirmed `DONE`, `INCOMPLETE`, or `CANCELLED` task state, never from timeout, absence, capture failure, or corruption.

Successful completion SHALL require a current canonical roll-forward task-change manifest bound to the immutable preflight origin and all applicable revision anchors, no unresolved ambient drift, no unresolved `triage-required` finding or `impact-gap`, complete proven-or-validly-waived acceptance coverage, a present current result or valid waiver/reuse for every obligation required by the current assurance plan, and no obligation, aggregate, or total-action budget overrun. Evidence for a member or integration path that the current plan does not require SHALL NOT be fabricated or promoted to assurance. Missing, failed, stale, ambiguous, or exhausted required evidence, missing current obligations, unresolved governance states, or exceeded ceilings SHALL prevent `DONE` and remain visible in an `INCOMPLETE` Dossier and its projections.

#### Scenario: All obligations are current
- **WHEN** all member and integration verification passes against the current aggregate snapshot and coverage is complete
- **THEN** finalization may produce one `DONE` Delivery Dossier for the exact repository set

#### Scenario: One member lacks current proof
- **WHEN** every other member passes but one required member result is missing, failed, or stale
- **THEN** successful finalization is rejected and the member is identified in completion diagnostics

#### Scenario: Member is temporarily unavailable
- **WHEN** one persisted member root cannot be inspected
- **THEN** repository-dependent progress is blocked while the task ledger and current node remain unchanged

#### Scenario: Canonical member root is restored
- **WHEN** the user restores the valid leased worktree at the persisted canonical root and retries
- **THEN** the controller recaptures the complete set and resumes the same current action

#### Scenario: Distinct linked worktrees join different tasks
- **WHEN** two prepared linked worktrees have distinct canonical roots and distinct worktree-specific Git administrative directories but share one Git common directory
- **THEN** separate tasks may lease them concurrently because their cross-task lease identities differ

#### Scenario: One task requests duplicate common-directory members
- **WHEN** one new repository set contains two linked-worktree members that share one Git common directory
- **THEN** same-task topology validation rejects the complete repository set even though the members have distinct cross-task lease identities

#### Scenario: Another active task owns the worktree identity
- **WHEN** a requested canonical root or worktree-specific Git administrative directory matches a member of another valid non-terminal current task
- **THEN** admission rejects the complete new task and identifies the owning task and member without writing partial state

#### Scenario: Current inventory contains a corrupt task
- **WHEN** any current `0.4.0` inventory entry cannot prove its immutable membership and controller-confirmed terminal state
- **THEN** every new task admission fails closed, the corrupt bytes and stored diagnostics remain readable, and no terminal state or lease release is inferred

#### Scenario: Prior-version inventory bytes remain
- **WHEN** retained `0.2.0` namespace bytes coexist with a healthy current `0.4.0` inventory
- **THEN** current admission does not inspect those prior-version bytes and derives leases only from validated current entries

#### Scenario: Cancellation cannot capture one member
- **WHEN** cancellation is requested while one persisted member root cannot be captured safely
- **THEN** cancellation fails without changing the ledger, revision, status, current node, or lease

#### Scenario: Cancellation retries after restoration
- **WHEN** every canonical member root is again available and the current workflow stage declares cancellation
- **THEN** cancellation captures the complete set, appends one canonical cancellation record, and releases the task's active leases through terminal state

#### Scenario: All required obligations are current
- **WHEN** every current assurance-plan obligation is present and satisfied, validly reused, or validly waived, acceptance coverage is complete, no ambient drift, `triage-required`, or `impact-gap` remains, and all absolute ceilings are respected
- **THEN** finalization may produce one `DONE` Delivery Dossier for the exact repository set

#### Scenario: One required proof is missing
- **WHEN** a required member, integration, review, or manual obligation is missing, failed, stale, or exhausted
- **THEN** successful finalization is rejected and the exact unmet obligation is identified in completion diagnostics

#### Scenario: Review or planning governance is unresolved
- **WHEN** a blocking unknown-causality finding remains `triage-required` or a proven affected relation remains an unresolved `impact-gap`
- **THEN** projections and the Delivery Dossier expose that state and successful finalization rejects `DONE`

#### Scenario: An absolute ceiling is overrun
- **WHEN** replay derives consumption beyond a per-obligation, aggregate, or effective-contract total-action ceiling
- **THEN** successful finalization rejects `DONE` and the Delivery Dossier exposes the overrun and affected current obligations

### Requirement: Windows exact-set membership uses the canonical host path rule

On documented Windows x64 client systems, repository admission SHALL canonicalize every supplied local worktree root through the native Windows runtime path rule before deriving repository IDs, sorting members, checking duplicate roots, checking ancestor/descendant overlap, comparing controller-data separation, or acquiring active membership leases.

This Windows rule SHALL preserve the existing one-to-eight-member, order-insensitive, immutable exact-set model and SHALL add no platform-specific fields to `TaskState.repositories`.

#### Scenario: Caller order and Windows spelling differ

- **WHEN** two starts supply the same distinct Windows worktrees in different caller orders and use equivalent drive-case or separator spellings
- **THEN** both derive the same canonical member order and repository-set identity

#### Scenario: Windows members overlap

- **WHEN** one canonical Windows worktree root equals or contains another member root or the controller data root
- **THEN** task creation rejects the complete set before state is written

### Requirement: Windows aggregate capture retains all-or-none repository evidence

Repository-backed operations for Windows members SHALL capture the same current repository-set wrapper and one validated member snapshot per canonical task member. The controller SHALL retain its two complete aggregate capture passes and SHALL compare normalized Windows root, worktree Git directory, and common Git directory identities against immutable membership.

A failure or change in any Windows member SHALL fail the complete repository-set operation without committing early-member evidence.

#### Scenario: Two stable Windows members are captured

- **WHEN** both complete passes produce equal valid snapshots for every member
- **THEN** the controller accepts one canonical repository-set snapshot through the existing mutation path

#### Scenario: A later Windows member fails

- **WHEN** an earlier member is captured but a later member is missing, invalid, over budget, or unstable
- **THEN** the controller appends no record and retains no partial member evidence
