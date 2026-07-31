## ADDED Requirements

### Requirement: Authority-gated operations create durable exact confirmation requests
Before an authority-gated workflow action or effect-recovery operation can
commit state or dispatch an effect, the controller SHALL validate its current
task, revision, action, payload, grant, actor role, actor identity and scope and
SHALL create or reload one deterministic
`dev-flow-v4-confirmation-request/v1` record bound to those values and the
current workflow identity, repository context and Codex session. Actor
identity here is the local execution account for audit and MUST NOT be
described as authenticated-human identity. The request SHALL have no
time-based expiry. Creating or reading it MUST NOT mutate workflow state,
dispatch an effect or modify Git.

#### Scenario: Request confirmation for an exact action
- **WHEN** an eligible authority-gated action has no matching confirmed request
- **THEN** the controller persists one pending exact-bound request, returns its bounded confirmation packet and performs no task or external-effect mutation

#### Scenario: Repeat the same pending operation
- **WHEN** the same session repeats an action with the same task, revision, action, grant, validated payload and scope
- **THEN** the controller returns the same request ID without creating another request or applying the action

#### Scenario: Resume after an arbitrary delay
- **WHEN** a pending request remains current while the user takes any amount of time to inspect it
- **THEN** the request remains pending without timeout, polling, denial or automatic application

#### Scenario: Restart while confirmation is pending
- **WHEN** the controller process exits and later reloads a still-current pending request
- **THEN** it returns the same durable request and does not reopen a popup or lose the decision point

#### Scenario: Retry a denied binding
- **WHEN** a request was denied and an identical apply or recovery input is submitted again
- **THEN** the same deterministic request remains denied, no new request is created, and reconsideration requires a new controller-owned task revision/binding or task

### Requirement: Only an exact later user prompt confirms a request
The controller SHALL accept confirmation input only from the configured
`UserPromptSubmit` lifecycle path containing a non-empty `session_id`,
`turn_id`, `cwd` and exact `prompt`. A model response, action payload, CLI or MCP
boolean, tool approval, Hook allow decision, transcript inference or caller
narrative MUST NOT confirm a request. A session identifier is correlation
scope only; the product MUST NOT claim that it authenticates the human author
or resists a malicious same-account process that can forge Hook input.
Request creation and prompt decisions across all tasks in one data directory
SHALL be serialized through one private confirmation index and lock. The
unique event key SHALL be `(session_id, turn_id)`.

#### Scenario: Confirm the only pending request
- **WHEN** one eligible request exists for the session and repository context and a later user prompt is exactly `同意` or `approve` after trimming whitespace
- **THEN** the controller marks that exact request confirmed and records the session and turn evidence without applying the action

#### Scenario: Confirm by request ID
- **WHEN** a later user prompt is exactly `同意 <request-id>` or `approve <request-id>` and that request is pending in the same session and repository context
- **THEN** only the named request becomes confirmed

#### Scenario: Reply ambiguously
- **WHEN** a bare agreement could match more than one pending request
- **THEN** no request changes and the controller returns bounded guidance requiring one displayed request ID

#### Scenario: Race a second request with a bare reply
- **WHEN** request creation for another task and one bare reply occur concurrently in the same session and repository context
- **THEN** one confirmation-lock order linearizes both operations, so the reply either confirms the request that was uniquely pending first or observes both and changes neither; it can never confirm both

#### Scenario: Include additional prose
- **WHEN** a prompt mentions agreement but is not one of the exact accepted reply forms
- **THEN** no request changes and no authority is created

#### Scenario: Replay or conflict one turn
- **WHEN** the same session/turn/prompt digest is observed again, or the same session/turn is reused with different prompt content
- **THEN** the data-directory event ledger returns the identical decision idempotently and the conflicting event changes no request in any task

#### Scenario: Race agreement and denial
- **WHEN** agreement and denial events race for one pending request
- **THEN** confirmation-lock CAS records exactly the first serialized terminal decision and the later event cannot change it

