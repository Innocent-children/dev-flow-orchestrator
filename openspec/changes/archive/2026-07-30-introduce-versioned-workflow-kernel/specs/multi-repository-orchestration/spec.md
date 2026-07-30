## ADDED Requirements

### Requirement: Repository plans are versioned, canonical, and approval-bound
Every multi-repository execution SHALL use a task-local artifact conforming to
the package-owned `dev-flow-repository-plan/v1` schema. The plan MUST bind its
task and input revision, plan identity, monotonic map epoch, canonical
repository identities, exact selected repository set, dependency edges,
per-edge input and output interface-contract digests, approved paths, worktree
policy, concurrency policy, retry policy, and applicable integration commands
or evidence contracts. It MUST use the strict JSON value restrictions defined
by `dev-flow-bundle-identity/v1`; its canonical bytes are the corresponding
semantic JSON bytes, and its DAG digest is
`SHA256(b"dev-flow-repository-plan-v1\0" || U64BE(len(bytes)) || bytes)`.

Before map expansion, an explicit plan approval MUST bind the artifact identity
and byte digest, DAG digest, map epoch, canonical repository set, interface
contract digests, plan input revision, semantic-input digest, and approval
intent. The approval record SHALL separately record `approved_at_revision`,
which is an audit and CAS fact rather than a currentness dependency. Normal
approval, expansion, lease, result, barrier, and other workflow mutations MAY
advance the task revision without staling the plan. Telemetry MUST be written
only to a separate observational store and MUST NOT change task bytes, task
revision, durable outbox, guards, readiness, or plan currentness. A repository,
identity, edge, contract, path, policy, plan artifact, or another value
included in the semantic-input digest change MUST stale the approval and every
derived expansion; the controller MUST NOT patch an approved plan in place.

#### Scenario: Approve a complete repository plan
- **WHEN** a schema-valid plan names the exact current repositories, acyclic dependencies, interface contracts, paths, policies, map epoch, artifact digest, input revision, and semantic-input digest
- **THEN** the controller records one approval bound to all of those identities plus its distinct approval commit revision before any map child or worker lease is created

#### Scenario: Advance an unrelated task revision
- **WHEN** approval commit, map expansion, lease creation, result acceptance, barrier evaluation, or another workflow mutation advances revision without changing a semantic input bound by the approved plan
- **THEN** the approval and existing expansion remain current while normal CAS still uses the latest task revision

#### Scenario: Record observational telemetry
- **WHEN** an adapter records telemetry for a repository attempt at an observed task revision
- **THEN** only the separate observational store changes while task bytes, task revision, durable outbox, guards, readiness, and plan currentness remain exactly unchanged

#### Scenario: Reject an invalid plan graph
- **WHEN** a plan contains a self-edge, cycle, unknown repository, duplicate portable identity, duplicate edge, or contract reference absent from the task artifact set
- **THEN** plan validation returns a stable structured diagnostic and creates no approval, expansion, or lease

#### Scenario: Drift an approved repository or contract
- **WHEN** the selected repository set, canonical repository identity, dependency edge, interface-contract digest, approved path, or plan artifact changes after approval
- **THEN** the controller invalidates the approval and expansion and requires a new map epoch and explicit approval

#### Scenario: Replay expansion after a crash
- **WHEN** recovery reopens the same approved plan artifact, DAG digest, map epoch, and semantic-input digest after a crash even though the current task revision is later
- **THEN** it derives the same canonical repository children and does not create duplicate node identities

### Requirement: Repository dependencies form a deterministic pinned DAG
For every multi-repository task, the controller SHALL derive a directed acyclic graph from the approved, version-pinned workflow bundle and the approved repository plan. Every repository node and dependency edge MUST have a stable identity, and the controller MUST reject self-edges, cycles, unknown repositories, duplicate identities, and ambiguous dependency declarations before dispatching any worker. A node SHALL become ready only when every required predecessor has an accepted, current result satisfying the declared output contract. Agent output, worker completion order, runtime availability, and concurrency limits MUST NOT add, remove, or reinterpret dependency edges.

#### Scenario: Validate an acyclic repository plan
- **WHEN** an approved plan declares stable repository nodes and an acyclic set of cross-repository dependencies
- **THEN** the controller records the canonical DAG digest and derives the same ready-node set for the same task revision and accepted results

