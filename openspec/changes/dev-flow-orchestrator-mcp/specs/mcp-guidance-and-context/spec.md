## Purpose

Define how the MCP server supplies sufficient, versioned, bounded guidance for the
current Dev Flow action without requiring Codex to read packaged Skills, Hook source,
CLI source, MCP implementation source, or raw task state.

## ADDED Requirements

### Requirement: Initialization instructions establish the complete global authority rule

The MCP server SHALL publish one initialization instruction string no larger than
4 KiB UTF-8. Its first 512 characters SHALL be self-contained and SHALL state that:

- the Controller is the only Dev Flow task-state writer;
- the client must discover or select one task before starting or resuming;
- the client must obtain exactly one current action;
- only that action may be performed across the immutable repository set;
- a mutation must submit the exact current binding and closed payload;
- stale, ambiguous, unavailable, or terminal authority must not be guessed;
- direct task-state file access is unsupported.

The remaining instruction text MAY explain the stable tool sequence and residual
local-shell boundary, but SHALL NOT embed the full workflow manuals, payload examples
for every action, implementation details, or content already available through tool
schemas.

#### Scenario: A client reads only the first 512 characters

- **WHEN** a host surfaces only the bounded leading server instructions
- **THEN** the client still receives the complete authority and sequencing rule needed to avoid starting, selecting, or applying work implicitly

#### Scenario: Instructions exceed the budget

- **WHEN** candidate instructions exceed 4 KiB or require text after byte 512 to understand the authority rule
- **THEN** package validation fails

### Requirement: Current-action guidance is generated only for the live projected action

`dev_flow_get_next_action` and successful mutation results SHALL include a bounded
action guidance object with schema `dev-flow-mcp-guidance/1.0.0`. Guidance SHALL be
selected from a versioned package catalog by the current action kind, projected
payload contract, workspace role, optional driver, obligation kind, and review
contract. It SHALL be generated only after the live Controller projection is valid.

Guidance SHALL include:

- `objective`: the exact outcome of the current action;
- `must_read`: projected contract, repositories, inputs, resources, obligations, and
  other current fields that must be inspected;
- `allowed_effects`: whether the action is read-only, source-producing, or
  source-verifying;
- `required_evidence`: the projected evidence and provenance that must be returned;
- `payload_notes`: semantic rules not expressible in JSON Schema;
- `driver`: exact optional-tool and fallback rules when applicable;
- `stale_recovery`: the safe refresh behavior;
- `completion_rule`: how to recognize Controller-confirmed progress or terminal state;
- `guidance_digest`: a lowercase SHA-256 over the canonical guidance object excluding
  its digest field.

Guidance SHALL NOT describe a different workflow phase, include another action's
payload, authorize unprojected retries, or substitute for the exact action binding.

#### Scenario: The current action is preflight

- **WHEN** the Controller projects `task.preflight`
- **THEN** guidance instructs only the bounded read-only preflight and an empty payload and does not include implementation or review procedures

#### Scenario: The current action changes source

- **WHEN** the projected workspace role is `produces-source`
- **THEN** guidance states the exact starting snapshot, change-ownership claims, repository scope, governing resources, and successor evidence required by that action

#### Scenario: The current action changes concurrently

- **WHEN** the task advances after guidance is returned
- **THEN** the guidance and binding are treated as stale together and the caller must refresh rather than reuse guidance against a new action

### Requirement: Normal MCP journeys do not require package-source reading

For every official workflow action, the combination of initialization instructions,
tool descriptions, generated input schema, compact current-action projection, and
action guidance SHALL contain enough information for a capable Codex executor to
perform and submit the action correctly. Public guidance SHALL explicitly state that
reading `skills/`, `hooks/`, `src/dev_flow_orchestrator/cli.py`, MCP adapter source,
launcher scripts, or Controller task-state files is neither required nor an accepted
normal step.

Installed journey validation SHALL observe model-facing file reads or equivalent
instrumented access and SHALL fail when a normal workflow reads package source to
discover invocation syntax, payload fields, sequencing, fallback behavior, or task
state. Repository source reads required to implement, verify, or review the user's
actual task remain allowed.

#### Scenario: Codex starts an installed feature journey

- **WHEN** the server and tools are available and the user supplies a requirement and prepared repositories
- **THEN** the journey can discover/start, obtain, execute, and apply every action without opening legacy Skill, Hook, CLI, MCP, or state implementation files

#### Scenario: Required semantics are absent from guidance

- **WHEN** an installed journey must inspect package source to determine a required payload field or workflow rule
- **THEN** validation fails and the missing semantic must be moved into schema, projection, or bounded guidance

### Requirement: Action guidance preserves task-change ownership rules

For every source-producing action, guidance SHALL require the executor to compare the
bound starting snapshot with the current complete repository-set evidence and submit
current `dev-flow-task-change-claims/0.4.0` for every and only task-owned observed
changed path. It SHALL require repository ID, relative path, classification,
criterion IDs, and purpose as defined by the current model. It SHALL prohibit silent
adoption of ambient drift, omission of a changed member, and direct editing of
Controller state.

For context and source-verifying actions, guidance SHALL prohibit source mutation.
For source-producing planning, guidance SHALL preserve the current governing and
reported resource rules, including repository-scoped identity and the semantic
OpenSpec tasks normalizer where applicable.

#### Scenario: Ambient drift exists

- **WHEN** a source-producing action observes a changed path not owned by the current task
- **THEN** guidance requires explicit current ownership handling or a fresh Controller path and does not authorize claiming the drift silently

#### Scenario: A verification action changes a repository

- **WHEN** a `verifies-source` action causes a member snapshot change
- **THEN** the action binding becomes invalid and the result cannot be recorded as current verification evidence