#### Scenario: Deny an exact request
- **WHEN** an unambiguous later user prompt is exactly `拒绝`, `deny`, `拒绝 <request-id>` or `deny <request-id>`
- **THEN** the selected request becomes denied and the bound operation remains unapplied

### Requirement: Confirmed authority is exact, revision-bound and single-use
A confirmed request SHALL authorize only its canonical binding. The controller
MUST revalidate current task state, revision, action, payload, grant, actor and
scope before any effect or commit. Confirmation locking MUST NOT nest with the
task, effect-journal or workspace lock. The controller SHALL release the
confirmation lock before using the existing task CAS or deterministic effect
claim, SHALL persist the confirmation request ID in the successful task
event/approval evidence or effect-journal claim, and SHALL then consume the
request at the declared successful lifecycle boundary. Missing, pending,
denied, stale, mismatched or consumed requests SHALL fail closed.

#### Scenario: Apply a confirmed action
- **WHEN** the same exact action is repeated after its request is confirmed and every current precondition still matches
- **THEN** the controller applies at most one mutation or effect and consumes the request at the declared successful lifecycle point

#### Scenario: Race two confirmed retries
- **WHEN** two processes retry the same confirmed effect-free or effectful operation concurrently
- **THEN** task revision CAS or the deterministic effect claim permits at most one commit or dispatch and both processes converge on one terminal request outcome

#### Scenario: Change the payload after confirmation
- **WHEN** any validated payload value or bound scope differs from the confirmed request
- **THEN** the confirmed request is unusable and the changed operation requires its own confirmation

#### Scenario: Advance the revision before application
- **WHEN** the task revision or current action changes after confirmation
- **THEN** the old request cannot authorize the new state and no effect or commit occurs from it

#### Scenario: Replay consumed confirmation
- **WHEN** a caller repeats an operation whose matching request was consumed
- **THEN** the controller returns a stable consumed or placement diagnostic and performs no duplicate effect or mutation

#### Scenario: Crash after task commit before consumption
- **WHEN** the exact task mutation durably records the request ID and the process exits before updating the confirmation record
- **THEN** read-only reconciliation marks that request consumed from the matching task evidence and never reapplies the action

#### Scenario: Crash after effect claim or receipt
- **WHEN** the effect journal durably binds the request ID and the process exits before task commit or confirmation consumption
- **THEN** the request remains claimed, ordinary apply cannot redispatch, and only the existing exact recovery lifecycle may settle it

#### Scenario: Drift without matching success evidence
- **WHEN** revision or action changes and neither task evidence nor the effect journal proves that request succeeded
- **THEN** reconciliation marks the request stale rather than consumed and grants no authority

### Requirement: Conversation confirmation is bounded auditable evidence
The private confirmation record SHALL identify its schema, request ID,
canonical binding, status, creation and decision timestamps, local account,
channel `codex-user-prompt/v1`, session ID, confirming turn ID and prompt
digest. It MUST NOT store the raw prompt, secrets, transient popup data or an
unbounded transcript. The confirmation directory and files SHALL be private to
the local account, reject unsafe symlink/permission/corruption states and fail
closed for authority while Hook delivery remains fail open. Current pending,
confirmed, claimed and current denied records MUST NOT be evicted. Stale and
consumed records MAY be compacted only after retaining a bounded tombstone
with request ID, binding digest and terminal status. Store limits MUST return a
stable fail-closed diagnostic rather than silently dropping live requests or
session/turn replay evidence. The product SHALL describe this as Codex
conversation evidence rather than independent operating-system authentication.

#### Scenario: Inspect confirmed evidence
- **WHEN** a reviewer reads a confirmed request record
- **THEN** the record proves the exact binding and user-prompt event identifiers without exposing raw conversation text

