## Context

V5 has one immutable free-text requirement, one preflight snapshot, and an opaque append-only evidence list. A workflow node has one unconditional target, workflow validation rejects every cycle, and `test.record` rejects `passed: false` before persistence. This is a sound foundation for a short linear task, but it cannot retain the product state required by Stage 1: structured intent, failed-assurance evidence, bounded rework, typed artifacts, current-input freshness, decisions, or a terminal Delivery Dossier.

Adding built-in workflow IDs changes `PRODUCT_IDENTITY`, and changing `lite` changes its pinned workflow identity. Treating the feature as an in-place V5 extension would make existing tasks fail identity checks without an honest compatibility boundary. Stage 1 is therefore a V6 product generation with its own task, workflow, record, projection, and plugin-data identities.

The runtime remains local-first, Python-standard-library-only, single-task, single-repository, current-worktree, and single-executor. The controller remains the sole writer. Repository inspection remains bounded and read-only.

## Goals / Non-Goals

**Goals:**

- Preserve an original structured delivery contract and every accepted revision or decision.
- Ship `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full` as built-in workflows.
- Persist failed verification and review attempts and converge through declared finite rework paths.
- Record typed artifacts with contract, source-baseline, producer, digest, and input lineage.
- Derive freshness from current inputs without rewriting historical records.
- Give optional OpenSpec, codebase-memory, and independent-review stages an explicit fallback experience.
- Generate a deterministic Delivery Dossier for successful and exhausted official-workflow outcomes.
- Preserve V5 data unchanged in its V5 namespace and publish an explicit upgrade boundary.

**Non-Goals:**

- Multiple repositories, branches, managed worktrees, external Git effects, or cleanup ownership.
- Parallel agents, child tasks, claims, leases, fan-out, or fan-in.
- A general workflow workbench, arbitrary named-result router, UI, approval inbox, or role system.
- Authenticated actor identity, shared state, network connectors, or executable third-party drivers.
- Automatic V5 task migration or mutation of V5 state.

## Decisions

### Use a V6 identity and data namespace

V6 gives each compatibility surface its own identity and invalidation rule:

| Domain | Identity | What a change invalidates |
| --- | --- | --- |
| installed release | manifest/package version plus installed snapshot digest | release evidence for a different installed snapshot; never a stored task by itself |
| task state | task schema and V6 namespace | state whose root schema is unsupported |
| workflow language | workflow document schema plus adapter version | definitions the installed loader cannot validate or adapt |
| selected workflow | digest of the selected canonical document, its language identity, and adapter identity | only tasks pinned to the changed selected definition |
| built-in catalog | digest of sorted official IDs and file identities | package/catalog validation and new selection; catalog-only additions do not invalidate existing tasks |
| record | per-record schema and canonical digest | the affected ledger when a record schema is unsupported or its content is changed |
| artifact | artifact type/schema and canonical digest | the affected artifact and its lineage descendants |
| driver capability | declared tool/Skill identity recorded by the producer | that artifact's producer claim; tool availability does not change task identity |
| agent protocol | projection schema | consumers of that projection; persisted task replay remains unchanged |

The product-generation identity selects the V6 namespace and supported identity vocabulary; it does not aggregate the mutable built-in catalog. V6 loads only V6 state from `v6/`; V5 state remains untouched under `v5/`. Upgrade guidance tells users to finish or cancel V5 work before switching, or retain a V5 installation to inspect it. Rollback reinstalls V5 and points its locator at the unchanged V5 namespace.

An in-place V5 change was rejected because the built-in registry participates in product identity and every task pins a workflow digest. A permissive compatibility allow-list was also rejected because Stage 1 changes the replay model and would make a single store contain two transition languages.

### Store the original contract and an append-only record ledger

`TaskState` stores repository identity, the original frozen delivery contract, and an append-only `records` tuple. The contract includes a schema, revision, summary, stable acceptance-criterion IDs, scope, constraints, risks, non-goals, and open questions. A requirement-only start produces a bounded minimal contract so the `lite` path remains quick; normal Skill guidance supplies an explicit contract. Creation writes revision-zero state and is the one explicit non-mutation initialization boundary. Every later committed mutation appends one record, so `task revision == record count`; preflight is record and revision one.

