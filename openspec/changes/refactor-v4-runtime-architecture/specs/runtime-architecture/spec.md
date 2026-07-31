## ADDED Requirements

### Requirement: Greenfield runtime is independently importable
The V4 runtime SHALL be implemented as ordinary Python modules under
`src/dev_flow_orchestrator/`. It MUST start and pass focused tests without
importing, executing, wrapping, aliasing, or resolving symbols from
`scripts/dev_flow_parts/`. Runtime construction MUST NOT use `exec`, `eval`,
ordered source fragments, a shared global namespace, string-based operation
lookup, service locator, or dependency injection container.

#### Scenario: Import the skeleton in isolation
- **WHEN** Python imports the greenfield runtime with only the package `src` directory and standard library available
- **THEN** product model, store, engine, controller and CLI modules load without executing or importing the old runtime

#### Scenario: Detect an old runtime dependency
- **WHEN** a greenfield runtime module imports, reads, executes or resolves a symbol from `scripts/dev_flow_parts/`
- **THEN** architecture validation fails before the candidate can reach cutover

### Requirement: A minimal vertical slice precedes architecture expansion
The first greenfield milestone SHALL contain only the product matrix, V4 task
model, filesystem store, transition engine, controller, bounded Git reader and
JSON CLI required for `start`, `show` and `preflight`. It MUST prove all four
profile creations, explicit `--data-dir`, one state writer and one JSON stdout
object before another workflow capability is added.

#### Scenario: Run the minimal skeleton
- **WHEN** a caller creates, inspects and preflights a task through the greenfield CLI
- **THEN** each action crosses the same controller boundary, persists schema v4 state outside the repository and returns one structured JSON response

#### Scenario: Add a capability before the skeleton gate
- **WHEN** implementation attempts to add planning, review, recovery or multi-repository scheduling before the minimal slice passes its focused gate
- **THEN** the milestone remains open and the additional capability is not treated as part of the candidate

### Requirement: Every node has one explicit contract
Each workflow node SHALL declare one stable identity, typed input, typed output,
required authority, allowed state writes, effect kind, effect port,
idempotency binding, failure result and recovery action. A node function MUST
consume an immutable projection and return a decision or mutation plan; it MUST
NOT directly write task state, filesystem, Git, process, registry or external
systems.

#### Scenario: Inspect a node boundary
- **WHEN** a reviewer selects any packaged workflow node
- **THEN** its contract identifies every permitted input, output, authority, write, effect, failure and recovery without following an implicit global call path

#### Scenario: Node attempts a direct effect
- **WHEN** node logic attempts to write state or invoke an external effect outside its declared port
- **THEN** focused validation rejects the node before activation

### Requirement: One controller boundary owns mutation
`Controller.apply` or its final equivalently named application operation SHALL
be the only task-state writer. It MUST plan under current revision, execute only
the declared effect, and commit under renewed revision and receipt validation.
CLI, MCP, Hook, Skill, node functions, Git adapters and process adapters MUST
NOT commit task state directly.

#### Scenario: Commit an effect-free mutation
- **WHEN** an authorized action requires no external effect
- **THEN** the controller plans and atomically commits it under one task-lock scope

#### Scenario: Commit an effectful mutation
- **WHEN** an authorized action requires an external effect
- **THEN** the controller binds the plan, releases any inappropriate long-held lock, obtains a receipt, reacquires authority and commits only if revision, binding and receipt remain current

#### Scenario: Adapter attempts to write state
- **WHEN** a CLI, MCP, Hook, Skill or effect adapter tries to replace task state
- **THEN** architecture validation or the controller contract rejects the write

### Requirement: Conversation confirmation is resolved inside the mutation boundary
For an action whose node contract requires more than task-revision authority,
the controller SHALL validate the operation and create or reload an exact,
durable conversation confirmation request before an external effect or state
commit. The request MUST bind task, workflow identity, revision, action,
grant, local execution account, actor role, validated payload context,
repository/lease scope, repository context and Codex session. A later exact
`UserPromptSubmit` event MAY confirm or deny the request but MUST NOT execute
the action. The controller SHALL revalidate and consume a confirmed request
only while committing the same successful operation or its declared effect
lifecycle boundary. Public CLI and MCP surfaces MUST NOT accept an approval
boolean, authority issuer, actor assertion, authority ID, raw prompt,
serialized record or separate authority-issuance/confirmation command.
Conversation/session evidence is correlation and audit data, not independent
macOS or authenticated-human identity.

#### Scenario: Request and later confirm an exact mutation
- **WHEN** an exact gated operation has no current confirmed request
- **THEN** the controller persists one pending request, performs no guarded mutation, and proceeds only after a later exact user-prompt event is recorded and the operation is retried

#### Scenario: Review role uses the same local account
- **WHEN** one local account confirms implementation and later confirms an independent-review artifact through the configured conversation channel
- **THEN** both records retain the same audit account and distinct role/fingerprint bindings, and the runtime does not pretend that role suffixes, session IDs or Hook JSON prove a second person

#### Scenario: User denies or the conversation channel fails
- **WHEN** the exact request is denied or the configured Hook/store cannot record a matching event
- **THEN** the action remains unapplied before any external effect or state commit, task state stays unchanged, and no caller-supplied fallback can approve it

#### Scenario: Caller attempts to supply authority
- **WHEN** CLI or MCP input includes an approval boolean, actor, issuer, authority ID, raw prompt, serialized record or authority-issuance/confirmation operation
- **THEN** the public schema rejects that input and no grant is created

### Requirement: Greenfield cutover is atomic
The public CLI, MCP, Hook and Skill entrypoints SHALL continue to identify one
product and MUST switch to the greenfield runtime together. Before cutover the
new package SHALL be exercised directly by focused tests and SHALL NOT be
dual-dispatched from the public entrypoint. At cutover,
`scripts/dev_flow_parts/` and every old-only wrapper, manifest, validator and
test MUST be removed from the package.

#### Scenario: Inspect a pre-cutover worktree
- **WHEN** only part of the greenfield capability set is implemented
- **THEN** no public entrypoint chooses between old and new runtime based on command, task or environment

#### Scenario: Complete the cutover
- **WHEN** every required greenfield vertical slice passes its cutover gate
- **THEN** all public entrypoints resolve only the new package and package validation finds no executable old runtime path
