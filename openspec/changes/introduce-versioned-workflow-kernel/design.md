## Context

The controller currently exposes a deterministic JSON CLI and keeps workflow
state outside target repositories. Its strongest properties are not model
behavior: they are task and workspace locks, expected-revision checks, atomic
state replacement, durable event delivery, evidence currentness, approval
intents, mutation quarantine, and explicit recovery.

The workflow model, however, is distributed across ordered-state constants,
transition tables, target-state guard branches, domain actions that directly
advance status, CLI parser construction, hook-side copies of labels and next
steps, and Skill reference routing. This makes a workflow change both expensive
and susceptible to semantic drift. It also forces Codex to receive full workflow
and index projections when only one current action is relevant.

The existing runtime constraints remain:

- controller and hook runtime code uses only the Python standard library;
- this V4 delivery is validated only with the installed Python runtime on
  native macOS; it makes no Windows or Linux validation or support claim;
- task state remains outside target repositories;
- Git-changing operations remain deterministic, scoped, and explicitly gated;
- hooks remain small and fail-open on their own errors;
- codebase-memory and model output are discovery evidence, not proof; baseline
  and current-generation workspace queries use distinct controller-selected
  project identities and explicit phase/generation bindings;
- active schema-v1 and schema-v2 tasks must remain resumable without in-place
  workflow migration.

The independent `complete-cross-platform-support` OpenSpec change may define
additional platform requirements, but it is not a release-order prerequisite
for this macOS-only V4 delivery. This change neither modifies nor satisfies
that separate change.

## Goals / Non-Goals

**Goals:**

- Establish one package-owned, versioned source of truth for workflow nodes,
  edges, labels, guard references, invalidation behavior, response projections,
  and execution policy.
- Make common node additions data-only and make executable node additions local
  to a reviewed handler registration plus its node pack and tests.
- Preserve the deterministic controller as the only authority that commits task
  state, approvals, evidence, and repository ownership.
- Add DAG node instances, repository-level map/join execution, barriers, and
  runtime handles without turning model conversations into workflow state.
- Provide compact typed surfaces for Codex and retain the existing CLI as a
  complete compatibility and recovery interface.
- Reduce repeated orchestration context and measure actual node-level token and
  latency costs.
- Introduce changes incrementally with legacy adapters, shadow comparison, and a
  rollback path at every migration boundary.

**Non-Goals:**

- Replacing the controller with an LLM planner, the Agents SDK, Codex App
  Server, or conversation history.
- Allowing target repositories, `PLUGIN_DATA`, arbitrary Python paths, or remote
  MCP servers to load executable controller handlers.
- Automatically migrating an active task from one workflow bundle to another.
- Automatically committing, pushing, merging, stashing, resetting, cleaning,
  rebasing, or force-pushing repositories.
- Requiring Codex SDK, Agents SDK, Node.js, or any third-party Python package for
  normal plugin operation.
- Making hooks a complete enforcement boundary.
- Moving the ordered shared-namespace facade to ordinary package imports in
  this change. Physical loader modularization is deferred to a separate,
  independently reversible OpenSpec change; this change introduces explicit
  `RuntimeServices` while retaining the loader compatibility boundary.

## Decisions

### 0. Use evidence-gated milestones without creating partial release states

The delivery sequence uses four planning checkpoints defined in
`MILESTONES.md`. A milestone is a bounded implementation and review stop, not a
workflow version, release reservation, activation state, or substitute for an
OpenSpec checkbox.

V4-M0, the selected next checkpoint, implements only the ledger-successor and
introduction-epoch provenance contracts in tasks 13.5 and 13.6. It may update
the validator, its direct CLI validation surface, and direct tests. It must run
the smallest directly relevant macOS test selections, strict validation,
`git diff --check`, and independent read-only review, then stop. It does not
create a V4 epoch artifact, append a real V4 reservation, change activation, or
begin recovery runtime.

V4-M1 is a conditional, developer-only local preview. It adds and validates the
inactive V4 candidate bundles, complete transitive identity declarations, and
the V3 fail-closed inspection policy in tasks 13.1 through 13.3. It may exercise
catalog loading, read-only inspection, and preview against isolated test data,
but cannot expose apply, dispatch, compensation, production creation, or
installation. A future restricted `lite@4` execution profile would require a
separate scope decision and a terminal-capable graph whose every reachable
operation has its complete safety closure; reachability cannot be edited merely
to evade testing.

V4-M2 completes all remaining local effect, reconciliation, multi-repository,
CLI recovery, and V4 regression closure while both V4 profiles remain inactive.
V4-RC then follows the ordered 14.x freeze and external-evidence sequence on
one candidate. Only V4-RC may append the exact final V4 reservation batch, and
only its separately authorized later gates may hand off, run CI, install,
publish, or activate.

V4-RC uses macOS-only native, focused CI, installation, and post-report
evidence. The independent `complete-cross-platform-support` change remains
separate and is not queried as a gate; one change never silently satisfies the
other.

The milestone boundary never downgrades a security failure to a schedule issue.
Lock order, expected-revision CAS, proof and nonce atomicity, journal/
reconciliation state, quarantine, target-bound live evidence, dual-authority
compensation, and zero-redispatch remain immediate blockers in every
checkpoint whenever those paths are exercised. Absence of trusted host
authority is not itself an M2 blocker when the required scope-blocking
`UNRESOLVED` operator-intervention path passes; it grants no live-evidence or
compensation authority. V3 historical non-completions remain immutable facts
and are not manufactured to improve milestone progress.

### 1. Use immutable workflow bundles as the workflow source of truth

A workflow bundle contains canonical JSON definitions, referenced playbooks,
JSON schemas, and the versioned identities of every referenced handler. Built-in
bundles are shipped under a package-owned `workflows/` directory.

The top-level definition contains:

- `schema`, `workflow_id`, and `workflow_version`;
- supported task schema and controller contract ranges;
- node definitions;
- edge definitions;
- task-level terminal and compatibility metadata;
- referenced handler contract IDs;
- response projection and playbook references.

Each node definition contains, as applicable:

- stable `id`, `kind`, localized labels, and lifecycle policy;
- `handler`, `guards`, `reducers`, and evidence contracts;
- `playbook`, required state sections, and context projection;
- executor kind, tool capabilities, write policy, timeout, retry, and budget;
- fan-out, concurrency key, and join policy.

Each edge contains:

- stable edge ID and source/target node IDs;
- action or completion trigger;
- named guards and reducers;
- confirmation policy and side-effect classification;
- exact allowed state-write paths;
- audit and evidence projection profiles.

The normative `dev-flow-bundle-identity/v1` contract uses domain-separated
SHA-256 preimages with unsigned 64-bit big-endian length prefixes. It rejects
non-portable or colliding paths, symlinks, special files, duplicate JSON keys,
non-NFC strings, floats and non-finite numbers, and requires every transitive
file and every handler implementation source file to be enumerated without
globs. JSON, UTF-8 text, and binary payloads have distinct kind bytes;
handler-file sets and bundle files are sorted by normalized UTF-8 path bytes.
The exact preimages and reference encoder are defined in the
`versioned-workflow-bundles` specification and protected by normative golden
vectors executed for this delivery on macOS. Those vectors retain portable
semantics but do not establish native Windows or Linux evidence.

`graph_sha256` covers the canonical root graph payload. `bundle_sha256` covers
every canonical bundle file plus handler ID, contract ID, and the digest of
every exact packaged handler implementation file.