Preflight, later workflow actions, contract revisions, and decisions all append typed records. The first mutation is always preflight, whose revision-one record owns its Git evidence and eliminates V5's separate mutable repository-preflight track. Contract revisions and decisions/waivers are available only after preflight; callers needing different initial scope supply the intended complete contract at task creation. Contract-revision records contain the complete new contract, reason, actor label, deterministic workflow reentry transition, and a safe current workspace snapshot exposed as a new-contract `revision-source` baseline. Each workflow declares a contract-revision target: official workflows return to impact/planning, `lite` returns to implementation, and the workflow-v1 adapter returns to preflight. The revision source is the only cross-contract source bridge: governing, assurance, and causal artifacts from the old contract remain historical and cannot satisfy new-contract inputs. This gives revised scope a declared path to new planning and assurance. A decision ID is unique within one task, so `(task_id, decision_id)` is its global identity. Within one contract digest, a `(kind, subject)` pair can be decided only once; correction requires a new contract revision and a new decision ID. This deliberately finite rule gives duplicate, conflicting, restart, and tamper replay one deterministic result without introducing a store-global lock. The effective contract and applicable decisions are derived by replay, preserving the original intent and every revision.

Separate mutable `current_contract`, `decisions`, and `artifacts` collections were rejected because one mutation could partially update them. A single append-only ledger keeps revision CAS, deterministic replay, and atomic replacement as the integrity boundary.

### Keep general workflow execution simple and add bounded assurance routing

Ordinary nodes retain one success target. Only `verification.record` and `review.record` may declare a `rework` contract containing a failure target, a positive `max_attempts`, and an exhausted target. A failed result is persisted, then replay deterministically chooses the rework or exhausted target from prior attempts with the same `(node_id, effective_contract_digest)`. Contract revision preserves old attempts historically and starts a fresh assurance budget for the new contract.

Workflow validation builds the complete target graph, requires every node to be reachable, and verifies that removing finite failure edges leaves an acyclic graph. Every remaining cycle therefore consumes at least one bounded failure edge, and every bounded edge has an exhausted route. This supplies Stage 1 rework without introducing Stage 2's general named-result routing language.

Rejecting failed evidence was unsuitable because interruption after a failed command would erase the reason for rework. Unbounded cycles were rejected because they cannot provide deterministic operator intervention when repair fails to converge.

### Record artifacts in a common lineage envelope

Typed action records use a common envelope containing record ID, kind, schema, task revision, action and node, attempt, timestamp, payload, chosen transition, effective contract revision and digest, observed repository snapshot, and an optional artifact descriptor. The artifact descriptor contains type, schema, digest, producer, declared workspace role, and resolved input record IDs and digests.

Workflow nodes declare the artifact type, workspace role (`context`, `produces-source`, or `verifies-source`), and typed input edges. A `governing` edge must identify the latest current artifact of its type and later replacement invalidates the consumer. A `source-predecessor` edge identifies the source baseline that the current action is intentionally replacing. A `causal` edge preserves a failed verification, review finding, or other reason for work without requiring that record to remain current completion proof after the work addresses it.

`next` resolves those edges before work begins and emits a canonical action binding containing task revision, action/node, contract digest, input record IDs/digests/edge kinds, the source predecessor, and the starting workspace snapshot digest. `apply` requires that binding, verifies its canonical digest, and CAS-checks task revision, contract, node, and every pinned record against the current ledger. A context or source-verification action also requires the captured current snapshot to equal its starting snapshot. A source-producing action may change the worktree; after the binding passes, apply captures the successor snapshot and atomically appends the artifact that links the pinned predecessor to that successor. The binding is a deterministic concurrency and provenance token rather than an authenticated actor credential.

