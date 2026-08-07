# task-owned-change-capsules Specification

## Purpose
TBD - created by archiving change introduce-task-scoped-adaptive-assurance. Update Purpose after archive.
## Requirements
### Requirement: A task change capsule binds an exclusively leased repository set
Every task SHALL have one canonical task change capsule for its exact immutable repository set. During revision-zero creation, the controller SHALL hold the controller-data-directory membership lock, canonicalize and stably capture every requested member, and reject the complete start when any canonical worktree root or worktree-specific Git administrative directory is leased by another non-terminal current task. A successful creation SHALL atomically persist the task membership from which all member leases are derived; it SHALL NOT use an independently editable lease registry or lease expiration. Each lease SHALL remain active from successful task creation through the same task's controller-confirmed transition to `DONE`, `INCOMPLETE`, or `CANCELLED`. A lease conflict SHALL identify the owning task and member, and failure for any requested member SHALL leave no new task state or partial lease. Distinct linked worktrees MAY be leased by different tasks because their roots and worktree-specific Git directories differ, even when they share one Git common directory; duplicate Git-common identity inside one task remains rejected by repository-set topology validation.

#### Scenario: Task acquires every requested member
- **WHEN** a caller starts a task for a valid repository set whose canonical roots and worktree-specific Git directories are not leased by another active task
- **THEN** one revision-zero task is created atomically and its task change capsule has lease authority over every canonical member

#### Scenario: One member is already leased
- **WHEN** any requested root or worktree-specific Git directory belongs to another valid non-terminal task
- **THEN** the controller rejects the entire start, reports the owning task and member, and persists neither a new task nor a lease for any requested member

#### Scenario: Concurrent starts request the same member
- **WHEN** two task starts race for repository sets containing the same canonical member
- **THEN** the membership lock permits exactly one revision-zero creation and the losing start reports the committed owner

#### Scenario: Owning task becomes terminal
- **WHEN** the owning task reaches controller-confirmed `DONE`, `INCOMPLETE`, or `CANCELLED`
- **THEN** the controller SHALL allow a later valid task start to acquire the former member after repeating all current admission checks

#### Scenario: Controller restarts while a task is active
- **WHEN** a controller reloads valid non-terminal task state after restart
- **THEN** it derives the same active leases from immutable membership and terminal status without extending, expiring, or duplicating lease authority

#### Scenario: Separate linked worktrees are used concurrently
- **WHEN** two starts use distinct prepared linked worktrees that share a Git common directory but have different canonical roots and worktree-specific Git directories
- **THEN** each task may acquire its own worktree lease without weakening the rule that one task cannot contain duplicate Git-common members

#### Scenario: Current lease inventory contains corrupt state
- **WHEN** any entry in the current model `0.4.0` namespace cannot prove valid immutable membership and a controller-confirmed terminal state
- **THEN** task admission fails closed for the current inventory, preserves the corrupt bytes, reports diagnostics, and does not treat the entry as a released lease

### Requirement: Preflight seals an exact three-plane ownership baseline
The first post-creation mutation SHALL seal one immutable preflight ownership origin for the complete leased repository set using `dev-flow-repository-set-snapshot/0.4.0`. For each member, the baseline SHALL bind repository identity; canonical worktree root and worktree-specific Git administrative directory; Git common directory as repository-topology evidence; resolved `HEAD` state and symbolic branch or detached state; porcelain status; bounded worktree observations; the canonical Git index entry set and immutable `HEAD`-tree entry relevant to every changed, untracked, or declared-resource path; and every declared governing resource. Index entries SHALL preserve stages zero through three, Git mode, and object ID for regular files, symbolic links, and gitlinks. Worktree observations SHALL preserve path, kind, mode, and content or link-target digest; the controller SHALL permit a clean tracked path to be represented by proven equality to its bound `HEAD`-tree and index entry. Each repository observation SHALL contain at most 4,096 bounded snapshot paths and 12,288 raw stage entries, and the index-enumeration command SHALL produce at most 2 MiB; these limits do not raise the existing 1 MiB limit for other Git commands. No limit permits truncation. The controller SHALL derive all observations and digests, capture two identical complete repository-set observations, and reject preflight without a record if any member, path enumeration, `HEAD`-tree entry, index entry, worktree entry, resource, or identity is unstable, unsafe, unsupported, truncated, or over budget. Pre-existing staged, unstaged, and untracked non-ignored content SHALL remain part of the environment baseline and SHALL NOT become task-owned merely because it is present at preflight.