The handler set is a complete transitive execution closure, not only the
handler named on the happy-path edge. For each action it includes every
package-owned implementation that can dispatch, observe a receipt or live
target, settle or reattach a runtime, validate postconditions, stop or
reconcile a target, decide `ACCEPTED`/`ABANDONED`/`UNRESOLVED`, plan or verify
`COMPENSATED`, close containment, or archive and unblock the execution.
Recovery policy data, schemas, validators, and every callable recovery handler
are therefore identity-covered. A generic recovery helper outside that closure
cannot change the meaning of a reserved action. Any change to one of those
semantics changes a handler implementation identity and, after reservation,
requires a successor handler contract and workflow version.

A package-owned `workflows/release-ledger.json` using
`dev-flow-workflow-release-ledger/v1` is the authoritative, portable
immutability-boundary evidence. Before the first installation, publication,
external handoff, or activation that could expose an exact
identifier-version, the release process must add a canonical reservation
binding the workflow ID/version, graph and bundle identities, and every
handler contract and implementation identity. The ledger is deliberately not
part of any identity stored inside itself; the later package-candidate and
handoff digests cover the ledger bytes, avoiding a self-referential digest.
The reservation is written after the cachebuster and all identity-covered
workflow inputs stabilize but before the exposing operation. Its durable
presence crosses the boundary even when that operation later fails.
Reservation entries are append-only package history: they cannot be deleted or
rewritten, and catalog validation rejects a different identity for their
identifier-version.

Ledger order is append history rather than a globally sorted set. The existing
V3 reservation objects are an immutable exact sequence prefix. Each later
introduction epoch appends one contiguous batch; epochs are ordered by their
monotonic sequence, and entries are sorted only within that batch by workflow
identifier UTF-8 bytes and numeric workflow version. Validation never re-sorts
or rewrites a prior prefix to make a new key fit global lexical order. Epoch
provenance binds the predecessor reservation count and SHA-256 of the exact
strict canonical predecessor-ledger bytes plus the appended batch start, count,
ordered keys, and a domain-separated SHA-256 over the canonical complete
reservation-object list, including every graph, bundle, handler-contract, and
handler-implementation identity.

For this first introduction, the package also ships
`workflows/release-provenance/first-introduction.json` using
`dev-flow-workflow-first-introduction-provenance/v1`. It binds the change ID,
Git object format, base commit
`2dc397411ad1ea5f2a43d43e881523b125bb5eec`, base tree
`ee7de366a818d8800b4808015f2d8ae4c4405136`, the exact introduced
workflow identifier/version and handler identity keys, and a baseline
inventory digest. The inventory is
`SHA256(b"dev-flow-first-introduction-git-tree-v1\0" ||
U64BE(len(raw_inventory)) || raw_inventory)`, where `raw_inventory` is the
unaltered output of `git ls-tree -rz --full-tree <base_commit>` and the
resolved tree must equal the declared base tree. Validation recomputes it from
the named immutable Git objects; wrong object format, commit, tree, inventory,
introduced-key set, mutable/unknown fields, or a baseline already containing
an introduced identity fails closed.

This `first-introduction.json` is immutable historical provenance for its exact
declared V2/V3 workflow and handler key sets. V4 MUST NOT edit it to add
`full@4`, `lite@4`, or successor handlers. Its exact canonical file SHA-256 is
`72e301d16546001abb397e37600cf3a141ca2955e7052f5d7dabdbb96f02016a`;
successor validation anchors this value rather than trusting a replacement
manifest and a caller-recomputed digest. The provenance manifest contains no
self, candidate, review, or handoff digest.
The pre-handoff independent review instead emits an external
`dev-flow-release-review/v1` record binding reviewer identity, manifest
SHA-256, base commit/tree/inventory, and frozen candidate digest; the external
handoff manifest repeats those bindings. A handoff without the matching review
record is not authoritative. A successor to an official release uses the
previous reviewed ledger and handoff manifest rather than regenerating this
first-use assertion; the reserved-unexposed V3 successor case is defined
separately below.

A later set of newly introduced workflow or handler identity keys uses a
separate strict
`dev-flow-workflow-introduction-epoch-provenance/v1` successor manifest under
`workflows/release-provenance/introduction-epochs/`. It binds its schema and
change ID, a monotonic epoch sequence and identity, predecessor kind and
provenance SHA-256, the exact predecessor reservation count and canonical
ledger SHA-256, the sorted new workflow and handler key sets, the contiguous
ledger append-batch start/count plus domain-separated digest of the canonical
complete reservation objects, and the resulting ledger SHA-256 and cumulative
identity-set digest. For each epoch, introduced keys are exactly the current
package keys minus the cumulative predecessor provenance history, and the
ledger suffix keys exactly equal the introduced workflow keys. The cumulative
handler history is never reconstructed from the smaller union of handlers
referenced by ledger reservations. Every appended complete reservation must
equal the reservation recomputed from the exact current package. For
`official-release`, it binds the exact previous independently reviewed handoff
and review identities. For `reserved-unexposed`, it instead binds the immutable
`first-introduction.json` SHA-256, predecessor ledger SHA-256 and reservation
count, inactive activation-manifest identity, and an explicit declaration that
no review, handoff, publication, installation, activation, or pin-eligibility
fact is being asserted; the current independent V4 review must confirm that
supersession from authoritative release and activation evidence before
handoff. `active=false` or an empty/partial data-root scan alone is
insufficient. It contains neither its own digest nor the current
candidate, review, or handoff digest. The current independent review and
handoff records later bind this successor manifest and completed ledger.
Missing or discontinuous provenance required for the selected predecessor kind
blocks the new epoch; an absent V3 handoff is not fabricated and does not by
itself invalidate the authorized `reserved-unexposed` successor. Neither kind
authorizes editing the first-introduction record or an earlier ledger prefix.

The current ledger already reserves `full@3`, `lite@3`, the frozen legacy
workflow identities, and their recorded handler implementation identities.
It contains four reservations and its exact strict canonical file SHA-256 is
`89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062`.
That reservation is an irreversible identity fact only. The V3 candidate did
not complete the independent review, reproducible external handoff, native
evidence, publication, installation, activation, or pin-eligibility sequence,
and no such fact may be inferred or synthesized. Because recovery semantics
must now enter the complete transitive identity after that reservation, the
successor workflows are `full@4` and `lite@4`; the reserved V3 bundles and
handlers remain package-resolvable and read-only.

Before a release reservation exists, candidate bytes may be regenerated under
the same working contract/version only when authoritative prior-release
provenance proves that identifier-version absent from every preceding official
release, its profiles have never been pin-eligible, and no installation,
publication, or external-handoff evidence exists. The provenance is the exact
chain required by the selected predecessor kind: previous reviewed release
ledger and handoff manifest for `official-release`, immutable
first-introduction plus exact reserved/inactive/no-exposure bindings for
`reserved-unexposed`, or the immutable package baseline for the original first
introduction. Missing or discontinuous required provenance fails closed and
requires a new workflow and handler version.

Because callers may choose arbitrary controller data roots, scanning one or
more roots is only a negative blocker: a discovered task reference proves the
boundary was crossed, but an empty scan can never authorize same-version
regeneration or claim that no hidden root exists. Pin eligibility itself
requires a prior release reservation, so a legitimately controller-created
pin is covered by the release chain. An unreserved task reference or exposure
is quarantined as missing provenance and preserves its observed identity
rather than authorizing replacement. After the boundary, a semantic handler
change requires a new versioned handler contract ID and workflow version; the
previously reserved handler and bundle remain resolvable without in-place
substitution.