#### Scenario: Reject a dependency cycle
- **WHEN** repository dependencies form a direct or transitive cycle
- **THEN** the controller returns a structured graph-validation blocker and starts no repository worker

#### Scenario: Hold a downstream repository
- **WHEN** a repository node has a required predecessor whose result is absent, failed, stale, or not accepted
- **THEN** the downstream node remains non-ready even if a manager or worker requests its dispatch

#### Scenario: Ignore runtime completion order when evaluating dependencies
- **WHEN** independent repository workers finish in different orders across otherwise equivalent runs
- **THEN** the controller applies the pinned dependency edges and output contracts without inferring a new edge or readiness rule from that order

### Requirement: Repository map expansion and fan-out are stable and idempotent
A repository-map node SHALL expand only from the repository set recorded in the
current approved plan whose semantic-input digest still matches live bound
inputs; the expansion mutation itself uses the latest expected task revision
for CAS. Expansion MUST assign each child a stable node-instance identity
derived from the map node and canonical repository identity, order children
canonically, and persist the complete expansion before any child is dispatched.
Re-evaluating the same map input MUST return the existing expansion without
creating duplicate children. The scheduler MAY limit simultaneous workers, but
such a limit MUST affect only dispatch timing and MUST NOT change graph meaning,
node identity, or barrier membership.

Every repository dispatch SHALL use a separate indexed action-execution record
whose scope binds the exact node instance, repository, worktree, lease, paths,
and runtime resources. Disjoint scopes MAY claim and reach durable runtime
handoff concurrently. Overlapping scopes and `exclusive-task` actions MUST
conflict before effect. Dispatch receipts and later result acceptance remain
separate mutations; result and barrier commits SHALL remain serialized by the
latest expected task revision. A non-conflicting task revision may be rebased
only through the pinned `disjoint-scope-revalidate` policy and a fresh engine
candidate built from current state.

#### Scenario: Fan out independent repositories
- **WHEN** an approved map contains three dependency-ready repositories and the concurrency policy permits three workers
- **THEN** the scheduler may dispatch all three repository node instances concurrently with distinct stable identities

#### Scenario: Claim three disjoint dispatch scopes
- **WHEN** three ready workers bind distinct approved repository, node, worktree, lease, path, and runtime scopes
- **THEN** the journal index admits independent claims and durable handoffs without allowing any caller to bypass serialized task-state commits

#### Scenario: Reject a duplicate dispatch scope
- **WHEN** a second dispatch overlaps an active repository, node, worktree, lease, path, or runtime scope
- **THEN** index CAS rejects it before process launch and preserves the first execution record

#### Scenario: Partially dispatch before controller restart
- **WHEN** two repository executions are handed off, a third is claimed but uncertain, and the controller exits
- **THEN** recovery preserves the two runtime handles, observes or quarantines the claimed third effect without redispatch, and considers only genuinely unclaimed ready scopes for later dispatch

#### Scenario: Apply a lower concurrency limit
- **WHEN** three repository node instances are ready but the configured concurrency limit is two
- **THEN** the scheduler dispatches at most two at once and later dispatches the remaining instance without changing its identity or dependencies

#### Scenario: Resume map expansion after interruption
- **WHEN** the controller restarts after persisting map expansion but before all children are dispatched
- **THEN** it reuses the persisted child identities and dispatch state and does not create a second child for any repository

#### Scenario: Detect repository-set drift
- **WHEN** the discovered or requested repository set differs from the approved map input after expansion
- **THEN** the controller marks the expansion stale, blocks further dispatch, and requires a new approved plan rather than silently adding or removing children

### Requirement: Writable workers use distinct controller-owned worktrees
Every repository execution lane that permits writes SHALL bind to a worktree planned, claimed, materialized, and verified by the controller. Each bound worktree MUST be distinct from every source checkout, analysis worktree, other repository execution lane, and concurrently writable task worktree by canonical filesystem and Git identity. No two active write leases SHALL share a worktree. App-managed, agent-created, or otherwise unclaimed worktrees MUST NOT satisfy workspace readiness or result-evidence requirements. The controller MUST revalidate ownership, repository common-directory identity, branch, HEAD, cleanliness expectations, and durable claim before granting a lease and before accepting its result.

#### Scenario: Assign parallel repository worktrees
- **WHEN** two independent repository nodes become ready for writable execution
- **THEN** each worker receives a different controller-owned, verified worktree bound to its repository node instance

