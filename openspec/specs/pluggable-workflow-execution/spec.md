# pluggable-workflow-execution Specification

## Purpose
TBD - created by archiving change introduce-versioned-workflow-kernel. Update Purpose after archive.
## Requirements
### Requirement: Nodes use explicit versioned execution contracts
Every executable node definition SHALL declare a stable node identifier and
contract version, node kind, typed inputs and outputs, referenced handler or
built-in behavior, required and produced evidence, context projection, approval
policy, effect classification, retry and recovery policy, and allowed state
writes as required by its node kind. The engine SHALL support deterministic
controller nodes, Codex worker nodes, external-tool nodes, barriers, and human
gates through the same node-instance contract. A bundle MUST NOT embed source
code, module names, shell commands, or executable expressions; it SHALL only
reference behavior already present in a sealed registry.

The declared execution contract SHALL identify the complete transitive
happy-path and recovery handler closure. That closure MUST include every
dispatch, observation, settlement, reattachment, control, live-target
evidence, acceptance, abandonment, compensation, containment, archive, and
unblock implementation reachable for the action. Recovery MUST NOT call a
semantics-bearing helper absent from the task-pinned bundle and handler
identity. For a host-owned approval bridge, the package-owned bridge interface,
request and receipt schemas, and adapter semantics are in the closure; opaque
host implementation internals remain host-owned and MUST satisfy that exact
identity-covered interface rather than becoming controller handlers.

#### Scenario: Add a node using an existing contract
- **WHEN** a new valid bundle declares a node kind and version whose referenced contracts are already registered
- **THEN** the engine validates and executes the node without adding a node-specific branch to the transition engine

#### Scenario: Reject executable content in a definition
- **WHEN** a node definition contains inline code, a module path, a shell command, or an executable condition instead of a registered contract reference
- **THEN** bundle validation rejects the node before it becomes executable

#### Scenario: Reject an unknown node kind
- **WHEN** a workflow refers to a node kind or contract version unsupported by the running engine
- **THEN** the engine returns a structured compatibility blocker and performs no node or task mutation

#### Scenario: Call an unpinned recovery helper
- **WHEN** recovery would dispatch to a validator, observer, reconciliation decision, package-owned compensation bridge adapter, containment closer, archive helper, or unblock operation outside the task-pinned transitive handler closure
- **THEN** recovery fails closed before that helper runs and leaves the original execution and affected scope blocked

### Requirement: Runtime registries are unique and sealed
The runtime SHALL maintain separate registries for commands, guards, reducers,
gates, and executors. Each registration MUST have a globally unique stable
identifier, contract version, implementation digest, declared authority, and
typed contract. Registration SHALL be permitted only from package-allowlisted
runtime modules during controller initialization. The controller MUST reject a
duplicate identifier-version binding with a different implementation and MUST
seal every registry before validating workflow bundles. After sealing, adding,
removing, or replacing a registration MUST fail for the lifetime of that
controller process.

Registration and bundle closure validation SHALL traverse recovery references
to a fixed point. A recovery handler's referenced live-evidence validator,
receipt observer, compensation planner or package-owned bridge-contract
adapter, control handler, containment closer, archive helper, or unblock
validator is itself a handler dependency whose exact implementation file set
and digest MUST be registered and covered by the bundle identity. The external
host's opaque approval implementation is not registered in-process; the
identity-covered adapter MUST reject a host that cannot enforce the declared
interface.

#### Scenario: Seal valid registries
- **WHEN** controller initialization completes with unique allowlisted registrations
- **THEN** all registries become immutable before the workflow catalog is validated

#### Scenario: Reject a duplicate implementation
- **WHEN** two implementations register the same identifier and contract version with different implementation digests
- **THEN** initialization fails deterministically and no workflow bundle is activated

#### Scenario: Attempt late registration
- **WHEN** a hook, Skill, external tool, target repository, or runtime callback attempts to register or replace behavior after sealing
- **THEN** the registry rejects the operation and preserves its original entries

#### Scenario: Omit a transitive recovery registration
- **WHEN** a registered action handler names a recovery dependency whose contract or exact implementation identity is absent from the sealed manifest
- **THEN** registry and catalog sealing fail before any task may activate or reconcile through that action

### Requirement: One transition engine owns all workflow movement
Every forward, rework, retry, skip, automatic, approval, failure, and terminal
workflow transition SHALL pass through one controller transition engine. For
each attempted transition the engine MUST acquire the applicable locks, reload
committed state, enforce the caller's expected revision, resolve the exact
pinned workflow bundle, verify the current task and node lifecycle, select one
declared edge, reevaluate guards, evidence, approval, and side-effect
preconditions, apply a bounded reducer, and commit the resulting revision and
durable event through the existing atomic state and outbox protocol. No command
handler, hook, Skill, agent, executor, or adapter MUST mutate workflow state
outside this engine.

Every schema-v3 business-state commit MUST consume one opaque,
non-serializable `EngineCommitProof` issued by the kernel while the required
locks are held. The proof MUST bind the canonical task directory and held-lock
capabilities, task/revision/bundle/edge identities, old and candidate state
digests, action outcome, event batch, and any verified receipt; it MUST be
authenticated by controller-start-private key material and a one-shot issuance
registry. A public `TransitionEvaluation`, serialized object, caller-created
mapping, copied context value, manager authorization, or matching digest MUST
NOT be sufficient to construct or replay it. Proofs MUST NOT be persisted
across restart; recovery reevaluates current facts to mint a fresh proof before
committing an already verified receipt.

#### Scenario: Apply a valid transition
- **WHEN** a declared edge is legal at the expected revision and every current guard, evidence, approval, and side-effect precondition succeeds
- **THEN** the engine commits exactly one next revision and its corresponding durable event through the existing transaction protocol