**Alternative considered:** Keep Python constants as authoritative and generate
Hook or documentation projections from them. This removes some copies but does
not provide immutable task pinning, declarative validation, or safe node packs.

### 2. Keep task schema v3 for V4 workflows behind a fail-closed activation gate

Workflow version and task-state schema version are independent. The V4
successors are `full@4` and `lite@4`, but their tasks continue to store
`schema_version: 3`; no task schema v4 is introduced merely because the
workflow version advances. A new V4 task stores:

```json
{
  "schema_version": 3,
  "workflow_ref": {
    "id": "full",
    "version": 4,
    "schema": "dev-flow-workflow/v1",
    "graph_sha256": "...",
    "bundle_sha256": "..."
  }
}
```

The existing `flow` and `status` fields remain compatibility projections. The
v3 state additionally stores node instances, their attempts, dependency state,
result/evidence references, and optional runtime handles.

Parsing, validation, catalog resolution, and read-only projection support for
task schema v3 exist while `full@4`/`lite@4` creation remains disabled. A
package-owned activation manifest enables new-task creation only for an exact
V4 bundle whose reachable edges, complete transitive handler identities,
recovery paths, and node kinds have passed legacy golden equivalence, shadow
comparison, and required recovery tests. Single-repository full/lite
activation is separate from multi-repository map/join activation, so no task
can select an execution surface the installed controller cannot complete.
Turning activation off affects only future task creation; an existing
supported task always stays on its exact pinned bundle and engine.

The reserved `full@3`/`lite@3` identities were never handed off or activated
and MUST remain inactive for new creation. If a controller nevertheless
discovers a task pinned to one of those identities, it preserves the exact
task bytes, workflow reference, journals, receipts, containment, scopes,
runtime handles, artifacts, worktrees, bundle, and handler implementations.
Read-only inspection remains available. State advancement, ordinary dispatch,
retry, and protected effects fail closed; a target-bound stop or reconciliation
may run only when the exact V3 bundle contains the complete transitive handler
identity for that safety operation and all of its live-evidence requirements
are satisfied. The controller never substitutes V4 recovery semantics,
silently migrates the task, treats missing handlers as abandonment, or unblocks
a scope whose safe closure is unproven.

Schema-v1 and schema-v2 tasks resolve to immutable built-in
`full@legacy-v2`/`lite@legacy-v2` adapters. They retain existing confirmation,
edge, response, and evidence behavior. A task never changes its pinned bundle
in place. If a workflow needs replacement, the user explicitly starts a new
task or uses a future separately specified migration tool.

**Alternative considered:** Rewrite existing state into the latest graph.
Rejected because handler and invalidation changes could silently reinterpret
existing approvals and evidence.

### 3. Introduce sealed, versioned registries

The runtime provides:

```text
CommandRegistry  command/action ID -> parser factory and handler
GuardRegistry    guard contract ID -> read-only evaluator
ReducerRegistry  reducer contract ID -> bounded state transform
GateRegistry     gate contract ID -> approval/evidence builder
ExecutorRegistry executor contract ID -> assignment/result adapter
```

Registration is performed only by package-owned modules listed in a static
runtime manifest. Duplicate IDs, missing contracts, an unknown playbook/schema,
or a bundle referring to an unregistered ID fails closed. Registries are sealed
before any task is loaded and cannot be replaced during the process lifetime.

Workflow JSON never names importable Python objects or arbitrary commands.
External plugins and MCP tools can be executor dependencies or evidence
producers, but cannot register guards, reducers, or gates in the controller.

This change retains the ordered shared-namespace loader and introduces frozen,
explicit `RuntimeServices` boundaries for catalog, registries, store, locks,
evidence, Git, and adapters. The loader remains the compatibility facade for
direct-script and independent spec loads, facade-visible monkeypatches,
process-local caches, and `ContextVar` identity. Workflow extensibility is
provided by declarative bundles and sealed registrations rather than Python
import topology. Migration to ordinary imports is deferred to a separately
reviewed OpenSpec change.

New guards and reducers receive only immutable canonical projections and a
versioned kernel capability object. Guard capabilities expose declared
read-only evidence queries; reducer capabilities expose no filesystem, Git,
process, network, registration, or commit primitive. The static manifest and
AST/import audit reject undeclared implementation files, globals, imports, and
capability requests. Legacy wrappers may use existing kernel-owned read-only
evidence services and remain package-trusted code under equivalence tests.
Python cannot sandbox arbitrary compromised in-process code, so untrusted logic
is always an external executor whose output is only an evidence candidate; the
runtime does not promise impossible detection of every arbitrary side effect.

**Alternative considered:** Use `importlib` discovery from `PLUGIN_DATA` or
Python entry points. Rejected because it introduces executable supply-chain
and compatibility risks into the state authority.

### 4. Centralize movement in one transition engine

Every state-changing domain command returns an `ActionOutcome` rather than
directly assigning task status:

```text
action_id
proposed_edge_id
evidence_records
proposed_state_delta
audit_facts
external_postconditions
```

Node actions that keep the coarse task status unchanged are not a second
mutation path. During catalog sealing, each declared node action is compiled
from the task-pinned bundle into an immutable same-node action edge with a
stable identity, exact public command and trigger, canonical audit event,
handler/guard/reducer/gate references, confirmation policy, bounded
node-owned writes, kernel-owned effects, external-effect classification,
canonical effect scopes/concurrency and dependency/parallel policy,
quiescence-or-handoff settlement, accepted receipt schema,
dispatch/idempotency policy, target-bound control actions, quarantine
reconciliation/compensation, and recovery policy.
One action identity maps to exactly one semantic validator, event contract,
and write/effect set; semantic overloading requires separate versioned action
identities. These compiled action edges participate in bundle validation and
engine evaluation but do not participate in movement-cycle analysis.
Activation computes a separate action closure over every movement-reachable
node and requires every exposed action edge, contract, effect, receipt,
recovery policy, and test suite to be ready. Runtime code must not append an
ad-hoc pseudo edge, infer write authority from the candidate diff, or fall
back to a more permissive schema-v1/schema-v2 command placement.

The durable commit boundary requires a single-use engine proof for every
schema-v3 business-state change, including same-node evidence, artifact,
repository, approval, test, review, workspace, node-instance, and orchestration
updates. Specialized validators may still establish the semantics of a gate,
node result, lease, or orchestration operation, but their output becomes a
typed `ActionOutcome` consumed by this same engine. Generic manager
authorization alone never authorizes a schema-v3 state write.

The proof is an opaque, non-serializable `EngineCommitProof` minted only after
the kernel evaluates the current state while the required locks are held. It
binds the canonical task-directory identity, held-lock capabilities, task and
revision, workflow bundle and edge, old and candidate state digests, action
outcome, event batch, and any verified receipt. A controller-start-private
domain-separated MAC and one-shot issuance registry authenticate and consume
it. Constructing or deserializing a public `TransitionEvaluation`, copying a
`ContextVar` dictionary, knowing the bound digests, or possessing manager
authorization cannot mint a registered proof. Proofs do not survive process
restart; recovery reloads current facts and reevaluates the pinned engine to
mint a new proof against an already verified receipt. This is a package
integrity boundary for trusted controller code, not a claim that Python can
sandbox a compromised allowlisted module.

Side-effecting actions use two engine-bound phases:

1. before the effect, the controller seals and durably journals an execution
   authorization bound to task, revision, workflow, action, effect plan,
   exact effect/dependency/parallel-group and idempotency identities,
   authorized paths, and caller
   confirmation, then atomically claims each eligible effect for exactly one
   dispatcher; the first claim advances the global execution phase but does
   not pre-claim later effects;
