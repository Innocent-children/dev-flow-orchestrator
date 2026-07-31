## ADDED Requirements

### Requirement: Public adapters use one request-confirm-apply boundary
CLI, MCP, Hook and Skill SHALL delegate durable confirmation to the same
controller operations. Public apply and recovery inputs MUST NOT accept a
confirmation boolean, confirmation/request/authority ID, issuer identity,
actor assertion, raw user prompt or serialized authority/confirmation record.
Apply, recovery and projection inputs MAY accept bounded Codex session and
request-turn routing fields that carry no authority by themselves. An initial
exact apply or actionable recovery call MAY create a pending confirmation
request but MUST NOT perform its guarded task mutation or external effect.

#### Scenario: Request through CLI and MCP
- **WHEN** CLI and MCP submit the same authority-gated operation at the same revision and session
- **THEN** both receive equivalent pending request semantics and neither adapter creates authority independently

#### Scenario: Caller supplies any forbidden confirmation field
- **WHEN** public CLI or MCP input includes any approval boolean, confirmation/request/authority ID, issuer, actor, raw prompt or serialized record
- **THEN** the per-field strict-schema negative matrix rejects the input and no request is confirmed or applied

#### Scenario: Apply after a user prompt
- **WHEN** the controller has recorded a matching confirmed request from `UserPromptSubmit`
- **THEN** CLI or MCP may repeat the exact operation and the controller alone revalidates, applies and consumes it

#### Scenario: Run without the confirmation Hook
- **WHEN** CLI or MCP creates a request while the configured `UserPromptSubmit` Hook is unavailable
- **THEN** it returns a stable channel-unavailable or pending diagnostic and no public fallback can confirm the request

#### Scenario: Project one conversation session
- **WHEN** Hook, CLI or MCP requests the current projection with bounded session routing
- **THEN** the controller returns only current confirmation locators eligible for that task/session and the routing field itself grants no authority

### Requirement: UserPromptSubmit forwards bounded confirmation evidence
The `UserPromptSubmit` Hook SHALL feature-detect and forward `session_id`,
`turn_id`, `cwd` and `prompt` to the controller's confirmation observer before
injecting a refreshed bounded task projection. The Hook MUST NOT choose an
action, apply a transition, dispatch or settle an effect, or write task state.
Malformed or unavailable event fields SHALL fail open while every pending
operation remains unapplied. Fields SHALL be type-checked and length-bounded;
oversized or conflicting same-turn input changes no request.

#### Scenario: Receive an exact agreement
- **WHEN** Codex invokes `UserPromptSubmit` with all required fields and an exact accepted agreement
- **THEN** the Hook delegates the event to the controller, injects the refreshed confirmation status and performs no workflow transition

#### Scenario: Hook cannot observe the reply
- **WHEN** the Hook is disabled, times out or receives malformed fields
- **THEN** the user prompt continues but the guarded operation remains pending and cannot be applied

#### Scenario: Invoke another Hook event
- **WHEN** `SessionStart`, `PreToolUse` or another lifecycle event carries text resembling agreement
- **THEN** it cannot confirm a request

#### Scenario: Replay one prompt event
- **WHEN** the same session, turn and prompt digest is delivered again
- **THEN** confirmation observation is idempotent, while the same session and turn with different prompt content is rejected

### Requirement: The Skill pauses for durable conversation confirmation
When a controller response reports confirmation required, pending or
ambiguous, the Follow Dev Flow Skill SHALL explain the exact bounded operation,
show the request ID when needed, ask the user for one accepted reply form and
end the current turn. For denied it SHALL explain that the exact binding is
terminal and stop without retrying it. It MUST NOT poll, retry apply, fabricate
a reply, invoke the Hook manually or describe pending status as approval. On a
later turn the Skill SHALL reload the controller projection before continuing.

#### Scenario: Wait while the user reads a plan
- **WHEN** a plan-approval request is pending
- **THEN** the Skill ends the turn and the user may reply later without a dialog timeout

#### Scenario: Resume after agreement
- **WHEN** a later user turn has confirmed the exact current request
- **THEN** the Skill reloads current state and repeats only that exact operation

#### Scenario: Receive an unrelated reply
- **WHEN** the later user prompt does not confirm the request
- **THEN** the Skill leaves the operation pending and follows the new user instruction without claiming approval

#### Scenario: Receive a denial
- **WHEN** the current exact request is denied
- **THEN** the Skill does not retry or reopen that binding and explains that reconsideration requires a controller-owned new binding or task

#### Scenario: Validate pause and resume semantics
- **WHEN** package validation inspects the Follow Dev Flow Skill
- **THEN** semantic checks prove pending/ambiguous/denied paths end the turn, later turns reload projection first, and no path polls, auto-retries or invokes the Hook manually

### Requirement: The packaged confirmation channel is discoverable and singular
The plugin manifest SHALL register one packaged `UserPromptSubmit` launch path
that resolves the same greenfield package and data directory as CLI and MCP.
Installation and upgrade validation MUST exercise a representative event
through that packaged launcher and prove that `session_id`, `turn_id`, `cwd`
and `prompt` reach the controller observer. No legacy Hook, dual runtime or
adapter-specific confirmation store MAY remain executable.

#### Scenario: Discover the installed Hook
- **WHEN** package validation resolves the plugin manifest and every Hook, CLI and MCP command from a non-trivial installed cache path
- **THEN** exactly one greenfield confirmation channel is found and every adapter resolves the same data-directory contract

#### Scenario: Deliver one packaged user prompt
- **WHEN** the packaged Hook launcher receives a bounded `UserPromptSubmit` fixture
- **THEN** the four required fields reach the controller observer, the refreshed projection is returned, and no task transition or external effect runs

#### Scenario: Upgrade from the popup candidate
- **WHEN** the cachebuster/reinstall workflow builds the new package
- **THEN** manifest and source validation find no executable legacy confirmation entrypoint or fallback and do not migrate old authority records into trusted conversation decisions

### Requirement: Executable source contains no plugin-owned popup authority
Runtime, launchers, validators, Skills, tests, current architecture and user
documentation SHALL contain no executable or current-product reference to
`MacOSApprovalPort`, `/usr/bin/osascript`, the 120-second dialog timeout,
`macos-system-dialog/v1` or graphical-popup prerequisites. Package validation
SHALL scan the complete shipped/current source closure, with explicit
allowlisting only for immutable archive or stale-review evidence that is not
packaged or presented as current. This requirement does not cover Codex
host-owned sandbox or tool-permission dialogs.

#### Scenario: Audit the shipped closure
- **WHEN** package validation scans runtime, scripts, hooks, Skills, manifests, validators, focused tests and current docs
- **THEN** none of the forbidden popup symbols or behaviors is reachable or described as current

#### Scenario: Find a forbidden popup reference
- **WHEN** a forbidden symbol remains in any executable, packaged or current-product file outside the explicit historical allowlist
- **THEN** package validation fails before cachebuster, reinstall or activation