#### Scenario: Reject a direct state mutation
- **WHEN** a command, node handler, or adapter attempts to change workflow state without invoking the transition engine
- **THEN** the controller rejects or discards the candidate change and commits no revision

#### Scenario: Apply a same-node action
- **WHEN** a declared node action records evidence or another allowed task fact without changing the coarse task status
- **THEN** the catalog-derived immutable action edge, typed `ActionOutcome`, registered reducers, and the same transition engine authorize and commit the bounded change without advancing node lifecycle

#### Scenario: Reject an unproved same-node commit
- **WHEN** schema-v3 code presents a same-status candidate for persistence without a single-use proof from the task-pinned engine
- **THEN** the durable commit boundary rejects every business-state change even if generic manager authorization is otherwise valid

#### Scenario: Forge a public evaluation or context value
- **WHEN** a caller constructs a structurally valid public `TransitionEvaluation`, copies or invents the old commit-context mapping, or supplies all visible candidate digests without a live registered proof
- **THEN** the durable boundary rejects it with no revision, outbox, nonce, journal, or external-state change

#### Scenario: Recover after the proof process exits
- **WHEN** an effect has a verified durable receipt but the process that held its engine proof exits before task-state replacement
- **THEN** recovery reloads current state under the required locks, reevaluates every guard and binding, and mints a new one-shot proof without redispatching the effect

#### Scenario: Reevaluate a previously previewed transition
- **WHEN** evidence, approval, workspace state, the pinned bundle, or the task revision changes after a transition preview
- **THEN** apply reevaluates all current preconditions and rejects the stale preview without protected side effects

### Requirement: Transition selection is deterministic
Each graph edge SHALL have a stable identifier and explicit transition
classification. If more than one edge can be legal from a node, the caller MUST
select an edge identifier or the graph MUST define an unambiguous deterministic
priority. The engine MUST return a structured ambiguity blocker when multiple
eligible edges have equal precedence and MUST NOT rely on manifest insertion
order, language map order, natural-language interpretation, or an agent's
unstated choice. Automatic transitions MUST be explicitly classified and
limited to the controller's validated automatic-action policy.

#### Scenario: Select an explicit edge
- **WHEN** two user-selectable edges are legal and the caller supplies one current declared edge identifier
- **THEN** the engine evaluates and applies only that edge

#### Scenario: Reject equal-priority eligible edges
- **WHEN** multiple eligible automatic edges have equal declared precedence
- **THEN** the engine returns a structured ambiguity blocker and commits no revision

#### Scenario: Ignore manifest ordering
- **WHEN** semantically equivalent graph serialization changes only the order in which edges appear
- **THEN** legal-action selection and transition results remain unchanged

### Requirement: Schema-v3 public actions are catalog-exhaustive and node-exact
Every public schema-v3 mutation command and trigger SHALL resolve at its exact
current node to one identity-covered action edge declaring the stable action
and edge identifiers, public command, canonical audit event type, exact
handler, guards, reducers and gate, confirmation mode, allowed node-owned
writes, kernel-owned writes and invalidations, external-effect classification,
canonical concurrency class and effect scopes, dependency/parallel policy,
synchronous-quiescence or asynchronous-handoff settlement, accepted receipt
schema, dispatch and idempotency policy, target-bound control actions,
quarantine reconciliation/compensation, and recovery policy.
One action identity MUST map to exactly one semantic validator, event contract,
and write/effect set. Schema-v1/schema-v2 repeat behavior, generic artifact
kinds, aliases, or same-status transitions MUST NOT become an undeclared
schema-v3 fallback.

#### Scenario: Reject incomplete action policy
- **WHEN** a reachable schema-v3 node action omits its public command, event type, confirmation, write/effect set, scope/concurrency, settlement, receipt, dispatch, idempotency, control, quarantine closure, or recovery contract
- **THEN** catalog sealing and profile activation fail before any task can invoke the action

#### Scenario: Reject an action outside its declared node
- **WHEN** a schema-v3 caller repeats an action at a node where the pinned catalog does not declare that exact action edge, even though a frozen legacy command accepted such a repeat
- **THEN** the engine returns a stable placement error with no task, outbox, journal, Git, filesystem, registry, or external-system change

#### Scenario: Reject semantic action overloading
- **WHEN** one action identifier is assigned to different validators, canonical events, or write/effect sets at different placements
- **THEN** catalog sealing rejects the bundle and requires distinct versioned action identities

#### Scenario: Enforce a declared note guard
- **WHEN** a blocking, rework, reassessment, reopen, or cancellation edge declares a required operator note and the caller omits or supplies an empty note
- **THEN** the guard rejects the action before reducer evaluation or any protected effect

#### Scenario: Resume only the recorded blocked target
- **WHEN** a caller requests resume to a status other than the task's recorded `blocked.from_status`, or attempts generic resume from a lite safety/risk block whose current safety gate is unresolved
- **THEN** the engine rejects the action without changing the blocked record, task revision, or outbox

#### Scenario: Reject an undeclared artifact kind
- **WHEN** a schema-v3 caller submits a generic artifact kind not allowlisted by the current node action and evidence contract
- **THEN** the engine rejects it rather than persisting an arbitrary same-node artifact

