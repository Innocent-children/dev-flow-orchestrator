# compact-agent-protocol Specification

## Purpose
TBD - created by archiving change introduce-versioned-workflow-kernel. Update Purpose after archive.
## Requirements
### Requirement: Agent projections expose only the current actionable frontier
The controller SHALL provide a versioned `agent-v1` task projection that contains the task ID, current revision, pinned workflow identity, current node or ready frontier, legal next actions, required state sections, confirmation mode, and playbook or artifact locators. The projection MUST be derived from the same workflow catalog and live state used by transition validation and MUST NOT include unrelated task history or repository index data.

#### Scenario: Read a single actionable node
- **WHEN** a task has one legal next action
- **THEN** `agent-v1` returns that action and only the state sections and locators declared for its current node

#### Scenario: Read a parallel frontier
- **WHEN** multiple independent node instances are ready
- **THEN** `agent-v1` returns a deterministically ordered frontier with stable node-instance and repository identities

#### Scenario: Encounter no legal action
- **WHEN** a task is blocked, terminal, or waiting for approval
- **THEN** the projection states that condition and returns the exact recovery, approval, or terminal locator without inventing a next action

#### Scenario: Detect catalog and state disagreement
- **WHEN** the pinned bundle cannot explain the live node or status
- **THEN** the controller returns a structured compatibility blocker and no action projection

#### Scenario: Project a reserved-unexposed V3 task
- **WHEN** a readable task is pinned to reserved but never activated `full@3` or `lite@3`
- **THEN** `agent-v1` reports the exact V3 identity, historical fail-closed blocker, and permitted inspection or target-bound safety locator without projecting an ordinary V4 action

### Requirement: Hostless recovery returns a bounded non-authoritative intervention packet
When the current Codex host cannot produce the trusted live authority required
for V4 `ABANDONED` or consume the opaque one-shot approval required for
`COMPENSATED`, the reconciliation response SHALL report scope-blocking
`UNRESOLVED` and SHALL include a packet whose
`schema` is `dev-flow-v4-operator-intervention/v1`. The packet SHALL contain
only that `schema`, `required: true`,
`reason: "TRUSTED_HOST_AUTHORITY_UNAVAILABLE"`,
`target_execution_id`, sorted unique `effect_ids`, normalized
`affected_scopes`, the exact `allowed_resume_conditions`
`authenticated_original_runtime`,
`verifiable_stored_receipt`, and `trusted_host_recovery_authority`, and false
values `automatic_redispatch: false`, `automatic_compensation: false`,
`automatic_unblock: false`, and `caller_assertion_can_unblock: false`. Task,
attempt, revision, status, and blocked state SHALL remain in the bounded
outer result whose `schema` is
`dev-flow-v4-action-reconciliation-cli-result/v1`.

The packet's canonical semantic-JSON encoding MUST be no more than 4,096
bytes. The controller MUST measure the complete
encoded packet before returning it and MUST NOT truncate an effect identity,
scope, or resume condition. If the limit would be exceeded, or the durable
effect graph/scopes cannot be normalized exactly, the original attempt and
scope remain `UNRESOLVED` and unchanged; the CLI fails with the stable
`ACTION_RECOVERY_OPERATOR_INTERVENTION_TOO_LARGE` or
`ACTION_RECOVERY_RESULT_INVALID` blocker and returns the target execution,
actual/limit byte counts when available, and the
`action-recovery-inspect` locator. Such an overflow or corrupt-target blocker
grants no recovery authority and permits no automatic action.

The packet MUST NOT contain raw authority, secrets, approval tokens, receipts,
journals, or unbounded target data. It is an action-required projection for
user inspection or operation, not evidence or approval, and presenting it back
to the controller MUST NOT close, redispatch, compensate, archive, or unblock
the original execution.

#### Scenario: Ask the user to intervene when host authority is unavailable
- **WHEN** recovery cannot authenticate the original runtime or obtain the exact current host-owned one-shot compensation approval
- **THEN** the response reports `UNRESOLVED`, identifies the blocked affected scopes, returns the bounded intervention packet, asks the user to inspect or operate, and exposes no automatic recovery action

#### Scenario: Treat an operator statement as proof
- **WHEN** a user, model, worker, manager, or caller states that the effect stopped, compensation is approved, or the scope is safe
- **THEN** that statement does not satisfy any allowed resume condition, and the original execution remains blocked without redispatch, compensation, archive, or unblock

#### Scenario: Gain trusted evidence after manual intervention
- **WHEN** a later explicit recovery request can authenticate the original runtime, verify a complete stored receipt, or use future trusted host recovery authority
- **THEN** the controller may create a fresh separately authorized attempt while treating the prior packet and `UNRESOLVED` attempt only as history

#### Scenario: Emit the largest permitted intervention packet
- **WHEN** the complete canonical intervention encoding is exactly 4,096 bytes
- **THEN** the controller returns every required identity and scope without truncation