#### Scenario: Task starts from a dirty worktree
- **WHEN** preflight observes stable pre-existing staged, unstaged, and untracked non-ignored paths in one or more members
- **THEN** their exact index and worktree identities are sealed in the baseline and no task-change-manifest entry attributes them to the task

#### Scenario: Staged content differs while worktree bytes match
- **WHEN** two observations have the same `HEAD`, porcelain status, path, and worktree bytes but different staged object IDs
- **THEN** their member and repository-set snapshot digests differ and preflight cannot seal them as one stable baseline

#### Scenario: Index contains unmerged stages
- **WHEN** a relevant path has stable index entries at stages one through three
- **THEN** preflight records those canonical entries for diagnosis and source successors, assurance records, and successful finalization remain blocked until the unmerged state is resolved

#### Scenario: One member changes during preflight
- **WHEN** any member's `HEAD`, index, worktree, status, declared resources, or repository identity changes between the two complete observations
- **THEN** preflight appends no record and retains no partial member baseline

#### Scenario: Caller supplies baseline fields
- **WHEN** an action payload attempts to provide authoritative baseline paths, Git object IDs, content digests, or aggregate identity
- **THEN** the controller rejects or ignores those values and uses only its bounded read-only observations

#### Scenario: Index enumeration exceeds its product bound
- **WHEN** one repository observation would contain a 12,289th raw stage entry or index output larger than 2 MiB
- **THEN** the complete capture fails without truncation, a partial baseline, or a task-state mutation

### Requirement: The controller derives a complete per-path task change manifest
For every task and effective contract, the task change capsule SHALL contain one canonical roll-forward `dev-flow-task-change-manifest/0.4.0` derived from the immutable preflight ownership origin, every accepted source action, every contract-revision reconciliation, and the latest accepted source artifact. A contract revision's aggregate `revision-source` SHALL anchor later source intervals but SHALL NOT replace the task ownership origin or remove still-material task changes. The current manifest SHALL contain every inherited task-owned entry whose after identity remains present, every exact ambient-drift entry explicitly adopted by an authorized revision, and every post-revision task-owned entry. Manifest entries SHALL be keyed by exact `(repository_id, repository-relative path)` and sorted canonically. Each entry SHALL contain the controller-derived change kind; original and current before and after worktree kind, mode, and content identity; before and after index entry sets; original producer or adoption record, later producer lineage, action and source intervals; contract-generation lineage; and the accepted bounded ownership classification, current acceptance-criterion IDs, and purpose. The agent SHALL supply only bounded ownership or revision-reconciliation claims naming candidate repository IDs and paths plus classification, criterion mapping, and purpose. Those candidate selectors SHALL NOT determine the authoritative manifest path set, before or after identities, change kinds, producer identity, canonical digests, or aggregate membership; the controller SHALL derive all of those fields.

Every source-producing apply SHALL compare its bound starting source with a stable complete apply-time observation and derive the exact set of paths changed during that interval. Submitted ownership claims SHALL cover that set exactly once, use the correct repository ID and path, reference only current contract criteria, and remain compatible with accepted scope. One source action SHALL contain at most 128 claims, and the current roll-forward manifest SHALL contain at most 4,096 net entries across the task; both remain subject to shared payload and path-byte limits, and neither may be truncated. An omitted, duplicate, unchanged, unknown-member, escaping, scope-incompatible, over-count, or over-size claim set SHALL reject the complete source successor without appending a record. When the binding, revision, contract, predecessor, and workspace remain current, the controller SHALL permit the same source action to be retried with corrected claims. A path whose claim expands accepted scope SHALL require a complete contract revision before the source successor can commit.