### Requirement: Guards and reducers have bounded authority
A guard SHALL be a deterministic read-only function of its declared input
projection and MUST NOT modify state, files, Git, registries, or external
systems. A reducer SHALL produce a candidate state delta and event without
performing external side effects. Before commit, the engine MUST compute the
actual changed JSON Pointer paths and prove that they are a subset of the
node's validated `allowed_state_writes`. Node-level write permissions MUST
never include task identity, pinned workflow identity, committed revision,
approval records, evidence provenance, durable outbox state, quarantine state,
lock metadata, workspace ownership, or other kernel-protected fields. External
effects SHALL run only through separately authorized effect executors governed
by kernel recovery rules.

Only package-owned, statically inventoried guard and reducer implementations
MAY run in-process. New contracts MUST accept immutable canonical value
projections plus an explicit kernel capability object; a guard capability MAY
expose only declared read-only evidence queries, and a reducer capability MAY
expose no filesystem, Git, process, network, registry-registration, or commit
operation. Static registration validation MUST reject undeclared globals,
imports, implementation files, and capability requirements according to the
versioned handler audit policy. Legacy wrappers MAY call existing
kernel-controlled read-only evidence functions, but they remain trusted package
code and MUST be covered by equivalence tests.

The Python runtime is not an isolation boundary for arbitrary trusted code.
Therefore the controller SHALL NOT claim that it can detect every possible
side effect by an already-compromised package handler. Untrusted or
dynamically supplied logic MUST run as an external executor and return an
evidence candidate; it MUST NOT enter `GuardRegistry` or `ReducerRegistry`. If
the capability membrane, static audit, or post-evaluation state comparison
detects a contract violation, transition evaluation MUST fail closed and any
observable external uncertainty MUST enter the normal blocker or quarantine
path.

#### Scenario: Apply a bounded reducer
- **WHEN** a reducer changes only its declared node-instance result paths and returns a valid event
- **THEN** the engine accepts the candidate delta and continues normal transition validation

#### Scenario: Reject an undeclared write
- **WHEN** a reducer changes a path outside the node's validated allowed-write set
- **THEN** the engine reports the unexpected JSON Pointer path and commits neither the candidate state nor its event

#### Scenario: Reject a protected-field grant
- **WHEN** a bundle attempts to grant a node reducer permission to change revision, workflow identity, approvals, outbox, quarantine, or workspace ownership
- **THEN** bundle validation fails before the node can run

#### Scenario: Reject forbidden guard authority at registration
- **WHEN** a new guard declares or statically references a filesystem-write, Git-mutation, process, network, registry-mutation, or external-system capability
- **THEN** registry validation rejects the handler before any task can execute it

#### Scenario: Reject a guard state mutation
- **WHEN** an in-process guard or legacy wrapper mutates its supplied projection or another observable candidate-state value
- **THEN** immutable input enforcement or post-evaluation comparison fails the transition and commits neither state nor event

#### Scenario: Route untrusted logic out of the guard registry
- **WHEN** a workflow needs logic that cannot satisfy the package-owned in-process audit and capability contract
- **THEN** it uses an external executor whose output remains an untrusted evidence candidate until a package-owned guard validates it

### Requirement: Node-instance lifecycle is explicit and separate
Every node instance SHALL have exactly one lifecycle state from `PENDING`,
`READY`, `RUNNING`, `WAITING_APPROVAL`, `WAITING_EXTERNAL`, `BLOCKED`,
`SUCCEEDED`, `FAILED`, and `SKIPPED`. A new instance SHALL begin as `PENDING`
and become `READY` only after the engine proves its declared dependencies.
Only the transition engine SHALL change lifecycle state. `SUCCEEDED`, `FAILED`,
and `SKIPPED` instances MUST remain immutable; retry or rework MUST create a
new uniquely identified attempt linked to the prior attempt. Task lifecycle,
node lifecycle, and executor runtime handles MUST remain separate, and an
executor runtime status MUST NOT by itself advance a node or task.

#### Scenario: Make a dependent node ready
- **WHEN** all declared predecessor outcomes and required evidence for a pending node are committed and current
- **THEN** the engine moves that node instance from `PENDING` to `READY` through one recorded transition

#### Scenario: Wait for an external result
- **WHEN** a running node has durably dispatched external work but has no validated terminal result
- **THEN** its lifecycle becomes `WAITING_EXTERNAL` while the task and downstream nodes remain unadvanced

#### Scenario: Retry a failed node
- **WHEN** policy permits retry of a `FAILED` node and the retry is explicitly requested
- **THEN** the engine preserves the failed attempt and creates a new attempt with a distinct identity and recorded predecessor link

#### Scenario: Receive a runtime completion signal
- **WHEN** an agent thread, subprocess, or external tool reports completion for a running node
- **THEN** the engine treats the signal as a candidate result and does not mark the node `SUCCEEDED` until output, evidence, revision, and attempt identity validation succeeds

### Requirement: Node results are typed, current, and provenance-bound
Before accepting a node result, the engine SHALL validate it against the
node's pinned output schema and bind it to the task identity, current node
instance and attempt, workflow bundle identity, handler and executor contract
identities, input digest, expected revision or issued execution token, output
digest, actor, and evidence references. Required evidence MUST pass the
existing authenticity and currentness checks. Large logs, patches, and test
outputs MUST be stored as controller-managed artifacts and represented in node
state by content-addressed references. An agent assertion or external success
status MUST NOT substitute for required evidence.

#### Scenario: Accept a current typed result
- **WHEN** a result matches the pinned schema, current attempt token, handler and executor identities, input digest, and all required current evidence
- **THEN** the engine records the result provenance and permits the declared completion transition

#### Scenario: Reject a late result
- **WHEN** a result refers to an earlier attempt, stale revision, different bundle identity, or superseded execution token
- **THEN** the engine preserves it only as non-authoritative diagnostic input and does not change the current node lifecycle