#### Scenario: Exceed the intervention byte limit
- **WHEN** the complete canonical intervention encoding would exceed 4,096 bytes
- **THEN** the controller returns the stable overflow blocker and inspect locator while the attempt, target, index, affected scopes, and dispatcher count remain unchanged

#### Scenario: Read a corrupt durable intervention target
- **WHEN** the durable target has no complete effect graph or canonical affected scopes
- **THEN** the controller returns `ACTION_RECOVERY_RESULT_INVALID`, emits no partial intervention packet, and preserves the same blocked state

### Requirement: Compact projections have deterministic byte budgets
In the common successful case, the active hook checkpoint SHALL be at most 600 UTF-8 bytes and `agent-v1` task-next output SHALL be at most 1,024 UTF-8 bytes. The controller MUST measure serialized bytes after canonical encoding. Required safety or diagnostic information MUST NOT be silently truncated to satisfy a budget.

#### Scenario: Common task-next response fits its budget
- **WHEN** a normal task has one current node and bounded locators
- **THEN** the serialized `agent-v1` task-next response is at most 1,024 UTF-8 bytes

#### Scenario: Common checkpoint fits its budget
- **WHEN** a hook emits the active task locator for a normal task
- **THEN** the serialized model-visible checkpoint is at most 600 UTF-8 bytes

#### Scenario: Required detail exceeds the inline budget
- **WHEN** a complete diagnostic or result cannot fit its inline budget
- **THEN** the system stores the full validated content as an integrity-bound artifact and returns a bounded summary and locator

#### Scenario: Artifact persistence fails during overflow handling
- **WHEN** oversized required content cannot be stored and verified
- **THEN** the controller fails the operation with a structured diagnostic rather than returning incomplete evidence

### Requirement: Mutation receipts are action-scoped and backward compatible
The controller SHALL support an opt-in compact mutation response profile whose common envelope is at most 1,024 UTF-8 bytes plus action-specific fields required by the action contract. It SHALL include the task ID, committed revision, current node or status, changed section identities, action result summary, and next-action locator. Existing default CLI responses and `show` behavior MUST remain compatible for schema-v1 and schema-v2 callers.

#### Scenario: Receive a compact successful mutation
- **WHEN** a caller requests the compact response profile and a mutation commits
- **THEN** the receipt contains the committed revision and sufficient next-action data without a duplicate full workflow or unrelated indexes

#### Scenario: Continue using a legacy response
- **WHEN** a caller omits the compact profile
- **THEN** the existing response fields and spellings remain available

#### Scenario: Return an action-specific required field
- **WHEN** a mutation contract requires a preview intent, artifact identity, or recovery locator
- **THEN** the compact receipt includes that field even when the common envelope budget would otherwise be exceeded

#### Scenario: Lose a mutation receipt
- **WHEN** a caller cannot parse or retain a successful receipt
- **THEN** it can reload the task through a compact projection using the committed revision and durable state

### Requirement: Agent protocol payloads use integrity-bound artifact references
Raw logs, diffs, fingerprints, review reports, test output, and large node results SHALL be stored outside model-visible receipts and referenced by stable artifact identity, semantic digest, byte digest, size, media or schema kind, and task-scoped locator. A reference MUST be resolved and validated through the controller before its content can satisfy a guard or transition.

#### Scenario: Return a large test result
- **WHEN** test output is larger than the current response budget
- **THEN** the receipt returns the validated test evidence identity and artifact reference rather than the raw output

#### Scenario: Resolve an artifact reference
- **WHEN** an authorized caller requests a referenced artifact
- **THEN** the controller verifies task scope, path identity, size, and digest before returning its permitted projection

#### Scenario: Detect a tampered artifact
- **WHEN** referenced bytes or metadata no longer match the recorded digests
- **THEN** the evidence is rejected as non-current and no dependent transition advances

#### Scenario: Request an artifact from another task
- **WHEN** a caller supplies a locator owned by a different task
- **THEN** the controller rejects the request without disclosing the other task's content

### Requirement: Worker results use a bounded versioned schema
Every agent or external executor result SHALL conform to a versioned `NodeResult` schema containing node instance, attempt, input digest, status, bounded summary, artifact and evidence references, changed-file identities where applicable, blockers, plan-drift declaration, runtime handle metadata, and optional usage. The manager-visible result MUST use the tokenizer-independent byte ceilings below; full details MUST use artifacts.
The normative, tokenizer-independent limit for the canonical manager-visible
`NodeResult` envelope SHALL be 2,048 UTF-8 bytes, including all JSON syntax,
and its inline summary SHALL be at most 512 UTF-8 bytes. Token counts MAY be
recorded as observational telemetry but MUST NOT determine schema acceptance.
If required content does not fit, the adapter MUST persist and verify an
integrity-bound artifact before returning a bounded reference; it MUST NOT
truncate a required identity, blocker, drift declaration, or evidence locator.

#### Scenario: Submit a successful worker result
- **WHEN** a worker completes its assigned node
- **THEN** it returns a schema-valid result bound to the assignment input digest and current attempt