In-memory and read-only impact/plan artifacts use `context`. A planning stage that creates or updates repository files, including OpenSpec, uses `produces-source` and binds concrete repository resources. Each resource binding records an authoritative path/content digest and a role: `governing` resources participate in freshness, while `reported` resources document generated progress state without governing the plan. OpenSpec proposal, design, and specs use their full safe content digests. `tasks.md` records both its raw reported digest and a governing semantic digest produced by replacing only list checkbox markers `- [ ]`, `- [x]`, and `- [X]` with one canonical unchecked marker before hashing. Checkbox-only progress preserves freshness; task text, ordering, or required test-work changes alter the semantic digest. The controller safely hashes declared resources even when they are otherwise clean in Git. Unrelated later code changes preserve the plan through source lineage, while changing or deleting a governing resource without a replacement planning artifact stales the plan and descendants. A later contract revision follows the workflow's planning reentry and produces a new current planning artifact.

A `produces-source` artifact establishes a new source baseline through its pinned predecessor. A `verifies-source` artifact must observe the latest source baseline exactly. This closes the interval in which repository-backed planning, documentation, or rework has changed files but has not committed its successor record, while unexpected worktree edits outside a bound source-producing action still invalidate the latest source authority and proof descendants.

The controller captures a bounded, content-sensitive, read-only Git snapshot for preflight, typed artifact, verification, review, and dossier actions. The snapshot digest binds `HEAD`, porcelain status, and canonical entries for tracked changed and untracked non-ignored paths. Regular files are opened without following the final path, bounded bytes are hashed, and identity metadata is compared before and after reading. Symbolic links hash their link-target bytes and are never followed. A clean initialized gitlink hashes its path, mode, index object ID, and current submodule `HEAD` without recursing; missing or dirty gitlinks fail the snapshot. Unsupported special files fail explicitly. Relative-path validation, parent containment checks, before/after `lstat`, repeated Git path/status enumeration, path-list, elapsed-time, and total-content budgets prevent escape, blocking reads, replacement races, and unverifiable evidence. The engine never executes a driver or repository-changing effect.

Embedding provenance only inside agent-supplied payloads was rejected because the model could omit or contradict authoritative task revision, workflow node, and Git baseline data.

### Derive freshness from contract, source, and artifact lineage

Freshness is a pure stage-sensitive view over immutable records. Every artifact must match the effective contract. Governing edges require their pinned inputs to remain the latest current artifacts of those types. Source-predecessor edges keep an explicitly consumed source lineage eligible through its current successor; only the newest source authority must match the inspected worktree. Causal edges require an intact, contract-compatible referenced record but do not turn an addressed failed review into current approval and do not stale the consumer when later assurance replaces that failure. Governing resource bindings must still resolve to the recorded safe content digests; reported bindings remain provenance only. A context artifact does not become stale merely because a downstream stage produces source. A source-verification artifact must observe the newest source authority and becomes stale when a later source authority is recorded. The projection reports stale reasons and excludes stale proof from completion coverage. Historical records remain unchanged. Porcelain status alone is display evidence and never serves as a freshness generation because it does not change when an already-modified file changes content again.

Persistently flipping a `stale` flag was rejected because a read-only repository change would otherwise require a controller mutation and could race with the filesystem state it describes.

### Make coverage and waivers controller-validated

Verification payloads map every acceptance-criterion ID to `proven` or `unverified`; `waived` is derived only from a current explicit waiver decision. Passing verification requires a non-empty command and current coverage in which every non-waived criterion is proven. Failed verification remains valid historical evidence and routes to rework or exhaustion.

Review records persist `approved`, `changes-requested`, and `unavailable` outcomes plus `independent` or `self` assurance level. An independent approval satisfies a required review. A self-review can contribute findings but cannot claim independent approval. A review-assurance waiver is a decision with kind `assurance-waiver`, subject equal to the exact review node ID, outcome `waived`, a unique decision ID, a non-empty actor label and rationale, and the effective contract binding. With that current waiver, an unavailable review may follow the success target and the dossier reports `waived`, its rationale, and the remaining assurance risk. Without it, unavailable or self-approved review consumes the same finite failure budget as changes requested and eventually reaches incomplete finalization. A successful official workflow can therefore finalize with fresh independent approval or an explicit current review waiver; an exhausted path visibly retains failed or unavailable assurance.

Allowing an agent to submit `waived` directly in verification output was rejected because it would collapse human authority into evidence production.

### Generate the Delivery Dossier inside the pure domain layer