#### Scenario: Deduplicate an identical result
- **WHEN** the same result identity and output digest are submitted again after being committed
- **THEN** the engine returns the existing receipt without incrementing revision or duplicating evidence and events

#### Scenario: Reject a conflicting replay
- **WHEN** a submitted result reuses an existing result or execution identity with a different output digest
- **THEN** the engine reports a provenance conflict and commits no state change

### Requirement: Side-effecting node execution is recoverable
Before dispatching node work that can change a repository, filesystem, or
external system, the engine SHALL durably record an execution intent bound to
the task revision, node attempt, input digest, authorized effect plan, and
executor contract. Completion SHALL require a validated receipt and
phase-appropriate postcondition evidence. After interruption or uncertain
executor status, recovery MUST inspect the durable intent, runtime handle,
receipt, and actual postconditions before retrying or completing the node.
The engine MUST NOT automatically replay an effect whose idempotency or
quiescence cannot be proven, and uncertainty MUST enter the existing durable
quarantine or blocker path before mutation locks are released.

The pre-effect execution intent and post-effect commit intent SHALL be
separate canonical contracts for schema-v3 tasks. The execution intent MUST bind the exact task,
revision, workflow, action, effect request, authorized paths, confirmation,
executor, idempotency identity, accepted result schema, postcondition schema,
and maximum permitted state/effect changes without depending on receipt-time
values.
Before starting the executor, the controller MUST atomically claim the first
eligible effect from the prepared intent for one dispatcher bound to one
attempt and idempotency identity. Every later effect has its own durable claim;
the first claim advances the global execution phase but does not pre-claim
later effects. No second caller may claim or dispatch the same effect. Only a
prepared authorization with no effect claim and no observed effect may be
withdrawn as unstarted.
After a synchronous executor is proven quiescent, or a package-owned
asynchronous runtime-dispatch executor reaches its declared durable handoff
point, a typed receipt MUST bind the same identities plus result and
independent postcondition observations before the engine may construct and
commit the final `ActionOutcome`. A durable handoff receipt MUST bind the
current lease, containment, runtime handle, stop/reconcile capabilities, and
launch postconditions; the worker lifecycle then remains separate from the
completed dispatch action. A same-node action, movement action, gate, or
specialized orchestration validator MUST NOT bypass this ordering merely
because its public command handler predates schema v3. If an exact-revision
policy sees revision drift, or any workflow identity, current guard, approval,
evidence, ownership, bound scope, or postcondition changes after dispatch, the
receipt and observations MUST be preserved in quarantine for explicit
reconciliation; the controller MUST NOT commit the stale candidate or
automatically replay the effect.
Any receipt that reports an undeclared path, broader effect, unsupported result,
or mismatched postcondition SHALL be quarantined and MUST NOT be retrospectively
authorized by a newly generated commit intent.

Before every schema-v3 effect, the controller SHALL persist a strict
`dev-flow-v3-action-execution-index/v1` at
`action-executions/index.json` and one strict
`dev-flow-v3-action-execution-journal/v1` at
`action-executions/active/<execution-id>.json` in the controller task
directory. Terminal journals SHALL be written to
`action-executions/archive/<execution-id>.json`. The index and journals MUST
reject unknown fields and use independent monotonic revisions. Journal updates
MUST compare execution identity, expected journal revision, and expected
record digest; index membership/scope updates MUST compare expected index
revision and index digest. The controller MUST reload and atomically write them
under the task lock plus every required repository, worktree, lease, or
registry lock.

Index/journal coordination MUST use a write-ahead protocol rather than assume
cross-file atomicity. Index CAS first reserves the scopes and stores
`pending_record_sha256`; the controller then atomically writes the active
journal and a second index CAS promotes that digest to `record_sha256` and
clears the pending value. No effect may be claimed or dispatched before
promotion. A pending value after interruption remains scope-blocking and
recovery MUST validate the old/new record before completing or quarantining the
update. Terminal closure MUST atomically write and verify archive bytes before
synchronous index removal or asynchronous runtime-reservation promotion; an
active file orphaned afterward may be deleted only when it exactly matches the
durable archive.

Each journal MUST bind the pre-effect task revision and state digest, pinned
workflow, action and handler, effect plan, concurrency class, canonical
repository/node/worktree/lease/path/external-resource scopes, confirmation,
operation and authorization fingerprints, request-nonce digest, principal,
verifier and candidate digests, safe effect inputs, idempotency identities,
effect dependencies, and parallel groups. It MUST NOT persist a raw nonce,
manager secret, or capability.

Index and journal canonical bytes SHALL use the strict semantic JSON rules
from `dev-flow-bundle-identity/v1`. For a journal, `core_bytes` are the
canonical bytes of the complete record excluding only top-level
`record_sha256` and `seal`, and:

`record_sha256 = SHA256(b"dev-flow-v3-action-execution-journal-record-v1\0" || U64BE(len(core_bytes)) || core_bytes)`.

For a manager-authorized journal:

`execution_key = HMAC-SHA256(manager_secret, b"dev-flow-v3-action-execution-journal-key-v1\0" || U64BE(len(task_id_utf8)) || task_id_utf8 || U64BE(len(execution_id_utf8)) || execution_id_utf8)`,

and:

`seal = HMAC-SHA256(execution_key, b"dev-flow-v3-action-execution-journal-seal-v1\0" || U64BE(len(core_bytes)) || core_bytes)`.

