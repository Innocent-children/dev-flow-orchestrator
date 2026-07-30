## ADDED Requirements

### Requirement: Every Codex adapter preserves controller authority
CLI, MCP, Hook, Skill, native subagent, `codex exec`, Codex SDK, and Agents Runtime integrations SHALL call the same controller services and SHALL NOT directly write task state, event logs, workspace claims, approvals, or evidence records. A model response, runtime handle, Hook decision, MCP approval, or Agents trace MUST NOT by itself satisfy a workflow guard.

#### Scenario: Model reports completion
- **WHEN** an agent says that a node or task is complete
- **THEN** the controller advances only after validating the required structured result, repository evidence, approvals, and current revision

#### Scenario: MCP host approves a tool
- **WHEN** Codex approves a write-capable MCP tool call
- **THEN** the controller still applies its own intent, evidence, gate, and revision validation

#### Scenario: Hook allows a tool path
- **WHEN** a Hook returns no denial for an operation
- **THEN** that absence grants no workflow or repository authority beyond the controller contract

#### Scenario: Lose an executor before durable claim
- **WHEN** a Codex thread, Agents session, or `codex exec` adapter fails before any effect is durably claimed or dispatched
- **THEN** durable task and node state remain unchanged and recovery may withdraw the unstarted record and create a new bounded attempt

#### Scenario: Lose an executor after durable claim
- **WHEN** a Codex thread, Agents session, or `codex exec` effect is already claimed and recovery cannot authenticate its live runtime handle or complete stored receipt
- **THEN** recovery quarantines without another dispatcher or executor invocation, returns hostless intervention when authority is unavailable, and permits only a fresh reconciliation from an authenticated original runtime, verifiable stored receipt, or future trusted host authority; another business execution remains forbidden unless a terminal authorized `ABANDONED` decision proves the prior effect quiescent with no accepted business outcome

### Requirement: The JSON CLI remains a complete compatibility and recovery surface
The existing CLI SHALL continue to operate without MCP, Codex SDK, Agents SDK, Node.js, or third-party Python packages. Existing command spellings, JSON stdout protocol, stable error codes, default response behavior, and schema-v1/v2 semantics MUST remain compatible. New command definitions SHALL be sourced from the sealed command registry.
For schema-v3 agent-plane mutations, the CLI SHALL accept manager proof only
through its local secret channel and SHALL provide explicit operator
authorization and revocation commands; it MUST NOT place the proof in argv,
JSON output, logs, Hooks, worker assignments, or task state.
The isolated CLI MUST NOT derive trusted-host facts from caller JSON,
environment values, inherited descriptors, manager approval, user statements,
or model output. When no trusted host can prove `ABANDONED` or provide the
one-shot `COMPENSATED` approval, the CLI SHALL return scope-blocking
`UNRESOLVED` with `dev-flow-v4-operator-intervention/v1`, ask the user to
inspect or operate, and exit without automatic redispatch, compensation,
archive, or unblock.

#### Scenario: Run without Codex integration
- **WHEN** the plugin's MCP server and lifecycle hooks are disabled
- **THEN** an authorized operator can inspect, preview, apply, and recover through the JSON CLI, while a task that lacks trusted recovery authority stops safely with bounded operator intervention instead of pretending completion

#### Scenario: Invoke an existing command
- **WHEN** a legacy caller uses an existing valid command and arguments
- **THEN** the CLI preserves its grammar and compatibility response

#### Scenario: Recover v3 through CLI only
- **WHEN** an authorized local operator explicitly opens a scoped v3 manager session without MCP or an SDK
- **THEN** the CLI performs every recovery step supported by authenticated evidence, keeps manager proof out of argv and every model-visible response, and returns `UNRESOLVED` plus the intervention packet when trusted host authority is unavailable

#### Scenario: Continue automatically after hostless recovery
- **WHEN** the CLI returns the operator-intervention packet for a claimed or quarantined V4 effect
- **THEN** it asks the user to inspect or operate and stops; it does not poll into a new attempt or invoke a dispatcher, executor, compensation provider, replacement lease, archive, or unblock operation

#### Scenario: Retry after trusted authority later appears
- **WHEN** a later CLI invocation can authenticate the original runtime, verify a complete stored receipt, or call through future trusted host recovery authority
- **THEN** it starts only a fresh separately authorized reconciliation attempt and does not treat the earlier packet or caller narrative as proof

#### Scenario: Generate parser entries
- **WHEN** a reviewed command is registered before registry sealing
- **THEN** the CLI exposes its parser and handler exactly once with the registered action identity