2. after a synchronous executor quiesces, or an explicitly asynchronous
   runtime reaches its declared durable handoff point, the controller
   independently observes postconditions, validates a typed receipt,
   reevaluates all current guards, and commits the resulting `ActionOutcome`
   through the engine.

The controller task directory contains a strict
`dev-flow-v3-action-execution-index/v1` at `action-executions/index.json`,
independent active records at
`action-executions/active/<execution-id>.json`, and terminal records at
`action-executions/archive/<execution-id>.json`. The index and every strict
`dev-flow-v3-action-execution-journal/v1` record reject unknown fields and have
separate monotonically increasing revisions. A journal update compares
execution identity, expected journal revision, and expected canonical record
digest. Index membership and scope claims use their own expected index
revision and digest. Both are reloaded and atomically written while holding
the task lock and any declared repository, worktree, lease, or registry lock.

Index/journal coordination uses an explicit write-ahead protocol rather than
claiming a cross-file atomic rename. Under those locks, index CAS first reserves
the execution scopes and records `pending_record_sha256`; the controller then
atomically writes the active journal and uses a second index CAS to promote
that digest to `record_sha256` and clear the pending value. No effect may be
claimed or dispatched until promotion. A crash with a pending digest keeps the
scope blocked; recovery validates the old/new record and completes or
quarantines the update without dispatch. Terminal closure atomically writes
and verifies archive bytes before synchronous index removal or asynchronous
runtime-reservation promotion; an orphaned active file afterward is removable
only when it exactly matches that archive.

Each execution declares canonical effect scopes and a sealed concurrency
class. `exclusive-task` conflicts with every ordinary effect; `scoped`
executions may coexist only when their repository, worktree, lease, path, and
external-resource scopes are disjoint. The kernel computes conflicts and does
not trust a caller-supplied non-conflict assertion. A terminal synchronous
record is removed from the active index only after its authoritative task event
and containment obligations are reconciled and its archive write succeeds. A
terminal asynchronous dispatch record is instead promoted to the runtime
reservation described below. An archive failure continues to block the
affected scope, not unrelated repository scopes.

Cancellation, stop, and runtime reconciliation are kernel-priority control
operations, not unrestricted new effects. They create an indexed control child
record that names one active execution or runtime handle and may overlap only
that target's scope when the pinned catalog declares the exact control edge,
authorization, and allowed writes. The child record cannot widen the target
scope or authorize ordinary work. Task/result/barrier mutations still commit
serially under expected-revision CAS even while disjoint repository execution
records are claimed and dispatched concurrently.

The journal immutably binds task and pre-effect revision/state digest, workflow
bundle, action edge and handler, effect-plan digest, concurrency class and
scopes, authorized paths, confirmation and operation fingerprints,
authorization/capability/request fingerprints, request-nonce digest,
principal, verifier-before/candidate-after digests, and the exact effect
identities, safe inputs, idempotency identities, dependency relation, and
parallel groups. It never persists a raw nonce, manager secret, or capability.

Journal and index canonical bytes reuse the strict semantic JSON rules from
`dev-flow-bundle-identity/v1`. Let `core_bytes` be the canonical bytes of the
whole record excluding only top-level `record_sha256` and `seal`. The lowercase
record digest is:

```text
SHA256(
  b"dev-flow-v3-action-execution-journal-record-v1\0"
  || U64BE(len(core_bytes))
  || core_bytes
)
```

For a manager-authorized record, derive:

```text
execution_key = HMAC-SHA256(
  manager_secret,
  b"dev-flow-v3-action-execution-journal-key-v1\0"
  || U64BE(len(task_id_utf8)) || task_id_utf8
  || U64BE(len(execution_id_utf8)) || execution_id_utf8
)

seal = HMAC-SHA256(
  execution_key,
  b"dev-flow-v3-action-execution-journal-seal-v1\0"
  || U64BE(len(core_bytes)) || core_bytes
)
```

`manager_secret` is the exact UTF-8 byte sequence of the already validated
secret-channel value; `task_id_utf8` and `execution_id_utf8` are their
strict-NFC UTF-8 bytes. `execution_key` is the raw 32-byte HMAC output, while
`record_sha256` and `seal` are lowercase hexadecimal.
The index uses the equivalent
`dev-flow-v3-action-execution-index-record-v1\0` digest domain and has no
manager seal. Hex digest and HMAC comparisons use `hmac.compare_digest`.
Including task and execution identities in both the core and key derivation
prevents seal copying. The controller-private, nonpersistent engine proof uses
the same strict JSON and length framing with its distinct
`dev-flow-v3-engine-commit-proof-v1\0` HMAC domain and a process-random key.
No digest or seal covers itself.

Recovery of a manager-authorized journal must reauthenticate through the
manager channel and derive the same execution key rather than trusting a
process-local random seal. An expired or revoked authorization that cannot
satisfy the explicit reconciliation policy is quarantined, not retroactively
completed.

The global phase machine progresses monotonically through
`PREPARED -> DISPATCH_CLAIMED -> RUNNING -> (QUIESCED |
HANDOFF_VERIFIED) -> RECEIPT_VERIFIED -> COMMITTED`. `HANDOFF_VERIFIED` is
available only to a package-owned asynchronous runtime-dispatch contract whose
receipt durably binds its lease, containment, runtime handle, stop/reconcile
capabilities, and launch postconditions; the worker lifecycle then continues
in the separate node-runtime record. Synchronous Git, filesystem, registry,
and external writes must use `QUIESCED`.

`QUARANTINED` is an absorbing fail-closed transition for the original effect
phase; recovery never fabricates missing settlement or receipt phases. Each
effect also uses a durable compare-and-swap progression
`PLANNED -> CLAIMED -> RUNNING -> (QUIESCED | HANDOFF_VERIFIED) ->
VERIFIED`. Effects in one declared parallel group may be claimed independently
when their scopes are disjoint; an effect outside that group waits only for
its declared predecessors, not arbitrary manifest order. An already claimed
effect is never dispatched again. Recovery may dispatch only an unclaimed
effect whose declared predecessors are reconciled, and may otherwise only
observe, settle, or verify a claimed effect. For an asynchronous effect,
“resume” means reattaching to an authenticated already-live runtime handle for
that exact containment identity and attempt; it never means calling the
dispatcher or executor a second time. An idempotency key is audit evidence,
not permission to reinvoke. If no live handle or complete stored receipt can
be authenticated after claim, the affected scope enters `QUARANTINED`. Only a
`PREPARED` journal with no claim and no observed effect may be withdrawn as
unstarted.

An exact input revision remains an audit binding. Exact-revision actions treat
any revision drift as quarantine. A catalog-sealed
`disjoint-scope-revalidate` policy may tolerate only revisions caused by
non-conflicting scopes: under the latest task revision and all required locks,
the engine must prove the target repository/node/lease, semantic guard
projection, approval, ownership, effect plan, and postconditions are unchanged
and build a fresh candidate from current state. It never patches or commits
the stale candidate. Any bound-scope or semantic drift is quarantined.

The singleton legacy `mutation-quarantine.json` remains frozen for
schema-v1/schema-v2. Schema-v3 uses strict per-effect containment records at
`action-executions/containment/<execution-id>/<effect-id>.json`; each binds the
journal schema, execution, effect, and claim identities. Recovery reads both
records and gives the action journal/index precedence; a linked containment
record cannot be independently archived. The required ordering is durable
journal claim, durable spawn-pending containment record, contained process
launch, durable runtime binding, authorized release, and either quiescence or
durable handoff observation before receipt verification. Direct filesystem
and registry effects, including review snapshots and workspace claims, require
the same journal claim even when no child process exists. Frozen
schema-v1/schema-v2 marker paths, bytes, and recovery order remain unchanged.