`manager_secret` SHALL be the exact UTF-8 bytes of the already validated
secret-channel value; task and execution identifiers SHALL use their
strict-NFC UTF-8 bytes. `execution_key` is the raw 32-byte HMAC output;
`record_sha256` and `seal` are lowercase hexadecimal.
The index uses the same construction with the
`dev-flow-v3-action-execution-index-record-v1\0` digest domain and no manager
seal. The nonpersistent engine proof uses strict semantic JSON and length
framing with a distinct `dev-flow-v3-engine-commit-proof-v1\0` HMAC domain and
controller-start-private key. Digest and seal fields MUST NOT cover themselves;
all hexadecimal digests and HMACs MUST be verified with
`hmac.compare_digest`. Recovery MUST reauthenticate through the manager
channel and derive the same execution key; a process-local random seal is
insufficient.

`exclusive-task` executions conflict with every ordinary effect.
Catalog-sealed `scoped` executions MAY coexist only when their repository,
node, worktree, lease, path, and external-resource scopes are disjoint. The
kernel SHALL compute conflicts and MUST NOT trust a caller's non-conflict
assertion. Effects in a declared parallel group MAY independently claim and
dispatch when their scopes are disjoint; other effects wait only for declared
predecessors. Task, result, and barrier commits remain serialized by the task
lock and expected-revision CAS.

An execution input revision is always audited. Exact-revision actions
quarantine on any revision change. A catalog-sealed
`disjoint-scope-revalidate` action MAY continue across only non-conflicting
revisions after the engine, under current locks and the latest revision, proves
that its target repository/node/lease, semantic guard projection, approval,
ownership, effect plan, and postconditions are unchanged and constructs a
fresh candidate from current state. It MUST NOT patch or commit the stale
candidate.

Each effect MUST have its own monotonic durable claim and phase. Global
execution progresses `PREPARED -> DISPATCH_CLAIMED -> RUNNING ->
(QUIESCED | HANDOFF_VERIFIED) -> RECEIPT_VERIFIED -> COMMITTED`; each effect
progresses `PLANNED -> CLAIMED -> RUNNING -> (QUIESCED |
HANDOFF_VERIFIED) -> VERIFIED`. `HANDOFF_VERIFIED` is legal only for a
declared asynchronous runtime-dispatch contract; synchronous Git, filesystem,
registry, and external writes require `QUIESCED`. `QUARANTINED` is an
absorbing fail-closed transition for the original effect phase. Recovery MUST
NOT redispatch an already claimed effect and MAY dispatch only an unclaimed
effect whose declared predecessors are reconciled.

Cancellation, stop, and runtime reconciliation SHALL use catalog-declared
kernel-priority control child records bound to one active execution or runtime
handle. Such a child MAY overlap only the target scope and only for its exact
control action, authorization, and bounded writes; it MUST NOT widen authority
or permit ordinary overlapping work. An archive failure keeps the affected
scope indexed and blocked but MUST NOT block unrelated disjoint repository
scopes.

The singleton legacy `mutation-quarantine.json` path and bytes SHALL remain
frozen for schema-v1/schema-v2. Schema-v3 child effects SHALL use strict
per-effect containment records at
`action-executions/containment/<execution-id>/<effect-id>.json`, each
cross-referencing journal schema, execution, effect, and claim identities. The
journal claim precedes the spawn-pending containment record, contained launch,
runtime binding, release, and either quiescence or declared asynchronous
handoff observation before receipt verification. Recovery MUST read both
records and MUST NOT independently archive a journal-linked containment
record. Direct filesystem and registry effects require the same pre-effect
journal claim even when no child process exists. Schema-v1 and schema-v2
containment marker path, bytes, and recovery precedence MUST remain frozen.

After an asynchronous handoff commit, the dispatch journal MAY be archived but
its index entry MUST be promoted to a runtime reservation binding the lease,
runtime handle, scope, containment record, and permitted stop/reconcile
actions. The reservation SHALL continue to reject ordinary overlapping work
until authenticated runtime exit or explicit quiescence reconciliation plus
the applicable result/cancellation event. Handoff or containment uncertainty
SHALL remain an indexed quarantine addressable only through target-bound
control and reconciliation records.

At `RECEIPT_VERIFIED`, the journal MUST persist the exact receipt, candidate
state, event-batch, and one-shot engine-proof digests. The final task-state
replacement MUST atomically commit the business mutation, manager request
nonce consumption when applicable, and audit event binding execution identity
and receipt digest. The journal reserves but does not independently consume
that nonce. Task state and its pending or delivered outbox are authoritative
if a crash occurs after replacement; recovery finishes the journal without
redispatch. Before replacement, recovery requires reauthorization and current
guard, ownership, registry, and postcondition validation against the stored
receipt.

The original effect phase SHALL remain `QUARANTINED`. Closure SHALL use
separate, versioned reconciliation attempts indexed as target-bound control
children, each with a fresh identity and
monotonic `PREPARED -> CLAIMED -> (ACCEPTED | ABANDONED | COMPENSATED |
UNRESOLVED)` phase. Every attempt MUST bind the quarantined execution and
receipt digests, expected task/index/journal revisions, exact recovery action,
current operator-or-manager authorization, pinned recovery gate, fresh nonce,
and one-shot engine proof. An unresolved attempt MUST leave the original
execution indexed and scope-blocking and MUST NOT prevent a later,
independently authorized attempt.

`ACCEPTED` SHALL reuse the stored receipt without dispatch only after current
postconditions and the pinned recovery policy permit a fresh engine evaluation
and atomic task/event/nonce commit.