#### Scenario: Reject a shared writable worktree
- **WHEN** a proposed worker assignment would share a worktree with another active write lease
- **THEN** the controller rejects the assignment before dispatch and leaves both repository histories untouched

#### Scenario: Reject an externally created worktree
- **WHEN** a worker reports changes from a worktree that lacks the matching controller ownership claim
- **THEN** the controller rejects the result as out of scope and does not advance the repository node

#### Scenario: Detect worktree drift before result acceptance
- **WHEN** a leased worktree no longer has the recorded canonical identity, repository common directory, branch, HEAD relationship, or ownership claim
- **THEN** the controller blocks result acceptance and returns structured recovery evidence without automatically stashing, resetting, cleaning, committing, or deleting the worktree

### Requirement: Worker leases are scoped, exclusive, and revocable
Before starting a repository worker, the controller SHALL durably record a lease containing the task identity, workflow-bundle digest, node-instance identity, canonical repository and worktree identities, attempt generation, input evidence digest, allowed path and action scope, and lease nonce. Exactly one writable lease MAY be active for a node instance and worktree at a time. A worker MUST operate only within that lease and MUST NOT widen its own repository, path, tool, transition, or mutation authority. Revocation, supersession, cancellation, or attempt replacement SHALL invalidate the lease, and output produced under an inactive or mismatched lease MUST NOT be accepted.

#### Scenario: Start a scoped worker
- **WHEN** a repository node is ready and its worktree passes pre-dispatch validation
- **THEN** the controller persists the lease before dispatch and the worker receives only the repository, worktree, inputs, actions, and paths declared by that lease

#### Scenario: Attempt an out-of-scope change
- **WHEN** result evidence contains a changed path or repository outside the active lease scope
- **THEN** the controller rejects the result, records a structured scope violation, and does not advance the node

#### Scenario: Submit a result from a superseded attempt
- **WHEN** a worker submits output using a nonce or attempt generation replaced by a retry lease
- **THEN** the controller classifies the output as late or orphaned and performs no task-state transition

#### Scenario: Try to create a second writer
- **WHEN** a manager requests another writable lease for a node instance or worktree with an active write lease
- **THEN** the controller refuses the second lease unless the first lease has been durably revoked and reconciled

### Requirement: The controller and manager preserve single-writer authority
The controller SHALL remain the only component that persists task state, node state, evidence acceptance, barrier status, and workflow transitions. Within the agent plane, only the designated manager role SHALL be authorized to request mutating controller operations. Repository workers MUST receive read-only controller capabilities and MUST return candidate results to the manager rather than writing state files, advancing nodes, accepting evidence, or invoking mutating controller tools. Manager requests MUST still satisfy controller locks, expected-revision checks, guards, approvals, and evidence contracts; manager designation MUST NOT bypass kernel policy.

Every agent-plane mutation through CLI or MCP MUST additionally present a
short-lived manager capability issued by the controller for one task, manager
session, permitted action set, and expiry. The controller SHALL generate at
least 256 bits of randomness, persist only a verifier plus issuance,
revocation, and request-nonce state, accept the plaintext proof only through a
manager-scoped secret channel rather than command arguments or logs, and reject
missing, expired, revoked, cross-task, cross-session, replayed, or
action-mismatched proofs before acquiring mutation authority. Worker
assignments and lease credentials MUST NOT contain or inherit the manager
proof; a lease credential can identify candidate output but grants no
transition, approval, cancellation, evidence-acceptance, or result-acceptance
operation.

This capability requirement applies to schema-v3 orchestration mutations;
schema-v1/schema-v2 CLI behavior remains under its frozen compatibility
contract. The standard-library CLI SHALL provide an explicit local operator
authorization and revocation path so recovery does not depend on MCP or an SDK.
Issuance itself MUST be confirmation-gated, audited, excluded from model or
worker output, and unable to bypass any workflow guard.

Writable native-worker dispatch is supported only when the host adapter can
prove that the worker sandbox and tool set exclude the controller data
directory, direct task-state paths, manager secret channel, and mutating
controller tools while permitting the assigned worktree. If the host cannot
provide that separation, the controller MUST fail closed for parallel writable
worker dispatch or fall back to manager-owned serial execution. Filesystem
isolation is a host boundary, not a claim made by Python code alone; out-of-scope
worktree effects are additionally detected at result and integration evidence
validation and never accepted as workflow success.