### Requirement: Optional-driver guidance is explicit and truthful

When the current action declares OpenSpec, codebase-memory, or independent-review as
an optional driver, guidance SHALL identify the exact tool, phase, required output or
evidence type, source-confirmation rules, current binding inputs, and declared
fallback. The executor SHALL use the named driver only when available and SHALL
record `available`, `degraded`, or `unavailable` truthfully in the current
`dev-flow-driver-result/0.4.0` envelope.

Guidance SHALL never describe fallback evidence as the named driver's result. Missing,
stale, partial, degraded, unavailable, unconfirmed, or internally inconsistent impact
evidence SHALL remain `unknown` for current assurance planning. The MCP server SHALL
not dynamically load or execute those external drivers itself in this change.

#### Scenario: OpenSpec is available

- **WHEN** a planning action declares OpenSpec and the tool is available
- **THEN** guidance requires current machine-readable status and instructions, concrete returned paths, governing resource bindings, and truthful driver provenance

#### Scenario: Codebase-memory is stale for one member

- **WHEN** a current graph generation cannot be matched to the member workspace
- **THEN** guidance requires degraded status, direct source confirmation as fallback, and conservative impact rather than focused assurance based on stale graph output

#### Scenario: The optional driver is unavailable

- **WHEN** a declared tool cannot be invoked
- **THEN** guidance identifies the exact fallback and limitations and never fabricates named-tool evidence

### Requirement: Assurance guidance executes only the current obligation

At assurance dispatch, guidance SHALL identify exactly the projected
`current_obligation`, its fingerprint, evidence contract, repository and integration
scope, task-change slice, prerequisites, remaining per-obligation attempts, applicable
class ceilings, and total-action authority. It SHALL direct the executor to run only
the smallest command or manual check required by that obligation and SHALL prohibit
undeclared retries or aggregate verdict submission.

Passing evidence MAY be reused only when the Controller projects current reuse for an
unchanged governing fingerprint and disjoint task-change slice. Intersecting or
ambiguous source changes, governing-resource changes, impact-closure changes, or
prerequisite changes SHALL require fresh projected evidence. A `not-required`
dimension SHALL remain a Controller decision.

#### Scenario: One focused repository obligation is current

- **WHEN** the plan projects one member-local repository check and no integration or review action
- **THEN** guidance requests only that check and preserves the Controller's not-required reasons for all other dimensions

#### Scenario: An attempt fails

- **WHEN** the current obligation execution fails, is incomplete, or is unavailable
- **THEN** guidance requires recording that actual result once and following the fresh projection rather than running an undeclared retry

#### Scenario: Existing evidence intersects later source change

- **WHEN** later task-owned changes intersect the evidence slice or invalidate a prerequisite
- **THEN** guidance treats the evidence as stale unless the Controller explicitly projects current reuse

### Requirement: Independent-review guidance has a stable package identity

When the current action requires independent review, guidance SHALL bind the exact
review contract, task ID, contract digest, plan digest, manifest digest, repository
set, per-member base/current evidence, aggregate workspace digest, current input
artifact manifest, and governing guidance/resource manifest. The package guidance
catalog used for review SHALL have a stable canonical digest. The projected review
contract SHALL expose that digest so current `dev-flow-review-finding/0.4.0` values
can bind the actual guidance reviewed without requiring a Skill file.

Guidance SHALL require one genuinely separate reviewer context for independent
assurance, complete task-wide review over every member and cross-repository behavior,
structured causal findings, and a fresh aggregate snapshot. Self-review MAY report
truthful findings but SHALL NOT claim independent approval. The Controller SHALL
remain verdict authority.

#### Scenario: A stable independent review passes

- **WHEN** a separate reviewer inspects the exact current aggregate inputs and returns no unresolved blocking, triage, or impact-gap finding
- **THEN** the result binds the projected guidance digest and the Controller may derive approval for that obligation

#### Scenario: Review guidance changes during a release

- **WHEN** any normative review instruction changes
- **THEN** its package guidance digest changes, package tests update, and stale findings bound to the old digest cannot be applied to the new projected contract

#### Scenario: No separate reviewer is available

- **WHEN** only the current executor can inspect the change
- **THEN** guidance requires unavailable independent assurance or truthful self-review and leaves satisfaction to current waiver and budget rules

### Requirement: Guidance and model context are release-bounded

The complete stable `tools/list` representation SHALL be no larger than 32 KiB
UTF-8. Each tool description SHALL be no larger than 512 UTF-8 bytes. One action
guidance object SHALL be no larger than 8 KiB. One text content summary SHALL be no
larger than 4 KiB unless an existing smaller domain bound applies. Server-info text
SHALL be no larger than 1 KiB. List and discovery summaries SHALL be paginated and
bounded as specified by the tool capability.

No response SHALL duplicate complete structured JSON in text, return a full ledger or
raw path inventory by default, truncate an action binding, or silently omit a field
needed to perform the current action. If a required exact result cannot fit its
bound, the tool SHALL fail with `MCP_RESULT_LIMIT` and a safe recovery statement.

#### Scenario: A current action fits the budget

- **WHEN** the exact binding, required current fields, and guidance fit their declared limits
- **THEN** the complete action is returned without unrelated workflow manuals or duplicate JSON text

#### Scenario: A required action exceeds the budget

- **WHEN** exact safe execution data would exceed the MCP result bound
- **THEN** the tool fails atomically with `MCP_RESULT_LIMIT` and does not return a truncated or apparently usable action

#### Scenario: Tool metadata grows

- **WHEN** a catalog change causes the serialized tool list or a description to exceed its release gate
- **THEN** package validation fails before installation