After `HANDOFF_VERIFIED` commits, the dispatch journal may be archived but its
index entry is atomically promoted to a runtime reservation binding the lease,
runtime handle, scope, containment record, and stop/reconcile actions. That
reservation prevents another ordinary execution from using the same scope
while permitting disjoint repositories. It is removed only after authenticated
runtime exit or explicit quiescence reconciliation and the applicable
result/cancellation event. A handoff or containment failure remains an indexed
quarantine; control child records target the reservation rather than bypassing
it.

The execution authorization intentionally excludes receipt-time observations
and timestamps. The commit intent binds the verified receipt, final candidate,
event batch, and engine-proof digest separately; successful caller
confirmation of the execution intent does not self-confirm a different
semantic action. `RECEIPT_VERIFIED` persists those exact digests before the
final transaction. The state replacement then atomically commits the business
mutation, manager nonce consumption when applicable, and action/manager audit
event whose payload binds the execution identity and receipt digest. Task
state replacement is the commit truth. A crash after state replacement is
recovered from task state and the pending or delivered outbox to finish the
journal and containment records, never by executing the effect again. A crash
before replacement requires the same request and authorization, current
guard/ownership/postcondition reevaluation, and the stored receipt; the
journal reserves but does not separately consume the manager nonce.

If an exact-revision action's revision changes, or workflow identity, bound
scope, guard evidence, approval, ownership, registry state, or verified
postconditions change after an effect, the controller preserves the receipt
and enters `QUARANTINED` rather than committing stale state or replaying the
effect. Only the preceding `disjoint-scope-revalidate` rule permits an
unrelated revision to be rebased through a fresh current engine evaluation.
Baseline receipts bind the exact remote/refspec and pre/post refs; workspace
receipts bind the exact plan, registry claim, and worktree observations;
review-snapshot receipts bind a content-addressed snapshot tree.
External-index success always requires its declared typed receipt. Recovery
code is observe-only for claimed effects and must not call a helper that can
implicitly fetch, materialize, create a worktree, claim a registry entry, or
rewrite a snapshot.

The original execution phase remains `QUARANTINED`; closure uses separate
versioned reconciliation attempts indexed as target-bound control children.
Each attempt has a fresh identity and
monotonic `PREPARED -> CLAIMED -> (ACCEPTED | ABANDONED | COMPENSATED |
UNRESOLVED)` phase, binds the quarantined execution and receipt digests,
expected task/index/journal revisions, exact recovery action, current
operator-or-manager authorization, gate, nonce, and engine proof, and is never
replayed. An `UNRESOLVED` attempt leaves the original execution indexed and
scope-blocking so later evidence may support a new explicitly authorized
attempt.

`ACCEPTED` reuses the stored receipt without dispatch only when current
postconditions and the pinned recovery policy permit a fresh engine evaluation
and atomic task/event/nonce commit.

`ABANDONED` requires controller-owned, freshly captured, target-bound live
evidence from identity-covered recovery handlers. The evidence binds the exact
original execution, effect, attempt, runtime/containment identity, target and
scope, current journal/index/task revisions, observation time and source, and
the postcondition digest. It must prove either that the durable claim was never
released and no invocation/effect occurred, or that the exact target is now
quiescent and no accepted business outcome exists in controller state/outbox
or the live target. A missing process or handle, lease expiry, an idempotency
key, a worker/operator/model assertion, caller-supplied snapshot, stale receipt,
or failure to observe a target is not abandonment evidence. When the
controller-owned live verifier is unavailable, incomplete, mismatched, or
cannot exclude an accepted outcome, the attempt becomes `UNRESOLVED` and the
scope stays blocked.

`COMPENSATED` is available only when the pinned catalog declares a versioned
compensation action and its current workflow gate succeeds. Immediately before
the exact compensation provider, Git, filesystem, or registry invocation, a
host-owned bridge must consume an opaque, non-serializable, expiring one-shot
host approval bound to the original execution and receipt, reconciliation and
compensation execution identities, request digest, target/scope, workflow-gate
decision, and nonce. A caller boolean, model or worker assertion, controller
approval record, prior receipt, or serialized token cannot supply or replay
that approval. The compensation receives its own journal/control record,
receipt, and engine commit; if the workflow gate, host bridge, current opaque
approval, request binding, or compensation receipt is missing, denied, stale,
or uncertain, the original scope remains blocked.

For this macOS product, an unavailable trusted Codex-host verifier or approval
bridge is a supported fail-closed boundary rather than authority that the CLI
may reconstruct. The current reconciliation attempt terminates only as
`UNRESOLVED`; the quarantined execution, receipt, containment, index, and
affected scope remain authoritative and blocked. The CLI returns
`schema: "dev-flow-v4-operator-intervention/v1"` in an outer
`schema: "dev-flow-v4-action-reconciliation-cli-result/v1"`:
`required: true`, stable
`reason: "TRUSTED_HOST_AUTHORITY_UNAVAILABLE"`, `target_execution_id`, sorted
unique `effect_ids`, normalized `affected_scopes`, the exact
`allowed_resume_conditions`
`authenticated_original_runtime`, `verifiable_stored_receipt`, and
`trusted_host_recovery_authority`, plus
`automatic_redispatch: false`, `automatic_compensation: false`,
`automatic_unblock: false`, and `caller_assertion_can_unblock: false`. Task,
attempt, revision, status, and blocked state remain in the outer result.
Neither envelope contains a raw secret, approval, authority, or unbounded
journal/receipt body.

The canonical intervention packet is capped at 4,096 semantic-JSON bytes.
The controller measures the complete encoding and never
truncates identities or scopes. An overflow fails closed as
`ACTION_RECOVERY_OPERATOR_INTERVENTION_TOO_LARGE` with actual/limit counts,
the target execution, and the `action-recovery-inspect` locator; a corrupt
effect graph or noncanonical scope fails as `ACTION_RECOVERY_RESULT_INVALID`.
Both leave the attempt, target, index, scopes, and invocation counts unchanged.

After emitting that packet the controller returns control and asks the user to
inspect or operate. It does not poll into a new attempt, invoke a dispatcher or
compensation provider, archive or unblock the original execution, or infer
proof from anything the user, model, worker, manager, or caller says. A later
authenticated original runtime, verifiable stored receipt, or future trusted
host authority may support a fresh separately authorized attempt against the
same original execution; the packet and prior `UNRESOLVED` attempt are never
promoted or replayed as proof. This hostless behavior is the required macOS
closure for tasks 5.13, 5.15, 7.12, 8.8, and 13.4. Trusted-host
`ABANDONED` and `COMPENSATED` success paths remain optional and are not claimed
as evidence for this release.

The controller archives and either removes
the original index entry or promotes it to an authenticated runtime reservation
only after one terminal reconciliation decision, all linked
runtime/containment obligations are quiescent or validly handed off, the
authoritative recovery event is in task state/outbox, and archive bytes are
durable. If safety cannot be proven, the affected scope, dependents,
barriers, and finalization remain blocked without pretending recovery
succeeded; unrelated disjoint repository scopes may continue when policy
allows.

