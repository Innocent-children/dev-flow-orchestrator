## ADDED Requirements

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
For every task, preflight and every repository-backed operation SHALL capture a `dev-flow-repository-set-snapshot/0.2.0` value containing the derived repository-set identity and one complete validated `dev-flow-workspace-snapshot/0.2.0` per member in canonical order. This model SHALL apply to repository sets of every supported size, including one member. Its aggregate digest SHALL cover the complete wrapper excluding its own digest. The controller SHALL capture and compare two complete observations with identical resource requests before mutation. If any member is missing, invalid, unstable, over budget, changes between observations, or no longer matches persisted identity, the operation SHALL fail without appending a record or retaining partial evidence. A bare top-level member snapshot or any other non-current snapshot schema SHALL be rejected.

#### Scenario: Repository-set preflight commits
- **WHEN** both complete observations match for every member
- **THEN** revision one appends exactly one preflight record containing one sealed repository-set snapshot

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

#### Scenario: Non-current snapshot is supplied
- **WHEN** replay or apply encounters a bare member snapshot or another unsupported snapshot schema
- **THEN** validation fails closed without detection, migration, repair, or fallback

### Requirement: One Codex executes one current action across the complete set
Every repository-set task SHALL retain one task state machine, one lock, one revision sequence, one retry budget per declared assurance node and effective contract, and exactly one projected current action for one Codex executor. Current action bindings SHALL use the canonical field set, and `starting_snapshot_digest` SHALL be the complete aggregate snapshot digest. A source-producing action MAY change one or more members, but its successor SHALL observe every member. A context or source-verification action SHALL reject drift in any member. Apply SHALL use one revision compare-and-swap and append at most one task record.

#### Scenario: Action changes API and client
- **WHEN** one source-producing action changes two members and the complete apply-time capture is stable
- **THEN** one apply mutation records one aggregate successor snapshot

#### Scenario: Action changes one member
- **WHEN** one source-producing action changes only the API member
- **THEN** its successor snapshot still explicitly includes the unchanged client member

#### Scenario: Read-only action observes drift
- **WHEN** any member changes after a context or verification action was projected
- **THEN** apply rejects the action and writes no record

#### Scenario: Another mutation wins
- **WHEN** another mutation commits after a repository-set action binding is issued
- **THEN** the earlier apply loses revision CAS and writes no per-member partial result

### Requirement: Repository-set verification is structured and complete
Every `verification.record` SHALL retain the pinned workflow's top-level payload fields and SHALL use one repository-set shape in its `coverage` object. That object SHALL contain exactly `schema`, `criteria`, `repositories`, and `integration`, with `schema` equal to `dev-flow-verification-coverage/0.2.0`. `criteria` SHALL exactly cover all effective criterion IDs with `proven` or `unverified`. `repositories` SHALL exactly cover all canonical repository IDs, including the sole ID of a one-member set, with each value containing only a non-empty bounded `command` and boolean `passed`. `integration` SHALL contain only a non-empty bounded `command` and boolean `passed`. The top-level `command` SHALL equal `integration.command`, and top-level `passed` SHALL equal the conjunction of every member result and the integration result. Assurance success SHALL additionally require every criterion to be proven or covered by a current valid waiver. A well-shaped command aggregate that passes while one or more criteria remain unverified and unwaived SHALL be recorded as an unsuccessful assurance attempt and follow the workflow's bounded failure or exhaustion route rather than being rejected as malformed.

#### Scenario: Complete repository-set verification passes
- **WHEN** every nested member result and the repository-set integration result pass and the aggregate `passed` value is true
- **THEN** one verification record binds that structured evidence to the current aggregate snapshot

#### Scenario: Member result is missing
- **WHEN** repository-aware coverage omits one repository ID or includes an unknown repository ID
- **THEN** apply rejects the payload without advancing the task

#### Scenario: Integration result fails
- **WHEN** all member results pass but the integration result fails
- **THEN** aggregate `passed` must be false and successful completion remains unavailable

#### Scenario: Commands pass but a criterion remains unverified
- **WHEN** every member and integration command passes, top-level `passed` is true, and one criterion is unverified without a current waiver
- **THEN** the valid verification attempt is recorded as unsuccessful assurance and follows the declared failure or exhaustion route

#### Scenario: One-member verification uses the current shape
- **WHEN** verification records evidence for a one-member repository set
- **THEN** coverage contains `criteria`, one exact repository result, and `integration` under the same schema used by every larger set

### Requirement: Recovery and completion preserve exact membership
Every repository-dependent projection, apply, contract revision, cancellation, and non-cancelled finalization SHALL validate all persisted canonical member roots. A missing or moved root, a canonical-root mismatch, a newly duplicated canonical Git common directory, or newly overlapping member roots SHALL block repository-dependent progress with member-specific diagnostics and SHALL NOT substitute another worktree. Persisted membership identifies canonical roots and does not claim to distinguish a repository-content replacement that preserves every persisted and observable membership field; such a replacement is handled as content drift. Pure stored-ledger inspection SHALL remain available when capture fails. Successful completion SHALL require a current aggregate snapshot, passing structured member and integration verification, and proven-or-validly-waived acceptance coverage. Missing, failed, stale, or ambiguous member evidence SHALL prevent `DONE` and remain visible in an `INCOMPLETE` Dossier.

#### Scenario: Member is temporarily unavailable
- **WHEN** one persisted member root cannot be inspected
- **THEN** repository-dependent progress is blocked while the task ledger and current node remain unchanged

#### Scenario: Canonical member root is restored
- **WHEN** the user restores a valid worktree at the persisted canonical root and retries
- **THEN** the controller recaptures the complete set and resumes the same current action

#### Scenario: Cancellation cannot capture one member
- **WHEN** cancellation is requested while one persisted member root cannot be captured safely
- **THEN** cancellation fails without changing the ledger, revision, status, or current node

#### Scenario: Cancellation retries after restoration
- **WHEN** every canonical member root is again available and the current workflow stage declares cancellation
- **THEN** cancellation captures the complete set and appends one canonical cancellation record

#### Scenario: All obligations are current
- **WHEN** all member and integration verification passes against the current aggregate snapshot and coverage is complete
- **THEN** finalization may produce one `DONE` Delivery Dossier for the exact repository set

#### Scenario: One member lacks current proof
- **WHEN** every other member passes but one required member result is missing, failed, or stale
- **THEN** successful finalization is rejected and the member is identified in completion diagnostics