#### Scenario: Attempt to register after startup
- **WHEN** code tries to add or replace a command after registry sealing
- **THEN** startup or registration fails closed before task mutation

### Requirement: The plugin provides a thin typed MCP facade with accurate policies
The plugin SHALL be able to bundle a standard-library stdio MCP server exposing a small versioned tool surface for task projection, node description, evidence projection, action preview, action apply, and worker-result submission. Every tool SHALL have a strict input schema, bounded structured output, and accurate read-only, destructive, and write annotations. Users MUST be able to disable the server or restrict tools and approval modes without editing controller code.

#### Scenario: Discover MCP tools
- **WHEN** a compatible MCP client initializes the bundled server
- **THEN** it receives only the supported bounded workflow tools and their versioned schemas

#### Scenario: Start the packaged POSIX MCP profile
- **WHEN** validation selects the POSIX profile from the packaged `.mcp.json` on a supported POSIX host
- **THEN** it launches that exact configured command from the plugin root and completes initialization and tool discovery against the bundled server

#### Scenario: Exclude the Windows MCP profile from this delivery's evidence
- **WHEN** the V4 candidate is validated for macOS
- **THEN** validation selects only the packaged POSIX profile and makes no claim about the retained, disabled Windows profile

#### Scenario: Keep platform profiles mutually exclusive
- **WHEN** package validation reads the bundled MCP configuration
- **THEN** both platform profiles default to disabled, documentation requires enabling exactly the current-host profile, and validation rejects a configuration that enables both

#### Scenario: Call a read-only projection tool
- **WHEN** Codex calls `task-next` with an authorized task identity
- **THEN** the MCP server returns the controller's `agent-v1` projection without mutating state

#### Scenario: Call a write-capable tool
- **WHEN** Codex calls an apply or result-submission tool
- **THEN** the tool is marked write-capable and delegates to controller revision, intent, evidence, and approval checks

#### Scenario: Restrict the MCP tool set
- **WHEN** plugin-scoped configuration disables mutation tools
- **THEN** Codex can use permitted read tools but cannot discover or call the disabled tools

### Requirement: MCP failures degrade to explicit CLI fallback
An unavailable, malformed, incompatible, or interrupted MCP server MUST NOT make durable task state unreadable or trigger a hidden state change. The plugin SHALL surface a bounded diagnostic and the exact injected CLI locator required to resume. Partial or duplicate MCP requests MUST remain safe under request identity and controller idempotency rules.

#### Scenario: MCP server fails to initialize
- **WHEN** the bundled server cannot start or negotiate a supported protocol
- **THEN** the Skill identifies MCP as unavailable and uses the injected CLI controller and data directory

#### Scenario: Client disconnects after a committed mutation
- **WHEN** the controller commits but the MCP response is lost
- **THEN** the caller reloads current state and does not blindly replay the mutation

#### Scenario: Duplicate a result-submission request
- **WHEN** an MCP client retries the same request identity
- **THEN** the controller returns the prior accepted outcome or a structured idempotency conflict without double-committing

#### Scenario: Receive malformed JSON-RPC
- **WHEN** the server receives invalid protocol input
- **THEN** it returns or logs a bounded protocol error and performs no controller action