Every contract revision SHALL reconcile the current workspace against the prior current manifest and latest accepted source. It SHALL carry forward every still-material prior task-owned entry, require exact authorized adoption claims for every ambient path incorporated by the revision, update current after identities, and map every current entry to compatible criteria in the replacement contract. A missing inherited entry, unclaimed adopted path, silently changed identity, incompatible mapping, or unexplained disappearance SHALL reject the revision atomically. A path restored exactly to the immutable preflight origin MAY leave the current net manifest while its producer and reversion lineage remain historical.

#### Scenario: Source action changes two claimed paths
- **WHEN** a bound source-producing action changes exactly two paths and supplies one contract-compatible ownership claim for each derived `(repository_id, path)`
- **THEN** one apply record commits the aggregate successor and the controller appends the two derived entries to the cumulative task change manifest

#### Scenario: Source action omits one claim
- **WHEN** apply derives changes to two paths but the ownership payload claims only one
- **THEN** apply rejects the entire successor, records neither path as task-owned, and preserves the prior source authority

#### Scenario: Ownership payload claims an unchanged or foreign path
- **WHEN** a payload names a path that did not change in the bound interval, belongs to another member, escapes its declared root, or does not exist in task membership
- **THEN** exact claim validation rejects the action without changing the ledger or manifest

#### Scenario: Existing task change is reverted
- **WHEN** a later claimed source action restores a task-owned path exactly to its immutable preflight ownership origin on both index and worktree planes
- **THEN** the current manifest no longer reports a net change for that path while immutable producer and reversion records preserve its history

#### Scenario: Claim expands the accepted contract
- **WHEN** a derived changed path or its stated purpose cannot be mapped to the current contract scope and criteria
- **THEN** source apply fails and repository-dependent progress requires restoration or an authorized complete contract revision before that change can be owned

#### Scenario: Contract revision follows implementation
- **WHEN** a contract revision is accepted after task-owned source entries already exist and their bytes remain present
- **THEN** the replacement current manifest carries every entry forward with original producer lineage, current after identity, and replacement-contract criterion mapping

#### Scenario: Contract revision adopts exact ambient drift
- **WHEN** an authorized replacement contract supplies exact compatible adoption claims for all ambient paths present in its stable revision source
- **THEN** those paths enter the roll-forward manifest with drift and revision provenance instead of disappearing into the revision source baseline

#### Scenario: Source action exceeds its claim bound
- **WHEN** one source-producing action changes and claims a 129th path
- **THEN** apply rejects the complete action without truncating claims, recording ownership, or consuming a source transition

#### Scenario: Current manifest exceeds its net-entry bound
- **WHEN** a source action or contract reconciliation would create a 4,097th current net manifest entry
- **THEN** the complete mutation fails without dropping an inherited, adopted, or new task-owned path

### Requirement: Ambient drift is classified separately and blocks implicit absorption
The controller SHALL compare every repository-dependent observation with the latest accepted aggregate source and SHALL classify each Git-visible difference outside a successfully bound source-producing apply as ambient drift. Diagnostics SHALL identify the repository ID, path, changed `HEAD`, index, worktree, status, or governing-resource plane, the recorded source identity, and the current observed identity. Stable preflight dirt SHALL remain `baseline-environment`; committed claimed changes SHALL remain `task-owned`; and later unclaimed differences SHALL remain `ambient-drift`. A difference observed during a source-producing interval but omitted from its exact ownership claims SHALL fail that apply and SHALL appear as ambient drift on the next repository-dependent observation rather than being absorbed into the task manifest.