#### Scenario: Worker completes implementation
- **WHEN** a repository worker finishes its assigned implementation and tests
- **THEN** it returns a candidate structured result to the manager and does not directly mutate task or node state

#### Scenario: Worker requests a transition
- **WHEN** a repository worker attempts to invoke a mutating transition or evidence-acceptance operation
- **THEN** the operation is denied before state persistence and the worker result remains unaccepted

#### Scenario: Worker knows the controller and task identity
- **WHEN** a worker running as the same operating-system user can locate the controller and knows the task ID and current revision but has no manager capability
- **THEN** CLI and MCP mutation requests are rejected before state persistence, approval changes, lease changes, or event delivery

#### Scenario: Replay a manager capability request
- **WHEN** a caller repeats an already consumed manager request nonce or uses a proof outside its task, session, action, or expiry scope
- **THEN** the controller returns a stable capability error and commits no state or event

#### Scenario: Authorize CLI-only recovery
- **WHEN** an operator uses the standard-library CLI without MCP or an SDK and explicitly confirms a scoped schema-v3 recovery session
- **THEN** the controller issues a manager capability through the local secret channel and every subsequent mutation still requires normal revision, evidence, approval, and recovery checks

#### Scenario: Host cannot isolate a writable worker
- **WHEN** an adapter cannot prevent a worker from reading the manager secret channel or controller data directory or from discovering mutating tools
- **THEN** the controller does not dispatch that parallel writable worker and reports the supported manager-serial fallback

#### Scenario: Manager submits an authorized result
- **WHEN** the designated manager submits a valid candidate result with the current expected revision
- **THEN** the controller independently validates the result and performs the permitted mutation under its task lock

#### Scenario: Manager attempts to bypass a gate
- **WHEN** the manager requests a transition lacking required current evidence or approval
- **THEN** the controller rejects the request exactly as it would reject any other unauthorized caller

### Requirement: Every orchestration operation uses the unified engine-proof boundary
The package SHALL maintain an exhaustive, catalog-sealed orchestration
operation matrix covering repository-plan proposal and approval, map expansion
and invalidation, frontier readiness, assignment, lease issue/revoke/expiry,
dispatch, stop, reconciliation, recovery, retry, timeout, cancellation,
result acceptance and invalidation, barrier closure and reopening, integration
capture and verification, independent review, finalization, and
manager-capability issue/revoke. Each operation-specific validator SHALL
produce a typed `ActionOutcome` for an exact same-node action edge, and the
common transition engine SHALL generate and consume the single-use commit
proof. A specialized validator, manager capability, lease credential, or
request nonce is necessary evidence but MUST NOT itself become a parallel
state-commit authority.

Each matrix entry MUST use one stable action identity for one semantic
validator, canonical event, and write/effect set. Frontier advancement and
assignment issuance, and runtime recovery observation and attempt abandonment,
are distinct operations with distinct versioned action identities.
Schema-v1/schema-v2 aliases MAY remain only in their frozen adapters; a
schema-v3 catalog MUST NOT overload one action identity across those semantics.

Every proof MUST bind task, revision, workflow bundle, operation, action edge,
candidate digest, manager authorization when required, and event batch. Missing
or mismatched proof and proof replay MUST leave task bytes, outbox, manager
nonce state, Git, worktrees, and external state unchanged. The manager request
nonce and its target business mutation SHALL be consumed in the same atomic
state/outbox transaction.

Capability issuance is the explicit bootstrap exception to possession of an
existing manager capability, not an exception to the engine. It requires the
local operator confirmation and secret-channel contract, task lock, expected
revision, exact `manager.authorize` action edge, and a fresh issuance nonce;
the engine atomically commits the verifier record and audit event. Revocation
uses its declared operator or current-manager proof and the same engine path.

#### Scenario: Apply a sealed orchestration operation
- **WHEN** an operation-specific validator accepts a current plan, lease, result, barrier, integration, review, recovery, or manager-registry outcome
- **THEN** the unified engine reevaluates its exact catalog action edge and atomically consumes both the manager request nonce and one single-use commit proof with the business mutation and audit batch

#### Scenario: Reject a forged orchestration proof
- **WHEN** an orchestration request omits the proof, changes its task, revision, bundle, operation, action, candidate digest, or event binding, or replays a consumed proof
- **THEN** task bytes, pending and delivered outbox records, nonce state, Git, worktrees, and external systems remain unchanged