### Requirement: Lifecycle hooks provide bounded advisory context
The plugin SHALL support `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `SubagentStart`, `SubagentStop`, `PreCompact`, and `PostCompact` where the host exposes them. Hooks SHALL inject or preserve bounded locators, assignments, and recovery context, SHALL feature-detect event fields, and SHALL remain fail-open on internal errors. Hooks MUST NOT execute transitions or certify evidence.

#### Scenario: Start a primary session
- **WHEN** Codex starts or resumes in the scope of an active task
- **THEN** `SessionStart` injects the bounded controller, task, revision, node, and next-action locators

#### Scenario: Start a worker subagent
- **WHEN** a subagent starts for an assigned node
- **THEN** `SubagentStart` injects the exact task, node instance, attempt, repository worktree, allowed paths, and playbook locator

#### Scenario: Compact the conversation
- **WHEN** Codex compacts an active session
- **THEN** the hooks best-effort preserve and restore the current compact locator without treating the conversation as state

#### Scenario: Hook execution fails
- **WHEN** a hook encounters malformed state, unsupported host data, or I/O failure
- **THEN** the hook exits fail-open while controller commands continue to enforce all invariants

### Requirement: The public Skill is a current-node dispatcher
The `follow-dev-flow` Skill SHALL remain the public orchestration entry point and SHALL contain only workflow invariants, typed adapter selection, recovery rules, and current-node dispatch. It MUST load only the playbook and state sections referenced by the current controller projection. It MUST NOT require routine reading of global and subcommand help when a compatible typed tool schema or action description is available.

Skill metadata SHALL declare a bundled MCP dependency only when one dependency
identity is satisfiable on every supported host. When the host schemas cannot
express an optional choice between platform-specific MCP commands, the package
MUST NOT publish a false mandatory dependency; it SHALL instead ship explicit
mutually exclusive optional MCP profiles and preserve the exact CLI locator as
the portable fallback.

#### Scenario: Enter a known node
- **WHEN** `task-next` identifies one current playbook
- **THEN** the Skill loads that playbook and no unrelated flow or gate playbooks

#### Scenario: Use CLI fallback
- **WHEN** MCP is unavailable
- **THEN** the Skill invokes the injected CLI arguments without inferring a controller or data-directory path

#### Scenario: Package platform-specific MCP commands
- **WHEN** the MCP companion schema has one command field and Skill metadata has no optional or OR dependency form
- **THEN** the package exposes explicit mutually exclusive host profiles, declares no unsatisfiable hard dependency, and keeps the Skill usable through the exact CLI locator

#### Scenario: Encounter an unsupported action contract
- **WHEN** the controller and Skill do not share a compatible action or projection version
- **THEN** the Skill stops before mutation and reports the compatibility blocker

#### Scenario: Resume after a receipt
- **WHEN** a successful compact mutation receipt contains all next-action fields
- **THEN** the Skill uses that receipt without issuing an immediate duplicate task query

#### Scenario: Receive a hostless operator-intervention packet
- **WHEN** V4 recovery returns scope-blocking `UNRESOLVED` with `dev-flow-v4-operator-intervention/v1`
- **THEN** the Skill shows the bounded action-required packet, asks the user to inspect or operate, and stops without converting the packet or any reply into evidence, redispatch, compensation, replacement, archive, or unblock authority

### Requirement: Native subagents use manager ownership and scoped workers
Interactive multi-agent execution SHALL keep the primary manager responsible
for controller calls and the final user-facing result. Explorer and reviewer
agents SHALL default to read-only work. Writable workers SHALL receive one
explicit node assignment, one distinct controller-owned repository worktree,
and only a lease-scoped non-mutating assignment identity. Workers MUST NOT
receive or inherit the manager capability, controller data-directory access,
direct state paths, or mutating CLI/MCP tools and MUST NOT be delegated
ownership of the task state machine. An adapter that cannot enforce those host
capability boundaries MUST disable parallel writable dispatch and expose the
manager-owned serial fallback; Hook instructions alone are not sufficient
isolation.

#### Scenario: Explore several repositories
- **WHEN** impact analysis has independent read-heavy repository questions
- **THEN** the manager may run explorers concurrently and collect bounded findings as discovery evidence

#### Scenario: Implement independent repository nodes
- **WHEN** the deterministic frontier contains several writable repository assignments
- **THEN** the manager starts one scoped worker per assignment and retains state-transition ownership

#### Scenario: Worker attempts a controller mutation
- **WHEN** a worker tries to advance, approve, cancel, or otherwise mutate the task
- **THEN** the missing or wrong manager capability is rejected before persistence and the manager must submit a validated result through the controller

#### Scenario: Host lacks worker capability isolation
- **WHEN** the Codex host cannot exclude manager secrets, controller state paths, or mutation tools from a writable subagent
- **THEN** the adapter reports parallel writable execution as unavailable and keeps implementation under the manager-owned serial path

#### Scenario: Review the integrated result
- **WHEN** all implementation workers have stopped and the barrier is current
- **THEN** a separate read-only reviewer evaluates the complete repository snapshot

### Requirement: Headless and SDK executors are optional structured adapters
The executor registry SHALL support optional contracts for `codex exec`, resumable Codex SDK threads, and an external Agents Runtime. `codex exec` runs MUST use machine-readable events and a final output schema. SDK and Agents Runtime packages MUST remain outside the standard-library controller distribution. Their model output MUST be validated through the same `NodeResult` and evidence contracts.

#### Scenario: Run a fixed CI node
- **WHEN** a known node is assigned to `codex exec`
- **THEN** the adapter supplies a bounded prompt and output schema, records JSONL usage and result identity, and submits only validated structured output

#### Scenario: Resume a coding thread
- **WHEN** a node policy uses a Codex SDK runtime handle and the handle remains valid
- **THEN** the adapter resumes the same bounded node attempt without treating conversation history as state

#### Scenario: Use an Agents Runtime
- **WHEN** an optional external workflow needs dynamic specialists or HITL
- **THEN** the Agents Runtime may orchestrate Codex while the controller remains the sole authority for every durable transition

#### Scenario: Install only the base plugin
- **WHEN** no optional SDK or Agents Runtime package is installed
- **THEN** the CLI, MCP facade, hooks, Skills, and native Codex subagents remain functional

### Requirement: Codebase-memory phase identities are generation-separated
Every codebase-memory capability use SHALL bind an explicit phase, generation,
repository identity, source snapshot, and controller-selected project
identity. The baseline phase and current-generation workspace phase for one
repository MUST use distinct project identities, and an identity selected for
one phase or generation MUST NOT be inferred, reused, or accepted for the
other. Worker assignments, tool requests, returned evidence, and
package-owned validation SHALL all carry the same exact binding. A material
conclusion remains discovery evidence until it is confirmed in the bound
source snapshot.

#### Scenario: Query the baseline generation
- **WHEN** an impact node requests codebase-memory evidence for the baseline phase
- **THEN** the adapter uses the controller-recorded baseline project identity and baseline source snapshot and records that exact phase and generation in the request and result

#### Scenario: Query the current workspace generation
- **WHEN** an impact node requests codebase-memory evidence for the current-generation workspace phase
- **THEN** the adapter uses a distinct controller-recorded current-generation project identity and current workspace source snapshot and records that exact phase and generation in the request and result

#### Scenario: Reuse a project identity across phases
- **WHEN** an assignment, tool request, or result uses the same project identity for baseline and current-generation workspace phases or mismatches its recorded phase, generation, repository, or source snapshot
- **THEN** the controller rejects it before accepting the external evidence and performs no workflow mutation

### Requirement: External tools produce evidence candidates under explicit capabilities
MCP servers, apps, connectors, codebase-memory, web tools, and remote agents
SHALL be declared as node capabilities and SHALL be exposed only when the
active node requires them. Their results MUST be treated as candidates or
discovery evidence until a package-owned validator confirms the required
source, scope, schema, and currentness.

For an externally visible write, the controller SHALL only issue a scoped,
expiring, one-shot workflow authorization bound to the pinned bundle, action,
execution, effect, canonical request digest, target scope, gate decision, and
nonce. It MUST NOT call the external provider directly or accept a caller
boolean, model statement, serialized worker field, or prior receipt as host
approval. A host-owned write bridge SHALL consume that authorization exactly
once, obtain or enforce current host approval for the same request immediately
before the provider invocation, and return a request-bound invocation receipt.
If the pinned workflow gate is absent or denied, the authorization is invalid,
the authorization is expired or replayed, the target differs, current host
approval is absent, or the host cannot provide this serial enforcement
boundary, the externally visible write capability MUST fail closed without a
provider invocation.

The same two-boundary contract SHALL apply to every `COMPENSATED` write,
including Git, filesystem, registry, and provider compensation. The pinned
workflow's compensation gate and the host approval are independent. The
host-owned bridge MUST consume an opaque, non-serializable, expiring one-shot
approval bound to the original execution and receipt, reconciliation and
compensation identities, exact request digest, target, gate decision, and
nonce immediately before invocation. Neither the controller nor a caller may
serialize, persist, synthesize, or replay that approval.
If that bridge or approval is unavailable, recovery SHALL choose the bounded
hostless intervention behavior rather than asking the operator to restate
approval through the CLI. Trusted-host compensation success is optional and is
not claimed by this macOS release.

#### Scenario: Use an unrelated tool
- **WHEN** a node does not declare a tool capability
- **THEN** its worker assignment and optional role profile do not expose that tool

#### Scenario: Receive a structurally valid unsupported claim
- **WHEN** an external tool returns schema-valid output without sufficient source coverage
- **THEN** the controller does not accept it as complete evidence

#### Scenario: Trigger an external write
- **WHEN** a connector action would change externally visible state
- **THEN** the controller issues only the exact request-bound workflow authorization and the host-owned bridge invokes the provider only after its current approval policy also permits that same request

#### Scenario: Forge or replay host approval
- **WHEN** a caller supplies an approval boolean or serialized receipt, reuses an authorization, changes its target or request, or presents it after expiry
- **THEN** the host-owned bridge rejects the request without invoking the provider or committing workflow evidence

#### Scenario: Run without an approval-enforcing host bridge
- **WHEN** an adapter cannot prove that host approval and workflow authorization are consumed serially for the same provider invocation
- **THEN** external reads may remain available under their declared capabilities, externally visible writes are unavailable, and a quarantined V4 recovery returns scope-blocking `UNRESOLVED` plus bounded operator intervention

#### Scenario: Approve a compensation at only one boundary
- **WHEN** a compensation has workflow approval without the current host-owned opaque one-shot approval, or host approval without the pinned workflow compensation gate
- **THEN** the bridge invokes neither the compensation provider nor a local write executor, the original quarantined scope remains blocked, and no user or caller assertion upgrades the attempt from `UNRESOLVED`

#### Scenario: Replay an opaque compensation approval
- **WHEN** any caller reuses the host approval for another reconciliation attempt, request digest, target, compensation execution, or nonce
- **THEN** the bridge rejects it before invocation and no receipt or workflow evidence is committed

### Requirement: Plugin packaging declares runtime adapters without adding hidden dependencies
The plugin manifest and package inventory SHALL declare bundled Skills, lifecycle hooks, and MCP configuration using portable package-relative paths. Runtime import validation SHALL prove that controller, Hook, and bundled MCP Python files use only the standard library or package-internal modules. Installing or enabling the plugin MUST NOT silently install custom agents, optional SDKs, or external credentials.
All added `workflows/`, schemas, playbooks, MCP configuration, runtime modules,
and tests MUST enter this change's canonical candidate allowlist and
reproducible handoff. After all canonical inputs stabilize, macOS-only release
evidence MUST follow this order: cachebuster and release-ledger reservation
with no installation; candidate freeze; smallest directly relevant tests,
runtime/Skill/manifest/POSIX-MCP/package/OpenSpec validation, and pre-handoff
review; verified handoff; matching native macOS report; progress-only update;
post-report strict validation and review; then separately authorized focused
macOS CI; and only then the first actual installation under explicit macOS
host authorization. Every stage MUST bind the same canonical digest. Full test
suites and broad unrelated aggregation are prohibited. Missing required macOS
evidence keeps completion open, and no Windows or Linux evidence is implied.

For V4, finalization SHALL restart from `full@4`/`lite@4` identity
stabilization. It MUST preserve the V3 reservation prefix and immutable
`first-introduction.json`, freeze the V4 introduction-epoch successor manifest,
append the exact V4 reservation batch without exposure, and then produce a new
V4 candidate, independent supersession review, handoff, native macOS report,
post-report review, authorized focused macOS CI, and authorized macOS
installation in that order.
Completed V3 reservation and local validation steps MUST NOT satisfy any V4
runtime or external-evidence gate, and the absence of an unfinished V3 review
or handoff MUST NOT be represented as though one occurred.

#### Scenario: Validate the packaged adapters
- **WHEN** the release candidate is validated
- **THEN** the manifest, default and explicit hook discovery, MCP configuration, referenced playbooks, schemas, and runtime files are all present and portable

#### Scenario: Preserve controller facade compatibility
- **WHEN** the controller starts directly under `-I -S` or two independent facade modules are loaded through `spec_from_file_location`
- **THEN** each facade initializes complete sealed registries, catalog, and `RuntimeServices`, while its monkeypatch-visible operations, filesystem caches, and `ContextVar` values retain the documented facade-local identity and do not leak into the other facade

#### Scenario: Validate native MCP launch commands
- **WHEN** the candidate is validated on native macOS
- **THEN** validation selects its packaged POSIX profile and proves initialize plus tool-list through the exact configured command rather than invoking the Python server directly

#### Scenario: Introduce a third-party runtime import
- **WHEN** a shipped controller, Hook, or MCP runtime file imports an undeclared third-party module
- **THEN** the isolated runtime audit names the import and blocks packaging

#### Scenario: Install the base plugin
- **WHEN** a user installs the plugin
- **THEN** optional custom-agent profiles and SDK integrations remain opt-in and no external credential is created or copied

#### Scenario: Disable bundled MCP
- **WHEN** the user disables the plugin-scoped MCP server
- **THEN** package validation and the CLI/Hook/Skill fallback remain valid

#### Scenario: Freeze the expanded package candidate
- **WHEN** the release candidate includes workflow bundles, schemas, playbooks, MCP configuration, runtime modules, or their tests
- **THEN** canonical identity and handoff include every added path before native validation and post-report review begin

#### Scenario: Required native evidence is unavailable
- **WHEN** the exact frozen candidate cannot obtain the required native macOS evidence
- **THEN** the release remains incomplete and does not convert unavailability into a passing completion record

#### Scenario: Reuse V3 evidence for V4 finalization
- **WHEN** V4 finalization presents a V3 local suite, candidate digest, reservation, or unfinished external-evidence step as a V4 pass
- **THEN** release validation rejects the stage and keeps the corresponding V4 review, handoff, native, CI, installation, and activation tasks open