Unresolved ambient drift SHALL block repository-dependent planning, assurance execution, evidence reuse decisions, source finalization, and successful Dossier finalization. It SHALL NOT rewrite historical records or prevent read-only ledger inspection. Repository-dependent progress SHALL resume only after the user restores the latest accepted source exactly, records an authorized complete contract revision that binds the exact drift and establishes a new aggregate revision source, or explicitly cancels at a stage whose workflow contract permits cancellation. The controller SHALL NOT silently rebase the ownership baseline, infer task ownership from proximity in time, or treat unrelated-path drift as a reviewable task change.

#### Scenario: Unrelated file changes after accepted source
- **WHEN** a path outside the task manifest changes after the latest source record and no bound source-producing action owns it
- **THEN** the next repository-dependent projection reports exact ambient-drift diagnostics and withholds assurance actions

#### Scenario: Preflight dirt remains unchanged
- **WHEN** a dirty path sealed in the preflight baseline retains the same index and worktree identities throughout task work
- **THEN** it remains baseline environment, is excluded from the task change manifest, and does not by itself trigger task review or rework

#### Scenario: User restores ambient drift
- **WHEN** the user restores every ambient path and Git plane to the latest accepted aggregate source
- **THEN** the controller observes no unresolved ambient drift and SHALL resume eligibility for the same current action without adopting those paths

#### Scenario: User expands scope around exact drift
- **WHEN** the user authorizes a complete next contract that references the current drift and the controller captures a stable complete revision source
- **THEN** the revision adopts every exactly claimed drift path into the roll-forward task manifest, establishes a new interval and planning boundary, and preserves the earlier drift diagnosis and adoption authority historically

#### Scenario: Ambient drift remains at finalization
- **WHEN** all planned assurance obligations are otherwise satisfied but any member still has unresolved ambient drift
- **THEN** successful finalization is unavailable and the unresolved repository and paths remain explicit in task status

### Requirement: Capsule updates preserve complete multi-repository identity and history
Every task change capsule, baseline, revision source, source successor, manifest, and ambient-drift observation SHALL bind the task's exact canonical repository-set identity and include an explicit member section for every immutable member, including unchanged members. Repository-scoped paths and claims SHALL always carry a repository ID; a one-member task SHALL use the same shape and SHALL NOT infer an omitted default ID. Aggregate capsule and manifest digests SHALL cover canonical member order, each member's immutable ownership origin and current source identity, all inherited, adopted, and later per-path entries, and the effective contract. Capture and commit SHALL be all-or-none across the set: an unavailable, unsafe, unstable, over-budget, mismatched, or conflicting member SHALL prevent a capsule update and any partial evidence. Contract revision SHALL start a new contract-bound interval generation from one complete aggregate revision source while rolling every current task-owned entry into the replacement current manifest and retaining all prior generations and ownership history for replay. Valid replay SHALL derive the same active generation, roll-forward manifest digest, drift classification, and member leases.

#### Scenario: Only one member changes
- **WHEN** a source action in a three-member task owns paths only in the second member
- **THEN** the successor capsule contains all three members, the manifest identifies only the second member's changed paths, and no evidence is fabricated for the unchanged members

#### Scenario: One member fails during source capture
- **WHEN** two members are stable but a third becomes unavailable or changes during complete apply-time capture
- **THEN** the controller commits no source successor, ownership claim, manifest entry, or partial member observation

#### Scenario: One-member task records a claim
- **WHEN** a source action changes a path in a one-member task
- **THEN** its ownership claim and manifest entry include that member's explicit repository ID under the same schema used for larger sets

#### Scenario: Contract is revised
- **WHEN** an authorized revision records a complete aggregate revision source for the immutable repository set
- **THEN** a new contract-bound interval generation becomes current, its current manifest includes every inherited and adopted still-material entry, and every earlier baseline, manifest, producer, and drift record remains immutable history

#### Scenario: Task resumes after restart
- **WHEN** the controller replays a valid capsule history with multiple members and source actions
- **THEN** it derives byte-identical canonical member ordering, current manifest identity, ownership classifications, and unresolved drift status