#### Scenario: Bootstrap a manager capability
- **WHEN** a local operator explicitly confirms capability issuance for a current schema-v3 task without already possessing a manager capability
- **THEN** the declared bootstrap action validates the operator and secret channel, expected revision, task lock, and fresh issuance nonce before the engine atomically records the verifier and audit event

#### Scenario: Reject nonce consumption without the target mutation
- **WHEN** a crash, invalid candidate, or stale engine proof prevents an authorized orchestration mutation
- **THEN** the manager request nonce is not consumed separately and the caller may safely retry only according to the same current authorization contract

#### Scenario: Reject an overloaded orchestration action identity
- **WHEN** a schema-v3 catalog assigns one action identity to frontier advancement and assignment issuance or to runtime recovery observation and attempt abandonment
- **THEN** catalog sealing fails and requires separate versioned action, validator, event, and write/effect contracts

### Requirement: Worker results use a versioned evidence-bound contract
Every worker result SHALL conform to a versioned structured schema and MUST identify the task, workflow bundle, map epoch, node instance, repository, lease nonce, attempt generation, and unique result ID. The result MUST report a terminal or waiting outcome, input evidence digest, resulting worktree and Git identities, changed-path manifest, executed verification summary, blocker and plan-drift declarations, and content-addressed references for detailed logs or artifacts. Free-form summaries and worker assertions MUST NOT substitute for controller-verifiable evidence. The controller SHALL reject malformed, unsupported, mismatched, stale, or unverifiable results without partially accepting their fields.

#### Scenario: Collect a successful worker result
- **WHEN** a worker returns a schema-supported result whose lease, inputs, worktree evidence, changed paths, and test artifacts all match the current node instance
- **THEN** the manager may submit it and the controller records the accepted result and artifact references without embedding raw logs in the task projection

#### Scenario: Reject a stale input digest
- **WHEN** a worker result was produced from an input evidence digest that is no longer current
- **THEN** the controller rejects the result as stale and does not mark the node successful

#### Scenario: Reject an unsupported result contract
- **WHEN** a worker result declares a schema version newer than the controller supports
- **THEN** the controller returns a structured compatibility blocker and preserves task state unchanged

#### Scenario: Report plan drift
- **WHEN** a worker discovers that implementation requires a repository, path, dependency, or behavior outside the approved plan
- **THEN** the result records plan drift, the node does not complete successfully, and the controller routes the task to the declared re-planning path

### Requirement: Fan-in barriers close only over current accepted results
A fan-in barrier SHALL persist its required child membership from the canonical map expansion and SHALL close only when every required child has an accepted terminal outcome allowed by the barrier policy. Missing, running, failed, blocked, cancelled, stale, or unaccepted required results MUST keep the barrier open unless the pinned workflow explicitly declares an alternative or optional outcome. On closure, the controller MUST produce a canonically ordered aggregate containing child result IDs, repository evidence digests, artifact references, and a barrier digest. Worker completion order MUST NOT change this aggregate. Any later invalidation of a member result SHALL stale the barrier and every downstream result that depends on it.

#### Scenario: Close a successful repository barrier
- **WHEN** every required repository child has a current accepted success result
- **THEN** the controller closes the barrier with a canonical aggregate and makes its declared downstream node ready

#### Scenario: Keep a barrier open after a failure
- **WHEN** one required repository child fails and the workflow declares no accepted failure alternative
- **THEN** the barrier remains open and no integration or completion node depending on it becomes ready

#### Scenario: Aggregate out-of-order completions
- **WHEN** repository workers finish in a different order from their canonical node identities
- **THEN** the closed barrier orders members canonically and produces the same digest for the same accepted result set

#### Scenario: Invalidate a closed barrier member
- **WHEN** a repository result used by a closed barrier becomes stale because its worktree or upstream evidence changes
- **THEN** the controller marks the barrier and dependent integration or review evidence stale before another transition can use them

### Requirement: Concurrent results are committed through serialized idempotent CAS
The manager MAY collect worker results concurrently, but SHALL submit result-acceptance mutations to the controller one at a time in canonical node-instance order for the applicable fan-out epoch. Each mutation MUST name the expected task revision and unique result ID, and the controller MUST apply the state change and durable event atomically under the task lock. A revision conflict SHALL require the manager to reload state and revalidate the candidate result; it MUST NOT trigger a blind overwrite or an unconditional retry. Replaying an identical accepted result ID SHALL return its prior receipt without duplicating state or events, while replaying the same ID with different content MUST fail closed.