`ABANDONED` SHALL require fresh controller-owned, target-bound live evidence
produced by the task-pinned transitive recovery handlers while the required
locks and target authority are current. The evidence MUST bind the original
execution, effect and attempt, runtime/containment identity, exact
repository/worktree/path/external-resource target scopes, current
task/index/journal revisions, observation source and time, and live
postcondition digest. It MUST prove either that the claim was never released
and no invocation or effect occurred, or that the exact target is quiescent and
neither controller state/outbox nor the live target contains an accepted
business outcome. A missing or unauthenticated runtime handle, process absence,
lease expiry, idempotency key, stale receipt, caller-provided snapshot, or
worker/operator/model assertion MUST NOT satisfy this proof. Unavailable,
incomplete, stale, or mismatched live evidence SHALL produce `UNRESOLVED`, not
`ABANDONED`.

`COMPENSATED` SHALL require a package-declared versioned compensation action
and a current successful pinned workflow gate. The compensation action SHALL
have its own journal or target-bound control record, claim, receipt, and engine
commit. Immediately before its exact provider, Git, filesystem, or registry
invocation, a host-owned bridge MUST consume an opaque, non-serializable,
expiring, one-shot host approval bound to the original execution and receipt,
reconciliation attempt, compensation execution/effect, canonical request
digest, target scopes, workflow-gate decision, and nonce. A caller boolean,
model/worker/operator statement, controller approval record, prior receipt, or
serialized token MUST NOT satisfy or replay host approval. A missing or denied
workflow gate, unavailable bridge, absent/stale/mismatched host approval,
request/target drift, or compensation uncertainty leaves the original scope
blocked.

When the current Codex host cannot produce the live authority required for
`ABANDONED` or consume the opaque one-shot approval required for
`COMPENSATED`, that absence SHALL close only the current reconciliation attempt
as `UNRESOLVED`. The controller SHALL keep the original execution, receipt,
containment, index membership, affected scope, dependencies, barriers, and
finalization blocked and SHALL return the bounded
`dev-flow-v4-operator-intervention/v1` contract defined by the compact agent
protocol. It SHALL ask the user to inspect or operate and then stop. It MUST
NOT automatically
poll into another attempt, redispatch the business effect, invoke compensation,
create a replacement, archive/remove the original blocker, or unblock any
affected scope. A user, model, worker, manager, or caller assertion alone MUST
NOT satisfy live evidence, receipt verification, or host approval.

A later authenticated original runtime, verifiable complete stored receipt, or
future trusted host recovery authority MAY support a fresh separately
authorized attempt against the same original execution. The prior intervention
packet and `UNRESOLVED` attempt MUST remain non-authoritative history and MUST
NOT be promoted or replayed as proof. This hostless behavior is the required
macOS safety closure; successful trusted-host `ABANDONED` and `COMPENSATED`
paths are optional and are not claimed by this release.

The controller SHALL archive the original and either remove its index entry or
promote it to an authenticated runtime reservation only after one terminal
reconciliation decision, all linked runtime/containment obligations are
quiescent or validly handed off, the authoritative recovery event is in task
state/outbox, and archive bytes are durable. If safety cannot be proven, the
affected scope, dependents, barriers, and finalization remain
blocked without pretending completion; unrelated disjoint scopes MAY proceed
when policy allows.

Schema-v1 and schema-v2 tasks SHALL remain on the frozen legacy
mutation-intent, containment, quarantine, confirmation, revision, event, and
recovery path. Introducing the schema-v3 two-phase protocol MUST NOT add a
legacy revision, change a legacy event batch or error code, or alter whether a
legacy effect starts. Golden tests SHALL cover success, rejection, and
stage-specific interruption for each retained legacy Git/filesystem action.
The immutable compatibility oracle SHALL come from isolated execution or audit
of base commit `2dc397411ad1ea5f2a43d43e881523b125bb5eec`, or from a read-only
fixture that embeds that base identity and was frozen before candidate
execution. Candidate code MUST consume but MUST NOT regenerate or update
expected observations. The base and candidate command inventories and every
success, pre-effect rejection, and interruption-stage trace MUST be compared
for completeness.

#### Scenario: Recover a completed effect after controller interruption
- **WHEN** an authorized effect completed but the controller stopped before recording node completion
- **THEN** recovery validates the durable intent, receipt, and actual postconditions before committing the corresponding result exactly once

#### Scenario: Reject an effect before kernel authorization
- **WHEN** a schema-v3 command reaches a Git, filesystem, repository-registry, or external-system executor without a current durable execution authorization from the pinned engine
- **THEN** the executor is not started and neither workflow nor external state is changed

#### Scenario: Separate preview facts from receipt facts
- **WHEN** receipt timestamps, actors, process identities, or post-effect observations become available only after execution
- **THEN** they bind the commit intent and receipt but do not alter the previously confirmed execution-intent identity

#### Scenario: Concurrent callers claim one execution
- **WHEN** two callers race to apply the same current execution authorization
- **THEN** one durable compare-and-swap claim wins, at most one executor starts, and the other caller receives the existing attempt or a structured conflict without changing external state

#### Scenario: Crash during index and journal promotion
- **WHEN** the controller stops after reserving a pending record digest, after writing the active journal, or before promoting the index entry
- **THEN** the reserved scopes remain blocked and recovery completes or quarantines the exact digest update before any effect can be claimed

#### Scenario: Dispatch disjoint repository scopes concurrently
- **WHEN** two current scoped executions target different approved repositories, worktrees, leases, paths, and external resources in one task
- **THEN** the index permits independent per-effect claims and dispatch while every task-state receipt still commits serially under current-revision CAS

#### Scenario: Reject an overlapping ordinary effect
- **WHEN** an ordinary execution requests a scope overlapping an active execution or either action is `exclusive-task`
- **THEN** index CAS rejects the new claim before dispatch and preserves both external state and the existing journal