All of this schema-v3 plumbing branches after task-schema resolution. Frozen
schema-v1/schema-v2 commands retain their existing confirmation, event,
mutation-intent, and recovery bytes. Before any full/lite single- or
multi-repository profile is activated, the activation validator must close
both movement reachability and action closure. Deactivation affects only new
creation; any task already pinned to a previously activated bundle continues
through that exact immutable bundle. During this unreleased migration all
V4 profiles remain inactive. The existing V3 reservation prefix and handler
implementations are immutable and cannot be regenerated. A V4 candidate may be
regenerated under `full@4`/`lite@4` only before its own append-batch reservation
and only when the immutable V3 prefix plus continuous successor provenance
prove those V4 identifier-versions were never exposed or pin-eligible.
Data-root inventory cannot supply that positive proof. After the V4 cachebuster
and every identity-covered input stabilize, the release process must append
the exact V4 reservation batch before the first install, publication, external
handoff, or activation attempt; that reservation remains authoritative even if
the attempt fails. Any identity-covered change after that boundary, or whenever
prior provenance is missing, requires another workflow and handler contract
version plus retention of every prior implementation or a controller-managed
read-only bundle archive, rather than in-place substitution.

The transition engine:

1. acquires the current task and any required workspace-registry locks;
2. reloads state and verifies expected revision;
3. resolves the task-pinned bundle and unique edge;
4. runs named read-only guards;
5. builds a canonical evidence projection;
6. binds task, revision, bundle, edge, handlers, action parameters, evidence,
   and side effects into the transition intent;
7. verifies explicit or automatic confirmation policy;
8. applies reducers to an isolated state copy;
9. compares the resulting JSON Pointer changes against
   `allowed_state_writes`;
10. applies the engine-owned status/node-lifecycle changes and validates global
    invariants and postconditions;
11. commits state and all audit facts through the existing durable outbox.

External Git effects remain inside the existing mutation-intent and quarantine
protocol. The engine consumes their verified outcome; it does not make those
effects transactional by pretending they occurred atomically with state.

Kernel policy always overrides the graph:

- `DONE` and `CANCELLED` require explicit confirmation;
- unknown task, evidence, workflow, or handler versions fail closed;
- task and workspace ownership writes require their locks;
- evidence and approval currentness cannot be disabled;
- the graph cannot broaden filesystem or Git authority.

**Alternative considered:** Let each node handler own its complete transition.
Rejected because it recreates the current distributed transition semantics.

### 5. Separate task, node, and executor state

Task lifecycle remains the durable user-facing lifecycle. Node instances use:

```text
PENDING
READY
RUNNING
WAITING_APPROVAL
WAITING_EXTERNAL
BLOCKED
SUCCEEDED
FAILED
SKIPPED
```

The deterministic scheduler computes the ready frontier from successful facts,
dependency edges, approval facts, and retry policy. It does not ask an LLM to
rediscover a fixed dependency graph.

Executor runtime state is stored only as a resumable handle associated with
`task_id`, `node_instance_id`, repository ID, and attempt. A Codex thread ID,
Agents session, or external job ID is not workflow truth. A failure before
durable claim/dispatch may withdraw the unstarted record and create a new
bounded attempt. After claim, loss of an authentic live handle or complete
stored receipt quarantines the scope with zero redispatch; a new attempt is
legal only after an independently authorized `ABANDONED` reconciliation proves
the prior effect is quiescent with no accepted business outcome. No handle
failure can erase or advance the durable node result.

The coarse `status` projection remains for existing CLI and UI callers. For a
parallel frontier it reports the bundle-defined phase, while detailed node
state is available through the new agent projection.

### 6. Add deterministic repository map/join

A `map_repository` node expands into one node instance per selected repository.
The bundle and a task-local artifact validated against the package-owned
`dev-flow-repository-plan/v1` schema provide dependency edges and shared
contract artifacts. The repository plan canonically binds its input revision,
monotonic map epoch, repository identities and set, dependency and interface
contract digests, approved paths, worktree, concurrency, retry, integration,
and evidence policies into a semantic-input digest. Explicit approval binds the
plan artifact and byte digest, canonical DAG digest, map epoch, repository set,
interface contracts, input revision, and semantic-input digest while recording
the separate approval commit revision for audit. Later CAS revisions caused by
approval, expansion, leases, results, barriers, or other workflow mutations do
not stale the plan unless a bound semantic input changes. Telemetry is written
only to a separate observational store and never advances task revision. A
bound input change invalidates approval and expansion rather than patching the
plan in place. Only dependency-ready instances become `READY`.

The action-execution index admits one scoped dispatch record per ready
repository/node/worktree/lease and permits disjoint records to claim and reach
durable asynchronous handoff concurrently. Each handoff journal closes after
its launch receipt is committed; the long-running worker remains governed by
its separate lease and runtime handle. Target-bound cancellation, stop, and
reconciliation use kernel-priority control child records, so an active runtime
cannot block its own safe termination while ordinary overlapping work remains
forbidden. Result acceptance and barrier changes remain serialized by current
task revision. Quarantine blocks the affected scope and dependency closure,
not unrelated repositories unless the pinned plan or an exclusive task policy
requires it.

Each assignment binds:

- task, revision, node, attempt, and repository identity;
- exact controller-owned worktree;
- approved paths and write policy;
- plan and interface-contract digests;
- required playbook and evidence;
- allowed executor capabilities.

Workers edit only their assigned repository worktree and return a structured
result. They do not call state-transition tools. The manager or deterministic
host serializes result acceptance through expected-revision mutations.

Agent-plane mutations additionally require an opaque, short-lived
manager-capability proof scoped to task, manager session, actions, expiry, and
single-use request nonce. Only its verifier and audit state persist; adapters
pass the proof through a manager-only secret channel, never arguments, logs, or
worker assignments. Worker lease credentials identify candidate output but
grant no controller mutation. Parallel writable dispatch is enabled only when
the host can exclude the manager secret, controller data directory, state
paths, and mutation tools from the worker while granting its exact worktree. A
host that cannot prove this boundary uses manager-owned serial execution.

Lease expiry revokes authorization but does not prove process quiescence.
Barriers and integration capture require either an authenticated stop for the
same runtime assignment plus a post-stop worktree snapshot, or explicit
reconciliation with termination or isolation evidence and two equal complete
postcondition snapshots over a monotonic-clock stability interval whose
positive kernel minimum cannot be reduced by workflow or configuration. An
expired-but-live or termination-uncertain worker blocks replacement dispatch,
barrier closure, integration capture, and completion.

A join node succeeds only after its policy is satisfied and all required
results remain current. Failure, cancellation, timeout, or a stale repository
fingerprint produces an explicit blocked or retryable node outcome. Final
cross-repository verification and review use complete current snapshots.

**Alternative considered:** Use an agent manager to decide fan-out dynamically
for every task. Rejected for known repository graphs because it adds planning
tokens and makes replay less deterministic.

### 7. Keep the CLI authoritative and add a thin typed MCP adapter

The existing JSON CLI remains fully supported and is the recovery surface when
Codex integration is unavailable. Parser definitions are generated from
`CommandRegistry`, preserving existing command spellings and error codes.

An opt-in `agent-v1` response profile adds compact tools equivalent to:

```text
task-next
node-description
evidence-read
action-preview
action-apply
worker-result
```

The bundled MCP server is a standard-library stdio adapter over the same
application services. It implements only the protocol required for
initialization, tool discovery, and tool calls. Tool schemas declare read/write
and destructive behavior accurately. Write tools still require controller
revision, evidence, gate, and intent validation; MCP approval is an additional
host boundary, not a replacement.