#### Scenario: Commit two concurrently completed results
- **WHEN** two repository workers finish concurrently
- **THEN** the manager orders their candidate results canonically and the controller accepts each in a separate expected-revision mutation

#### Scenario: Encounter a revision conflict
- **WHEN** another valid mutation changes the task revision before a candidate result is submitted
- **THEN** the controller rejects the stale expected revision and the manager reloads and revalidates before deciding whether to resubmit

#### Scenario: Replay an accepted result
- **WHEN** recovery resubmits the same result ID with byte-equivalent canonical content
- **THEN** the controller returns the original acceptance receipt and creates no duplicate node outcome or event

#### Scenario: Reuse a result ID with different content
- **WHEN** a caller submits different canonical content under an already observed result ID
- **THEN** the controller returns an idempotency conflict and performs no mutation

### Requirement: Failure and retry preserve attempt history and safety
A failed or blocked worker attempt SHALL be recorded with its lease generation, result or diagnostic, artifacts, and worktree evidence, and SHALL prevent dispatch of dependent nodes until the pinned workflow permits recovery. A retry MUST be authorized by an explicit retry policy or approval, increment the attempt generation, create a new lease nonce, and bind an explicit decision to resume the verified worktree or use a separately planned worktree. The controller MUST preserve prior attempt evidence and MUST NOT automatically stash, reset, clean, delete, commit, or otherwise rewrite a failed attempt's worktree. Results from earlier generations MUST remain non-current after retry begins.

#### Scenario: Record a failed repository attempt
- **WHEN** a worker returns a validated failure result
- **THEN** the controller records the failed attempt and artifacts, blocks dependent nodes, and preserves the worktree for inspection

#### Scenario: Retry within policy
- **WHEN** the retry policy permits another attempt and the manager supplies the current expected revision
- **THEN** the controller records a new attempt generation and lease after revalidating the explicitly selected worktree strategy

#### Scenario: Exhaust the retry policy
- **WHEN** a failed node has reached its allowed attempts and no overriding approval exists
- **THEN** the controller refuses another dispatch and reports the node as requiring re-planning, manual recovery, or task cancellation according to the workflow

#### Scenario: Retry from a drifted failed worktree
- **WHEN** a requested retry would reuse a failed worktree whose evidence differs from the recorded failed-attempt evidence
- **THEN** the controller blocks the retry until the drift is explicitly inspected and incorporated into a new approved recovery plan

### Requirement: Cancellation revokes dispatch authority and reaches quiescence safely
Task or fan-out cancellation SHALL be an expected-revision, approval-gated
controller transition. Once cancellation intent is persisted, the scheduler
MUST stop issuing new leases, revoke applicable active leases, request runtime
termination where supported, and reject later outputs from those leases. The
controller MUST distinguish cancellation requested from cancellation
quiesced. Lease expiry revokes logical authorization and rejects new results or
dispatch, but expiry alone MUST NOT prove that an agent or process stopped
writing.

Cancellation intent, runtime stop, and quiescence reconciliation SHALL use
catalog-declared kernel-priority control child records cross-linked to the
target indexed execution or runtime handle. Their overlap with the exact target
scope is permitted only for the declared control action; an ordinary effect
cannot claim that exception. Control records have their own authorization,
nonce, per-effect claim, receipt, engine proof, and audit event and MUST NOT
block or widen unrelated repository scopes.

An affected lease MAY become quiesced only after either (a) an authenticated
runtime stop/exit observation from the same process, job, thread, or host
assignment plus a post-stop worktree observation, or (b) explicit
reconciliation that records why runtime identity cannot be observed, confirms
termination or operator-controlled isolation, captures two equal complete
worktree and Git postcondition snapshots separated by the configured stability
interval measured by a monotonic clock, and finds no active writer or mutation
quarantine. The deterministic kernel SHALL enforce a positive minimum
stability interval that no bundle, workflow, task, or ordinary configuration
can reduce to zero. Failure to
terminate or prove either path MUST keep the lease uncertain and block
replacement leases, barriers, integration snapshots, and completion.
Cancellation MUST preserve task data, attempt history, artifacts, branches,
and worktrees and MUST NOT perform implicit cleanup or Git mutation.