#### Scenario: Submit free-form prose
- **WHEN** an executor returns text that does not satisfy the required result schema
- **THEN** the adapter records no successful node result and requests correction or creates a failed attempt

#### Scenario: Report plan drift
- **WHEN** the worker discovers work outside its approved plan or paths
- **THEN** the result declares the drift and the controller keeps the node from succeeding until the plan is reassessed

#### Scenario: Return excessive result detail
- **WHEN** raw detail would exceed the bounded result contract
- **THEN** the adapter persists it as an artifact and keeps only a summary and reference in `NodeResult`

#### Scenario: Enforce a portable result budget
- **WHEN** different models or hosts serialize the same canonical manager-visible `NodeResult`
- **THEN** acceptance uses the 2,048-byte envelope and 512-byte summary ceilings rather than a model-specific tokenizer estimate

#### Scenario: Cannot persist an oversized required result
- **WHEN** required worker detail exceeds the inline ceilings and its artifact cannot be durably stored and verified
- **THEN** the result is rejected with a structured storage diagnostic and no node-success transition occurs

### Requirement: Context checkpoints are digest-deduplicated and revision-aware
Model-visible task checkpoints SHALL be keyed by reliable session identity, task ID, task revision, current-frontier digest, and projection contract version when those values are available. Unchanged context MUST NOT be injected repeatedly into the same session. Missing, corrupt, or unwritable deduplication state MUST fail open by emitting the current bounded checkpoint.

#### Scenario: Submit repeated prompts at one revision
- **WHEN** the same session submits multiple prompts without a frontier change
- **THEN** only the first equivalent checkpoint is injected

#### Scenario: Advance the task
- **WHEN** the revision or ready-frontier digest changes
- **THEN** the next eligible hook emits a new checkpoint

#### Scenario: Use two concurrent sessions
- **WHEN** two sessions observe the same task
- **THEN** one session's checkpoint marker does not suppress the other session

#### Scenario: Lose the checkpoint marker
- **WHEN** the marker is missing, corrupt, or cannot be read
- **THEN** the hook emits the bounded current checkpoint and does not block Codex

### Requirement: Usage telemetry is observational and node-scoped
Adapters SHALL record supplied input, cached-input, output, and reasoning token counts, duration, attempts, response bytes, artifact bytes, executor policy, and outcome when the execution surface provides them. Metrics MUST be associated with task, node instance, repository, observed revision, and attempt. Records SHALL be stored under a controller-owned telemetry root outside the target repository, task-state transaction, and durable outbox. The telemetry store MUST use its own lock, strict canonical records, content-derived identities, and atomic idempotent writes, and MUST NOT invoke the task commit service. Missing, contradictory, corrupt, conflicting, unavailable, or unwritable telemetry MUST NOT affect workflow evidence, action success, retry, task bytes, task revision, durable outbox, guards, readiness, or plan currentness.

#### Scenario: Record codex exec usage
- **WHEN** a `codex exec --json` run reports usage
- **THEN** the adapter records those counts against the exact node attempt

#### Scenario: Run an executor without token usage
- **WHEN** an execution surface provides no model usage
- **THEN** the result remains valid based on evidence while usage is explicitly recorded as unavailable

#### Scenario: Observe a failed retry
- **WHEN** an attempt fails after consuming model tokens
- **THEN** its usage remains attributable to retry waste and is not merged into a successful attempt

#### Scenario: Receive telemetry that conflicts with evidence
- **WHEN** telemetry claims success but controller-validated evidence fails
- **THEN** evidence determines the node outcome and telemetry remains observational

#### Scenario: Replay an identical telemetry record
- **WHEN** an adapter records the same canonical telemetry identity and bytes after losing its response
- **THEN** the separate store returns the existing record without duplicating it or changing task state

#### Scenario: Conflict or fail in the telemetry store
- **WHEN** a telemetry identity has different bytes or the independent telemetry store is corrupt, unavailable, or unwritable
- **THEN** the controller emits only an observational diagnostic while the originating workflow result and every task-state byte remain unchanged

### Requirement: Protocol errors remain stable, structured, and non-localized
Agent and MCP protocol errors SHALL use stable English error codes and machine-readable details. Localized display names MAY accompany stable IDs but MUST NOT replace them. A protocol parse failure, unsupported contract, stale revision, or missing required field MUST perform no implicit retry or state mutation.

#### Scenario: Receive an unsupported projection version
- **WHEN** a caller requests an unknown response contract
- **THEN** the controller returns a stable unsupported-contract error and lists supported versions

#### Scenario: Submit a stale revision
- **WHEN** an agent mutation supplies an earlier revision
- **THEN** the controller returns `REVISION_CONFLICT` and performs no mutation

#### Scenario: Omit a required result field
- **WHEN** `NodeResult` lacks a contract-required identity or digest
- **THEN** validation returns the exact missing-field diagnostic and does not infer it

#### Scenario: Display a localized node name
- **WHEN** a Chinese display label is available
- **THEN** the response retains the stable node ID alongside the localized label