#### Scenario: Commit an asynchronous runtime handoff
- **WHEN** a declared runtime-dispatch executor has a durable lease, containment, runtime handle, stop/reconcile capabilities, and verified launch postconditions while the worker remains running
- **THEN** the dispatch journal may commit through `HANDOFF_VERIFIED` and archive into an indexed runtime reservation, leaving worker lifecycle and per-effect containment active while allowing another disjoint repository dispatch

#### Scenario: Stop a running scoped execution
- **WHEN** an authorized cancellation, stop, or reconciliation action targets one active execution whose ordinary scope would otherwise conflict
- **THEN** the kernel admits only the exact control child record, keeps unrelated scopes available, and requires its own claim, receipt, engine proof, and audit event

#### Scenario: Revalidate across a disjoint revision
- **WHEN** another repository's non-conflicting commit advances task revision after a `disjoint-scope-revalidate` effect starts
- **THEN** the engine reloads the latest state, proves the target scope and semantic guard projection unchanged, and constructs a fresh current candidate rather than applying the stale candidate

#### Scenario: Current facts drift after execution
- **WHEN** an exact-revision action sees any revision change or a scoped action's workflow identity, target scope, evidence, approval, guard result, ownership, or postcondition no longer matches the execution authorization
- **THEN** the controller preserves the settled receipt in quarantine and requires explicit reconciliation without committing or replaying the effect

#### Scenario: Recover one dependent effect without redispatch
- **WHEN** a multi-effect action restarts after one effect was durably claimed and another declared-dependent effect remains unclaimed
- **THEN** recovery observes and verifies the claimed effect, never dispatches it again, and may claim the dependent effect only after its declared predecessors are reconciled

#### Scenario: Restart a manager-authorized journal
- **WHEN** the controller restarts with an active manager-authorized journal whose process-local memory is gone
- **THEN** recovery reauthenticates the request through the manager channel, derives and verifies the durable journal seal without persisted secrets, and otherwise quarantines the execution

#### Scenario: Verify canonical journal and seal vectors
- **WHEN** independent macOS runs encode the normative journal/index fixtures and fixed test-only manager secret
- **THEN** they produce the exact same canonical bytes, record/index digests, derived execution key, journal seal, and fixed-key proof MAC vector without implying native Windows or Linux evidence

#### Scenario: Tamper with or copy a journal seal
- **WHEN** any covered field changes, a wrong manager secret is presented, or a digest/seal from another task or execution is copied onto the record
- **THEN** constant-time verification rejects the record before claim, recovery, receipt acceptance, or task mutation

#### Scenario: Recover after authoritative state replacement
- **WHEN** task state and its pending or delivered event already bind the execution identity and receipt digest but the journal is not yet marked committed
- **THEN** recovery completes journal and containment bookkeeping without dispatching any effect or committing a second revision

#### Scenario: Crash while archiving a terminal journal
- **WHEN** a terminal active journal cannot be archived or removed
- **THEN** its index entry remains a blocker for the affected scope and no overlapping effect can be prepared or dispatched while unrelated disjoint scopes retain their declared availability

#### Scenario: Accept a quarantined receipt
- **WHEN** a fresh authorized reconciliation proves the stored receipt and current postconditions satisfy the pinned accept policy
- **THEN** the engine reuses that receipt without dispatch, commits the current candidate, recovery event, and nonce atomically, then archives and unblocks the scope

#### Scenario: Abandon a quarantined execution
- **WHEN** an identity-covered controller verifier captures current target-bound live evidence proving no invocation/effect occurred or that the exact target is quiescent with no accepted business outcome
- **THEN** the engine records abandonment without accepting the stale candidate or redispatching and archives the execution only after every containment obligation is closed

#### Scenario: Reject caller-supplied abandonment evidence
- **WHEN** abandonment relies on a missing process or handle, expired lease, idempotency key, stale receipt, caller snapshot, or worker/operator/model assertion instead of controller-owned live evidence bound to the exact execution and target
- **THEN** the attempt becomes `UNRESOLVED` and the original execution, receipt, containment, and scope remain blocked

#### Scenario: Compensate a quarantined execution
- **WHEN** the pinned workflow declares compensation, its current workflow gate passes, and the host-owned bridge consumes an exact request-bound opaque one-shot approval immediately before invocation
- **THEN** compensation uses a separately claimed journal/control record and verified receipt before the original execution is marked compensated and its scope is unblocked

#### Scenario: Forge or replay compensation approval
- **WHEN** a caller supplies an approval boolean, prior receipt, controller record, serialized token, wrong target/request, expired approval, or replay instead of the current host-owned opaque one-shot approval
- **THEN** the compensation invocation count remains zero and the original execution and scope remain blocked

#### Scenario: Run compensation without both gates
- **WHEN** either the pinned workflow gate is absent or denied or the host-owned approval bridge is unavailable or denies the exact request
- **THEN** compensation is unavailable, no compensation journal reaches effect claim, and reconciliation remains `UNRESOLVED`

#### Scenario: Recover without trusted Codex-host authority
- **WHEN** the current host cannot authenticate the original runtime for abandonment and cannot consume an exact opaque one-shot approval for compensation
- **THEN** the current attempt becomes `UNRESOLVED`, returns the bounded intervention packet, asks the user to inspect or operate, and stops with zero automatic redispatch, compensation, replacement, archive, or unblock

#### Scenario: Assert safety after manual inspection
- **WHEN** a user, model, worker, manager, or caller reports that the effect is quiescent, the receipt is valid, or compensation is approved without the required authenticated evidence or host authority
- **THEN** the assertion is recorded at most as non-authoritative diagnostic context and the original execution and scope remain blocked