The package retains POSIX and Windows MCP profiles disabled by default, but
this V4 delivery validates and enables only the POSIX profile on macOS. The
Windows profile is an unvalidated compatibility artifact for this scope; the
CLI remains usable when neither profile is enabled.

MCP startup failure does not make task state unreadable: the Skill and hooks
fall back to the CLI locator already injected by the plugin.

Release acceptance exercises the exact isolated standard-library CLI launcher
with MCP, Hooks, Codex SDK, and Agents SDK disabled. The matrix restarts a
claimed or quarantined execution, opens and revokes scoped manager sessions
through the local secret channel, performs zero-redispatch `ACCEPTED` when a
verifiable stored receipt permits it, and otherwise proves the required
absence-of-host `UNRESOLVED` packet, user-action request, and safe stop at
every recovery boundary. Authenticated `ABANDONED` and declared
`COMPENSATED` MAY be exercised only when a trusted host actually supplies their
respective authority; they are not release requirements or macOS claims. An
unresolved task remains blocked rather than being reported complete, and the
already claimed dispatcher/executor and compensation-provider invocation
counts never increase.

**Alternative considered:** Replace the CLI with MCP or Codex App Server.
Rejected because it would remove the simplest standalone recovery surface and
add a host dependency to the controller.

### 8. Make Codex integration a dispatcher over current-node context

The public `follow-dev-flow` Skill remains the sole orchestration entry point.
It contains only invariant rules and asks `task-next` for the current action.
Node-specific instructions are small package-owned playbooks loaded only when
the current node references them. Independently invocable internal Skills
disable implicit invocation. A Skill declares an MCP dependency through
`agents/openai.yaml` only when one dependency identity is satisfiable on every
supported host. The current Codex Skill dependency schema has no optional or
OR dependency form, while the MCP companion schema has no OS-specific command
override. Therefore the package exposes explicit, mutually exclusive POSIX and
Windows MCP profiles, validates only the POSIX profile on macOS for this
delivery, does not publish a false mandatory Skill dependency, and retains the
exact injected CLI locator as the standalone baseline.

Hooks are extended as follows:

- `SessionStart`: inject controller, data directory, task, revision, current
  node, and next-action locators;
- `SubagentStart`: inject the exact assignment and playbook locator;
- `SubagentStop`: request continuation when the required structured result is
  missing, without committing state;
- `PreCompact`: persist a best-effort compact checkpoint outside target repos;
- `PostCompact`: emit only supported common output and finish silently;
- `SessionStart` with compact source: re-inject the current locator;
- `PreToolUse`: retain advisory protected-operation guardrails;
- optional filtered `PostToolUse`: record non-authoritative runtime metrics.

Hook output is digest-deduplicated and bounded. Hooks never execute a workflow
transition or certify evidence.

Native Codex subagents are the default interactive executor. `codex exec` with
JSONL and output schema is the lightest headless executor. Codex SDK threads and
`codex mcp-server` plus Agents SDK remain optional external adapters, not
controller dependencies.

External discovery capabilities are identity-covered node policy. In
particular, codebase-memory assignments and evidence bind one explicit
`baseline` or `current-generation-workspace` phase, a generation, repository,
source snapshot, and controller-selected project ID. Baseline and current
generation always use distinct project IDs; the adapter rejects reuse or any
phase/generation/source mismatch before evidence acceptance, and material
conclusions still require confirmation in the bound source.

Externally visible writes use a serial two-boundary bridge. The controller
never calls the provider directly and never interprets a boolean or serialized
field as host approval. It issues an opaque, expiring, one-shot workflow
authorization bound to the pinned bundle, action, execution, effect, canonical
request digest, target, gate, and nonce. A host-owned bridge consumes it once,
obtains or enforces current host approval for that same request immediately
before provider invocation, and returns a request-bound receipt. Adapters that
cannot provide this boundary expose external reads only. Activation uses a
fake host bridge to prove denial, wrong-target, expiry, replay, missing-gate,
and successful serial workflow-gate/host-approval behavior without contacting
a real service.

### 9. Use content-addressed artifacts and bounded projections

The existing task-local artifact store remains authoritative. Node results and
receipts carry identities, semantic hashes, sizes, and locators instead of raw
logs, diffs, fingerprints, or reviews.

The compatibility `show` output remains unchanged. New projections include:

- `show --next` / MCP `task-next`;
- named node and evidence projections;
- response profiles for compact mutations;
- optional deltas since a known revision.

Initial budgets are:

- active hook checkpoint: at most 600 UTF-8 bytes in the common case;
- `task-next`: at most 1 KiB excluding an unavoidable diagnostic;
- common mutation receipt: at most 1 KiB plus action-specific required fields;
- node playbook: at most 4 KiB unless a validator records an exception;
- canonical manager-visible `NodeResult`: at most 2,048 UTF-8 bytes, with an
  inline summary of at most 512 UTF-8 bytes.

Budgets are regression gates, not truncation rules. If safety information does
not fit, the response stores the full artifact and returns a bounded locator.
Model-token counts remain observational because tokenizer choice is not a
portable acceptance contract.

### 10. Separate observability from audit

The controller records observational `dev-flow-node-telemetry/v1` entries in a
separate store outside target repositories and outside the task-state
transaction. A telemetry write never changes task bytes, task revision,
durable outbox, guards, evidence, approvals, readiness, or plan currentness.
The store uses a controller-owned `telemetry/node/` root, an independent
telemetry lock, canonical content-derived record identities, and atomic
idempotent file creation; it never calls the task commit or outbox service.
Reusing an identity with different bytes, a corrupt record, or an unavailable
or unwritable telemetry store produces only an observational diagnostic and
cannot fail, retry, or reinterpret the workflow action that generated it.
Each entry binds task, pinned bundle, node instance, optional repository, the
observed task revision, attempt, executor policy, outcome,
start/end/duration, response bytes, artifact bytes, and a usage object. Usage
explicitly declares `available` or `unavailable`; when available it stores
separate non-negative input, cached-input, output, and reasoning-output token
counts exactly as supplied by the adapter. Failed attempts remain separate
records so retry waste is attributable. `codex exec --json` usage and
user-enabled Codex OTel can provide model-level observations. User prompt
content remains disabled in telemetry by default.

Controller events remain the audit and recovery record. OTel, Agents traces,
model summaries, and token metrics are never accepted as transition evidence.
Missing, malformed, or contradictory telemetry is recorded as unavailable or
diagnostic and cannot change a node outcome.

Model and reasoning choices use logical policies such as `economy`, `balanced`,
and `critical`, resolved by host configuration. Workflow bundles do not pin
rapidly changing model names.

## Risks / Trade-offs

- **[Bundle pinning increases package size]** → Retain every bundle and handler
  version referenced by supported active tasks; provide inventory validation
  and an explicit future retirement policy rather than deleting old versions.
- **[A data-driven graph could appear to grant authority]** → Keep terminal,
  locking, evidence, approval, path, and Git invariants in kernel code; restrict
  the graph to versioned registered IDs and bounded write paths.
- **[Shadow and legacy paths temporarily duplicate logic]** → Add golden vectors
  and production-safe comparison metrics, migrate one edge family at a time,
  and delete a legacy branch only after equivalence tests cover it.
- **[A hand-written stdlib MCP adapter can drift from the protocol]** → Keep the
  surface deliberately small, version its protocol fixtures, validate against
  an MCP client/inspector when available, and preserve CLI fallback.
- **[Parallel workers can increase total model tokens]** → Use deterministic
  fan-out only for independent ready nodes, pass bounded context, measure token
  multiplier and wall-clock gain, and fall back to serial execution when the
  gain is insufficient.