#### Scenario: Cancel while workers are running
- **WHEN** an approved cancellation is committed while repository workers hold active leases
- **THEN** no new worker is dispatched, the active leases are revoked, termination is requested, and the task remains non-quiesced until every lease is reconciled

#### Scenario: Admit stop despite the target execution scope
- **WHEN** an authorized stop control record names one running worker whose active execution owns the same worktree and runtime scope
- **THEN** the kernel permits only that target-bound control overlap, records its independent receipt, and continues to reject ordinary overlapping effects

#### Scenario: Receive output after revocation
- **WHEN** a revoked worker later submits a nominally successful result
- **THEN** the controller records or quarantines it as late diagnostic output and does not accept it into the workflow

#### Scenario: Finish cancellation reconciliation
- **WHEN** all affected leases have an authenticated stop plus post-stop evidence or have completed explicit stable reconciliation
- **THEN** the controller may mark cancellation quiesced while leaving worktrees and evidence available for explicit recovery or cleanup

#### Scenario: Lease expires while its worker remains live
- **WHEN** a lease reaches its policy expiry but the associated worker continues writing its worktree
- **THEN** the controller rejects its results, keeps the lease non-quiesced, and blocks replacement dispatch, barriers, and integration capture

#### Scenario: Runtime termination fails
- **WHEN** cancellation requests termination but authenticated stop cannot be established and stable reconciliation is incomplete
- **THEN** the controller records the uncertain runtime and leaves cancellation non-quiesced without claiming a clean integration snapshot

#### Scenario: Late output races integration capture
- **WHEN** revoked or expired worker output or worktree drift appears during or after a proposed integration snapshot
- **THEN** the snapshot is rejected or marked stale and cannot satisfy integration or completion gates

#### Scenario: Request cancellation with a stale revision
- **WHEN** the cancellation request names an outdated task revision
- **THEN** the controller rejects it without revoking leases or changing task state

### Requirement: Recovery reconciles durable orchestration state before redispatch
The controller SHALL persist enough orchestration state to recover the pinned
DAG, map expansion, node lifecycle, attempts, leases, accepted results, barrier
aggregates, idempotency records, and optional runtime handles after process or
host interruption. On recovery it MUST complete or quarantine any pending
durable state event before scheduling new work. A previously active worker MUST
be treated as uncertain until its runtime handle and worktree evidence are
reconciled; absence of an agent runtime process MUST NOT be treated as proof
that its worktree is clean, and presence of a runtime handle MUST NOT be treated
as proof that its result is valid. The controller MUST NOT create a replacement
writable lease until the prior lease is revoked and then proven quiesced by the
same authenticated-stop or explicit stable-reconciliation contract required by
cancellation. Revocation or expiry without that proof leaves the lease
uncertain.

A quarantined execution SHALL block its repository/node/worktree/lease scope,
dependent nodes, applicable barriers, integration, and finalization until its
versioned reconciliation closes. It MUST NOT automatically block an unrelated
disjoint repository scope unless the pinned dependency graph, shared contract,
task cancellation, or `exclusive-task` policy requires that propagation.

An `ABANDONED` closure for a repository execution SHALL use freshly captured
controller-owned live evidence bound to the exact repository, node, worktree,
lease, paths, runtime, containment, attempt, and current task/index/journal
revisions. Revocation, expiry, a missing handle, worker or manager assertion,
or a caller-supplied worktree snapshot MUST NOT prove abandonment. A
`COMPENSATED` closure SHALL require both the current pinned workflow
compensation gate and a host-owned bridge's opaque one-shot approval bound to
the exact compensation request and target immediately before its separately
journaled effect. Failure of either contract leaves the original dependency
closure and finalization blocked.

When the current Codex host cannot supply either trusted authority, the
required macOS recovery result SHALL be scope-blocking `UNRESOLVED` plus
bounded `dev-flow-v4-operator-intervention/v1`. Recovery SHALL ask the user to
inspect or operate and stop without redispatching a worker, compensating a
repository effect, creating a replacement lease, releasing a barrier, or
unblocking integration/finalization. A user, model, worker, manager, or caller
assertion MUST NOT prove quiescence or approval. A later authenticated original
runtime, verifiable stored receipt, or future trusted host authority MAY support
a fresh separately authorized attempt; the earlier packet is not proof.