#### Scenario: Start a fresh attempt after authority becomes available
- **WHEN** a later request authenticates the original runtime, verifies the complete stored receipt, or obtains future trusted host recovery authority
- **THEN** recovery may create a fresh authorized attempt without redispatching the claimed business effect or treating the earlier intervention packet as proof

#### Scenario: Fail to reconcile safely
- **WHEN** an attempt cannot prove acceptance, abandonment, or compensation, or loses its CAS or authorization
- **THEN** that attempt is `UNRESOLVED`, the original receipt and execution remain active and scope-blocking, and a replay cannot consume the nonce or pretend closure

#### Scenario: Crash during reconciliation closure
- **WHEN** reconciliation stops before or after task-state replacement, outbox persistence, containment closure or handoff, index removal or runtime-reservation promotion, or archive write
- **THEN** recovery uses the task event plus journal/index CAS to finish exactly once without redispatch, duplicate nonce consumption, premature unblocking, or loss of the stored receipt

#### Scenario: Capture a review snapshot
- **WHEN** a schema-v3 review action would write a snapshot tree in the controller data directory
- **THEN** it first claims its journal effect and commits only a verified content-addressed snapshot receipt, so a crash leaves a recoverable claimed effect rather than an untracked or partially accepted tree

#### Scenario: Accept an external index result
- **WHEN** an external index action reports success without its declared typed receipt and independently validated source/postcondition observations
- **THEN** the engine rejects or quarantines the result and commits no index evidence

#### Scenario: Preserve a legacy side-effect command
- **WHEN** a supported schema-v1 or schema-v2 task invokes a retained Git or filesystem command after schema-v3 two-phase execution is installed
- **THEN** the frozen legacy adapter preserves its prior confirmation, effect-start, mutation-intent, revision, event, error, and recovery observations byte-for-byte where the contract requires exact compatibility

#### Scenario: Refuse a candidate-authored legacy oracle
- **WHEN** a compatibility test attempts to regenerate expected side-effect traces from candidate code or uses a fixture without the immutable base identity
- **THEN** validation fails and accepts only the isolated base execution or pre-candidate read-only fixture bound to `2dc397411ad1ea5f2a43d43e881523b125bb5eec`

#### Scenario: Encounter an uncertain non-idempotent effect
- **WHEN** recovery cannot prove whether a non-idempotent external effect completed or whether its executor is quiescent
- **THEN** the engine blocks replay, records or preserves durable quarantine, and requires explicit recovery evidence

#### Scenario: Reattach to a claimed asynchronous runtime
- **WHEN** recovery authenticates the already recorded runtime handle, containment identity, attempt, and proof that the same asynchronous runtime is still live
- **THEN** the engine may reattach only to observe, stop, or reconcile that runtime and MUST NOT invoke the dispatcher or executor again

#### Scenario: Lose the runtime handle after claim
- **WHEN** an effect is already claimed but recovery cannot authenticate a live runtime handle or a complete stored receipt
- **THEN** the engine quarantines the affected scope without invoking the dispatcher or executor again, even when the executor advertises an idempotency key

### Requirement: Kernel safety invariants are not extensible
The deterministic kernel SHALL remain the sole authority for task and workspace
locks, expected-revision CAS, bundle identity, approval-intent binding, evidence
authenticity and freshness, protected-path and Git ownership checks, atomic
state replacement, durable outbox delivery, mutation quarantine, and recovery.
No bundle, registry entry, node handler, executor, MCP tool, hook, Skill, agent,
or optional runtime adapter MUST weaken, replace, disable, or report successful
bypass of these invariants. Hooks SHALL remain advisory and fail open on their
own internal errors, while the controller MUST independently reject the same
unauthorized operation. The controller and hooks MUST remain operable with the
Python standard library when all optional Codex and external adapters are
absent.

#### Scenario: Bypass an advisory hook
- **WHEN** a hook is absent or fails open and a caller submits an unapproved or stale transition directly to the controller
- **THEN** the kernel independently rejects the transition before any protected mutation

#### Scenario: Invoke a custom handler against another worktree
- **WHEN** a registered node handler requests a Git or filesystem effect outside its controller-authorized ownership and path boundaries
- **THEN** the kernel rejects the effect and preserves task, workspace, and repository state

#### Scenario: Run without optional agent runtimes
- **WHEN** Codex SDK, Agents SDK, MCP clients, and external executors are unavailable
- **THEN** the standard-library controller and hooks still load task state, enforce all kernel invariants, and execute supported deterministic nodes through the JSON CLI

### Requirement: Existing node kinds are declaratively extensible
Adding a node that composes existing node kinds and registered contracts SHALL
require only a new versioned bundle definition, its referenced schemas and
playbook, and corresponding validation tests. It MUST NOT require a new
hard-coded state constant, transition branch, CLI parser branch, hook state
table, or entry-Skill state table. Adding genuinely new executable behavior
SHALL require an explicit versioned allowlisted registration and tests, after
which any bundle using the supported contract SHALL execute through the generic
node and transition protocols.

#### Scenario: Add a declarative approval node
- **WHEN** a new bundle version inserts a human-gate node using existing gate and schema contracts
- **THEN** the generic catalog, projection, approval, and transition paths expose and execute it without node-specific controller, hook, CLI, or Skill logic

#### Scenario: Add a new executor contract
- **WHEN** implementation introduces a new allowlisted versioned executor with typed contracts, declared authority, implementation digest, and tests
- **THEN** the sealed registry exposes it to validated bundles without changing the transition engine's state-commit protocol

#### Scenario: Remove a handler still required by a task
- **WHEN** an installed runtime lacks a registered contract referenced by a non-terminal task's pinned bundle
- **THEN** the engine returns a compatibility blocker and preserves the task rather than substituting another handler