#### Scenario: Attempt to claim macOS authentication
- **WHEN** documentation or a result describes conversation confirmation as a macOS system-dialog identity proof
- **THEN** validation rejects the claim because the configured channel is `codex-user-prompt/v1`

#### Scenario: Open a private store
- **WHEN** the controller creates confirmation directories, indexes, records or event-ledger files
- **THEN** it uses local-account-only permissions and keeps every path outside target repositories

#### Scenario: Encounter unavailable or corrupt storage
- **WHEN** the confirmation store is missing required permissions, contains unsafe links or malformed records, cannot lock/write atomically, or exceeds its safe ledger limit
- **THEN** authority fails closed with a distinct bounded diagnostic, the Hook continues fail open, and no automatic repair, deletion or approval occurs

#### Scenario: Prune while another process decides
- **WHEN** terminal compaction races request creation, prompt observation or consumption
- **THEN** the same confirmation lock and status CAS preserve every live request, current denial and replay key while producing deterministic tombstones

### Requirement: Effect recovery uses the same durable confirmation lifecycle
Every actionable recovery mode that previously required a popup SHALL create,
confirm, revalidate and consume a durable request bound to the exact workflow
identity, task revision, execution ID and recovery mode. Recovery input,
journal binding and whether the selected mode can perform a mutation SHALL be
validated before request creation. A pending or confirmed recovery request
MUST NOT by itself prove effect absence, settlement, reattachment or
compensation.

#### Scenario: Request effect recovery
- **WHEN** an operator selects a supported recovery mode without a confirmed exact request
- **THEN** recovery returns a pending confirmation packet and leaves the effect journal and task state unchanged

#### Scenario: Confirm and settle an observed effect
- **WHEN** the exact settlement request is confirmed and the existing receipt and current-state checks prove settlement
- **THEN** recovery follows the existing single-dispatch settlement path and consumes the confirmation at the declared boundary

#### Scenario: Confirm an unprovable recovery outcome
- **WHEN** conversation confirmation exists but live or stored evidence cannot prove the requested recovery outcome
- **THEN** recovery returns bounded operator intervention and does not treat agreement as effect evidence

#### Scenario: Select an unavailable recovery capability
- **WHEN** reattach or compensate cannot authenticate the live runtime or invoke a host-owned compensation bridge
- **THEN** recovery returns the existing bounded operator-intervention result without creating a confirmation request for an operation it cannot perform

### Requirement: Confirmation data lifecycle is explicit
Installation and upgrade documentation SHALL identify the configured Hook,
shared data directory, trust boundary and diagnostic codes required by durable
confirmation. Upgrading from the popup candidate SHALL be an atomic source
cutover with no historical authority migration or dual runtime. Uninstall
SHALL preserve controller data, pending decisions and private audit records by
default; deletion requires a separate explicit operator action after active
tasks are resolved. The product MUST distinguish plugin-owned conversation
confirmation from Codex host sandbox or tool-permission approvals, which are
outside this plugin's control.

#### Scenario: Install or upgrade the plugin
- **WHEN** package validation inspects a fresh install or popup-candidate upgrade
- **THEN** one packaged `UserPromptSubmit` Hook and every CLI/MCP launcher resolve the same greenfield package and data directory with no popup fallback or dual dispatch

#### Scenario: Diagnose a pending decision
- **WHEN** confirmation cannot progress because session routing, Hook pickup, store permission, corruption, locking or capacity is unavailable
- **THEN** the bounded diagnostic distinguishes the cause and provides read-only inspection guidance without exposing raw prompt or authority records

#### Scenario: Uninstall with durable decisions
- **WHEN** the plugin is uninstalled while confirmation data exists
- **THEN** package removal leaves the external data directory intact and documentation requires separate explicit cleanup only after active tasks and audit-retention needs are resolved

#### Scenario: Encounter a Codex host permission prompt
- **WHEN** Codex itself requests sandbox, tool or filesystem permission
- **THEN** the plugin does not claim to suppress or auto-confirm that host-owned prompt