#### Scenario: Recover before worker dispatch
- **WHEN** the controller restarts after persisting a lease but before confirming worker dispatch
- **THEN** it marks the lease as requiring reconciliation and does not blindly start a duplicate writable worker

#### Scenario: Reattach a live worker
- **WHEN** a persisted runtime handle can be authenticated as the same active lease and its worktree evidence remains valid
- **THEN** recovery may reattach monitoring without creating a new attempt or lease

#### Scenario: Recover an orphaned worker
- **WHEN** a prior runtime cannot be reattached or authenticated
- **THEN** the controller revokes or expires the lease, keeps it uncertain, preserves its worktree, and requires authenticated stop or explicit stable reconciliation before retry or redispatch

#### Scenario: Reject a replacement after revocation alone
- **WHEN** recovery has durably revoked a prior lease but has not proved authenticated stop or completed explicit stable reconciliation
- **THEN** the controller refuses every replacement writable lease for its node or worktree

#### Scenario: Recover an accepted result after receipt loss
- **WHEN** task state and its durable event contain an accepted result but the manager did not receive the receipt
- **THEN** resubmission of the identical result ID returns the prior receipt and downstream readiness is computed from the recovered accepted state

#### Scenario: Continue an unrelated scope beside quarantine
- **WHEN** one repository execution is quarantined but another ready repository has no dependency, shared contract, path, worktree, lease, or external-resource overlap
- **THEN** the second scope may continue under its own journal while barriers and finalization that depend on the quarantined scope remain blocked

#### Scenario: Abandon a repository attempt from live target evidence
- **WHEN** the controller's pinned recovery verifier proves the exact runtime/worktree/lease target quiescent and proves no accepted result exists in live target or authoritative controller state
- **THEN** reconciliation may record `ABANDONED` without redispatch while retaining the evidence bound to that repository attempt

#### Scenario: Infer abandonment from lease expiry
- **WHEN** a repository lease expires or its runtime handle disappears without current controller-owned target-bound live evidence
- **THEN** reconciliation remains unresolved and replacement dispatch, dependent nodes, barriers, integration, and finalization stay blocked

#### Scenario: Compensate a repository effect without both approvals
- **WHEN** either the pinned workflow compensation gate or the exact host-owned opaque one-shot approval is missing, denied, stale, mismatched, or replayed
- **THEN** no compensation effect starts and the original repository scope and dependency closure remain blocked

#### Scenario: Stop for operator intervention without trusted host authority
- **WHEN** recovery cannot authenticate the original repository runtime, verify a complete stored receipt, or obtain the exact host-owned compensation approval
- **THEN** it returns `UNRESOLVED` with the bounded intervention packet, asks the user to inspect or operate, and leaves the worker/lease scope, dependents, barriers, integration, and finalization blocked with zero automatic redispatch, compensation, replacement, or unblock

### Requirement: Integration verification and review bind the complete repository set
No multi-repository task SHALL become complete solely from per-repository worker success. After the repository barrier closes, the controller SHALL bind an integration snapshot containing every required repository result, canonical worktree and Git evidence, relevant interface or dependency artifacts, and the barrier digest. Integration verification MUST run against that exact snapshot with no active writable lease for its repositories. A final review MUST be independent from the implementation workers and MUST evaluate the complete changed surface, including tracked, staged, unstaged, and untracked content in every repository, cross-repository contracts, and current test evidence. Any repository drift or member-result invalidation SHALL stale both integration and review evidence and block completion.

#### Scenario: Verify an integrated multi-repository snapshot
- **WHEN** the repository barrier closes with current successful results and all associated write leases are quiesced
- **THEN** the controller records the exact integration snapshot and permits the declared cross-repository verification to run against it

#### Scenario: Find a cross-repository incompatibility
- **WHEN** integration verification finds that one repository's output violates another repository's expected contract
- **THEN** the integration node fails with evidence identifying the affected contracts and the workflow routes the affected nodes through its declared rework path

#### Scenario: Perform independent final review
- **WHEN** integration verification succeeds on the current snapshot
- **THEN** a reviewer distinct from the implementation workers examines every repository's complete change surface, cross-repository effects, and current verification evidence before completion may be approved

#### Scenario: Drift after integration verification
- **WHEN** any included repository changes after integration or review evidence was captured
- **THEN** the controller marks that evidence stale and requires a new barrier aggregate, integration verification, and final review as applicable before task completion