`delivery.finalize` combines the effective contract, current decisions, current artifacts, verification commands/results, review findings, documentation evidence, repository baseline, remaining risks, and handoff recommendation into a typed `delivery-dossier` artifact. The engine calculates its digest and status. Official workflows have separate successful and exhausted finalization nodes so terminal `DONE` and `INCOMPLETE` states are explicit and replayable.

The agent supplies the change summary, remaining-risk details, and handoff recommendation; it does not construct authoritative coverage or provenance fields.

### Keep driver execution outside the runtime

Official workflow driver metadata uses `tool`, `optional`, `fallback`, and `produces`. The runtime projects the mapping, while package semantic validation enforces those fields for official assets and `$follow-dev-flow` invokes the named capability. OpenSpec stages obtain current JSON status and instructions for the selected change and record concrete artifact paths and digests. Codebase-memory stages keep baseline and current-generation workspace project IDs separate, select the phase-appropriate graph, confirm material conclusions in source, and mark unavailable, stale, or unconfirmed graph evidence degraded. Independent review binds its verdict and findings to the exact review snapshot. When an optional tool is unavailable, the Skill follows the declared fallback and records a `driver_result` in the artifact payload. Custom driver mappings remain opaque. V6 accepts new workflow-v2 definitions and existing absolute-path linear workflow-v1 documents; the definition's own version is stored independently from task schema version and adapted to the common V6 replay record boundary.

Dynamic imports, subprocess execution of driver code, and network connectors inside the core were rejected because they would reverse dependency direction and expand runtime authority.

### Preserve one controller and one current workflow action

CLI, Hook, Skills, and tests continue to use the same controller. `decide` appends a record without moving the workflow node. `revise-contract` appends one record and applies the workflow's declared contract-revision transition so revised scope re-enters planning deterministically. The projection continues to expose exactly one current workflow action. Workflow `apply` also accepts the exact action binding previously emitted by `next`. All three mutation paths use the task lock, revision CAS, replay validation, terminal-state rejection, and bounded payload rules.

The projection contains only the effective contract digest/revision and bounded summary, required input artifact IDs/digests/edge kinds/summaries, action binding, stale reasons, retry budget, and terminal dossier reference. Full record, artifact, and dossier bodies remain available through the read-only `show` view so the Hook does not inject an ever-growing ledger into each conversation.

## Risks / Trade-offs

- **Stage 1 is a major compatibility boundary** → V6 uses a separate namespace, validates exact identities, documents upgrade/rollback, and never modifies V5 data.
- **The record and routing model touches the integrity core** → record creation and replay share pure functions; store validation reconstructs every transition before atomic replacement; focused tamper, stale-revision, interruption, and retry tests cover the boundary.
- **Declared source stages intentionally change the worktree** → stage-sensitive freshness carries context artifacts forward, requires each source producer to consume its predecessor, and places verification after the last source-producing stage.
- **Content hashing can be expensive or observe unsafe/concurrent entries** → only changed and untracked non-ignored entries are read; no-follow, containment, type checks, gitlink rules, repeated enumeration, and strict byte/time/path budgets make unstable or unsupported snapshots fail without advancing the task.
- **Agent-supplied command results are claims about an executed command** → Skills require actual command execution before apply, records retain the exact command/result summary, and installed user journeys verify this sequence.
- **Optional tools can produce different artifact depth** → every optional stage declares its fallback and records which path produced the artifact; terminal requirements remain identical.
- **A single ledger can grow** → payload and record sizes remain bounded; Phase 1 tasks are single-user and finite; retention and task-portfolio controls remain later workbench capabilities.

## Migration Plan

1. Release the Stage 1 package as V6 with `v6/` controller data and V6 workflow identities.
2. Validate the tracked candidate package, every bundled workflow, every Skill, manifest metadata, and bilingual documentation.
3. Document that users finish or cancel V5 tasks before upgrading; users needing historical V5 inspection retain a V5 package snapshot.
4. Start all new tasks in V6. No V5 file is read, rewritten, copied, or deleted by V6.
5. Rollback by reinstalling V5 and using its unchanged V5 data directory. V6 state remains isolated.

## Open Questions

None.