- **[Worker edits can conflict]** → Give each worker a distinct
  controller-owned worktree and repository assignment; never permit concurrent
  controller state writers.
- **[Same-user workers are not isolated by Python]** → Require manager
  capabilities and host-proven secret/data-dir/tool separation before parallel
  writable dispatch; otherwise use the serial manager path and reject
  out-of-scope results through evidence checks.
- **[Lease expiry can race a still-live writer]** → Treat expiry only as
  authorization revocation; require authenticated stop or explicit stable
  reconciliation before barriers or integration snapshots.
- **[Hook lifecycle behavior varies by host version]** → Feature-detect event
  data, remain fail-open, and make every hook optimization optional.
- **[Response-size budgets could hide required detail]** → Store full content as
  a validated artifact and return a locator; never silently truncate evidence
  required by a guard.
- **[The independent cross-platform change may land concurrently]** → Preserve
  dirty worktree changes and keep edits independent; do not treat that change
  as evidence or a gate for this macOS-only delivery.

## Migration Plan

The milestone mapping for this migration is:

- V4-M0: tasks 13.5 and 13.6 only, followed by its explicit validation and stop.
- V4-M1: conditional tasks 13.1 through 13.3, inactive and developer-only.
- V4-M2: 13.1 through 13.3 first when M1 was skipped or incomplete, followed
  by remaining local closure in 5.13, 5.15, 7.12, 8.8, 13.4, and 13.7.
- V4-RC: tasks 14.1 through 14.13 under their existing ordering, macOS-only
  evidence, and external authorization gates. The independent
  `complete-cross-platform-support` change is not a prerequisite.

The detailed entry, exit, exclusion, and decision gates are maintained in
`MILESTONES.md`; the numbered migration below remains the technical dependency
order and cannot be bypassed by a milestone label.

1. Record golden vectors for every current full/lite edge, action-triggered
   transition, gate, invalidation, confirmation mode, and event batch.
2. Add exact canonicalization vectors, workflow schema, built-in
   legacy/full/lite bundles, catalog validation, and task-schema-v3
   read/storage support while keeping new bundle-aware creation disabled and
   production transitions unchanged.
3. Read labels, progress, next actions, index roles, Hook projections, and Skill
   routing from the catalog while old transition code remains authoritative.
4. Add shadow transition evaluation and fail tests on disagreement; production
   continues through the old engine.
5. Add `agent-v1`, `task-next`, compact receipts, artifact locators, and node
   playbooks to realize context savings before state semantics move.
6. Register commands and generate the CLI parser while preserving the public
   grammar.
7. Migrate pure transition edges into the engine, then action-triggered edges,
   and finally gates and Git-side-effect actions.
8. After every reachable single-repository edge and recovery path passes golden
   and shadow equivalence, validate task-schema-v3 V4 activation readiness while
   keeping every production profile inactive in this change. Any actual
   enablement of `full@4`/`lite@4` for new single-repository tasks requires a
   separately authorized follow-up change. Keep legacy adapters indefinitely
   for supported schema-v1/v2 tasks and keep reserved V3 identities fail closed.
9. Add the MCP adapter and expanded Hook lifecycle with feature detection and
   CLI fallback.
10. Add the canonical repository-plan schema and approvals, node instances,
    repository map/join, manager capabilities, host isolation checks,
    assignment leases, quiescence reconciliation, result acceptance, and
    barrier tests; validate `full@4` multi-repository activation readiness only
    after its complete recovery suite passes while keeping production creation
    inactive until a separately authorized follow-up change; update the
    dispatcher Skill.
11. After equivalence and compatibility are proven, complete the explicit
    `RuntimeServices` boundaries and audit the shared-loader compatibility
    contract. Retain the ordered loader for this change; defer physical
    ordinary-module conversion to a separate OpenSpec change. Finish docs and
    telemetry reports, and update the canonical candidate
    allowlist and package inventory for `workflows/`, schemas, playbooks, MCP
    configuration, runtime modules, and tests until every canonical input is
    stable.
12. Historical V3 fact: after its inputs stabilized, the process froze
    `first-introduction.json`, applied the V3 cachebuster, appended the
    `full@3`/`lite@3` and legacy reservation prefix, froze one V3 candidate and
    host snapshot, and completed the recorded local suite and validators. These
    facts establish reserved bytes only; V3 did not complete pre-handoff
    independent review, reproducible handoff, native evidence, CI,
    installation, publication, or activation.
13. Restart implementation under the V4 successor identities while keeping
    task schema v3: add `full@4`/`lite@4`, new versioned handler contracts for
    every changed transitive recovery semantic, the V3 existing-task
    fail-closed policy, the required absence-of-host `UNRESOLVED`
    operator-intervention path, optional target-bound live `ABANDONED`
    evidence, the optional workflow-gated and host-one-shot-approved
    `COMPENSATED` path, append-batch ledger validation, and chained
    introduction-epoch provenance. Preserve the entire V3
    bundle/handler/ledger prefix and `first-introduction.json` byte-for-byte.
14. Complete every still-open effect matrix, reconciliation, multi-repository
    activation-readiness, and CLI-only recovery task against the exact V4
    bundles. Re-run golden/shadow/legacy compatibility, recovery, focused
    macOS, and package validation while all V4 profiles remain inactive. The
    hostless matrix closes through bounded manual intervention and must not
    fabricate or claim a trusted-host success. Do not reuse a V3 pass as V4
    evidence or infer Windows/Linux coverage.
15. Only after all V4 identity-covered inputs are stable, apply the new
    cachebuster, freeze the successor introduction-epoch manifest, and append
    the sorted V4 reservation batch after the immutable V3 prefix without
    installation, publication, handoff, or activation. Then freeze one V4
    canonical candidate and its separate mode-sensitive host snapshot.
16. Against that exact V4 digest, run only the smallest directly relevant
    macOS test selections, import and changed-file syntax audits, every
    applicable Skill/manifest/POSIX-MCP/Hook/package/OpenSpec validator, and an
    independent pre-handoff code/specification/full-snapshot review that emits
    the required external review record. Discovery, a full test suite, and
    broad unrelated aggregation are prohibited.
17. Create and independently verify the reproducible V4 handoff, then obtain
    the matching native macOS report. Missing or mismatched required native
    evidence remains an unmet completion gate and MUST NOT be replaced by V3
    evidence.
18. Change only OpenSpec progress after the report, then run post-report strict
    validation and independent host-local/full-diff review while proving the
    V4 canonical digest is unchanged.
19. Only after explicit authorization, run the directly relevant macOS CI
    selections without a full suite; only after they are green and separate
    macOS-host installation authorization is received, perform the first
    actual plugin installation. Activation or pin eligibility remains a
    separate explicit decision after all profile-specific gates pass.

Rollback is version-oriented:

- disable MCP and new Hook matchers without touching task state;
- switch the package-owned activation manifest off for future schema-v3
  creation while continuing to read and fully execute every existing v3 task
  with the same shipped bundle;
- route new tasks back to frozen legacy bundles if shadow or engine comparison
  fails;
- never downgrade a task to a controller that does not recognize its task,
  evidence, or bundle contract;
- preserve all task data, worktrees, artifacts, and bundle versions throughout
  rollback.

## Open Questions

- The long-term bundle-retirement policy requires real task-age and installed
  version telemetry; no bundle referenced by a supported task will be removed
  in this change.
- Optional Codex SDK and Agents SDK adapters require separate packaging and
  dependency decisions. This change defines their executor contract but does
  not make them part of the standard-library plugin runtime.
