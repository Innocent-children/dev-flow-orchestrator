## Context

The greenfield V4 runtime currently creates and consumes authority inside one
`Controller.apply` or `Controller.recover_effect` call. `AuthorityStore.issue`
invokes `MacOSApprovalPort`, which starts `osascript` and waits at most 120
seconds. This proves an independent macOS-user decision but cannot support a
user who needs more time to inspect a plan or who is temporarily away.

Codex documents `UserPromptSubmit` as a turn-scoped Hook event containing
`session_id`, `turn_id`, `cwd`, and the exact `prompt`. The Hook can therefore
forward actual later user input to a controller-owned confirmation store.
There is no documented host signature or opaque approval token on that event,
so conversation confirmation is a deliberate product trust-boundary change:
it is durable evidence from the configured Codex lifecycle channel, not
independent operating-system authentication against a hostile same-user local
process. `session_id` is correlation scope, not proof of a person. This design
assumes the configured Hook path and same-account local processes do not
maliciously forge lifecycle JSON; deployments that require protection from
that actor need a future signed host event or host-owned confirmation API.

The current workspace is the in-progress greenfield V4 architecture change.
There is no historical V4 data to migrate. The implementation must use only the
Python standard library, keep state outside target repositories, keep Hooks
small and fail-open on internal errors, and run only focused macOS validation.

## Goals / Non-Goals

**Goals:**

- Let a confirmation wait indefinitely for a later explicit chat reply.
- Bind the reply to the exact validated action or recovery request and consume
  it once.
- Keep task transitions, effect dispatch, revision checks and confirmation
  decisions controller-owned.
- Make a bare `同意` convenient when unambiguous and safe when multiple tasks
  or requests exist.
- Remove the redundant Lite workflow approval placement without coupling
  workflow depth to repository topology.
- Preserve CLI/MCP parity, resumability, recovery and bounded model-visible
  projections.

**Non-Goals:**

- Automatically approve destructive or authority-gated actions.
- Treat model output, a caller boolean, MCP tool approval, or a Hook allow
  decision as user confirmation.
- Claim that a Codex conversation event is equivalent to independent macOS
  identity authentication.
- Add timeout, polling, background dispatch, historical migration or a
  compatibility layer.
- Change full/lite selection, workspace strategy policy, repository ownership,
  effect settlement, commit, push, reset, clean or force-push policy.

## Decisions

### 1. The first exact apply attempt creates a durable request

`Controller.apply` will continue to validate the current node, revision and
payload before authority handling. For a contract with
`task-revision+<grant>`, authority resolution will:

1. derive the actor role, active lease owner when applicable, validated payload
   context and scope;
2. derive one canonical request binding containing task, workflow identity,
   revision, action, grant, actor role, local-account execution identity,
   scope, validated context, repository context and Codex session;
3. create or reload a deterministic
   `dev-flow-v4-confirmation-request/v1` record outside the repository; and
4. return `CONFIRMATION_REQUIRED`, `CONFIRMATION_PENDING`,
   `CONFIRMATION_DENIED`, or the confirmed one-time authority.

Creating a request performs no workflow-state write, Git operation or business
effect. Repeating the same binding returns the same request ID. This keeps the
existing `apply` and MCP action surface small; a separate caller-invocable
authority issuer is not added.

Alternative considered: add `authority-request` and `authority-confirm`
commands. Rejected because a public confirm command would make caller
assertion the authority and would enlarge the surface unnecessarily.

### 2. `UserPromptSubmit` is the only confirmation input

The Hook will pass `session_id`, `turn_id`, `cwd`, and `prompt` to a narrow
controller method before injecting the refreshed projection. The controller
will select pending requests belonging to active tasks for that repository
context and session.

Accepted replies are intentionally exact after whitespace trimming:

- `同意` or `approve` confirms only when exactly one request is eligible;
- `同意 <request-id>` or `approve <request-id>` confirms that exact eligible
  request;
- `拒绝`, `deny`, and their request-ID forms use the same ambiguity rules and
  mark a request denied.

Additional prose does not confirm. An ambiguous bare reply changes nothing and
returns bounded guidance listing request IDs. The Hook does not apply an action
or modify task state; it delegates confirmation-record mutation to the
controller and fails open if input or auxiliary state is unavailable.

Alternative considered: parse the session transcript. Rejected because Codex
documents the transcript format as unstable and the event already supplies the
exact prompt.

Alternative considered: pass `--approved true` from the agent after a reply.
Rejected because the controller could not distinguish a real user turn from a
fabricated caller assertion.

### 3. Confirmation has no clock expiry but remains revision-bound

A pending request has no timeout. It becomes unusable when its exact workflow
identity, task revision, current action, validated payload, scope, repository
context or session binding no longer matches. The private lifecycle is
`PENDING → CONFIRMED → CLAIMED|CONSUMED|STALE` or
`PENDING → DENIED`; denial is terminal for that exact binding and the same
apply/recovery input deterministically remains denied. Reconsideration requires
a new controller-owned task revision/binding or a new task, not a transport
retry or caller flag. Replay and cross-action use fail closed.

The store records the confirmation channel, local account, session ID, turn ID
and a prompt digest, but not the raw user prompt. Records are private and
bounded. Replaying the same session/turn/prompt digest is idempotent; reusing a
session/turn with different prompt content is rejected. Current pending,
confirmed, claimed and current denied records are never evicted. Stale and
consumed records are deterministically compacted only after their request ID,
binding digest and terminal status are preserved as a tombstone. Per-task
request/tombstone and per-session event-ledger limits fail closed with a stable
diagnostic rather than silently evicting live replay protection. There is no
migration because no historical records exist.

### 4. One confirmation index is the conversation-event serialization point

One private data-directory confirmation index and one exclusive confirmation
lock serialize request creation, candidate selection, prompt-event recording,
status CAS, terminal reconciliation and pruning across every task and
controller process using that data directory. The event ledger's unique key is
`(session_id, turn_id)` and stores the prompt digest plus the deterministic
decision result. Under that lock, a bare reply observes one atomic snapshot of
all indexed requests for the same session and canonical repository context:
if a concurrent second request serializes first the result is ambiguous; if
the reply serializes first it may confirm the then-unique request. The same
event can never decide two tasks.

Confirmation operations never hold the task, effect-journal or workspace lock
while holding the confirmation lock. The order is:

1. read and validate the current task/action/payload/scope;
2. acquire only the confirmation lock to request or revalidate confirmation,
   then release it;
3. use the existing effect-journal claim and task-revision CAS boundaries;
4. persist the confirmation request ID in the successful task event/approval
   evidence or effect-journal claim; and
5. reacquire only the confirmation lock to mark the exact request consumed.

Two confirmed retries can therefore race, but the task CAS or deterministic
effect claim permits at most one commit/dispatch. A crash after task commit but
before consumption is reconciled to `CONSUMED` only when current durable task
evidence contains that request ID. A crash after effect claim or receipt keeps
the request `CLAIMED`, and the existing effect recovery path—not a second
dispatch—owns settlement. Revision/action drift without matching task or
journal proof reconciles to `STALE`. Reconciliation itself performs no Git
operation, effect or task mutation.

### 5. Projections expose bounded confirmation state

`Controller.next` will augment `agent-v1` with current confirmation requests
for the current revision/action. Each entry exposes request ID, status, action,
grant, scope/context digest, session binding and exact reply syntax. It excludes
raw prompt text, authority records and unrelated task history. The
confirmation addition is deterministically ordered, capped at eight entries
and at 4,096 serialized UTF-8 bytes; overflow returns stable locators and
counts rather than partial private records.

Current `agent-v1` distinguishes no request, pending, confirmed and denied; it
does not project consumed or stale requests as current authority. `CONSUMED`
is returned in the successful apply/recovery response and remains in the
private audit locator. A lost-response retry receives the task/effect
idempotency or placement result and cannot revive the old request.

The Follow Dev Flow Skill will treat confirmation-required/pending responses as
a terminal condition for the current turn: explain the exact action, show the
request ID when needed, ask the user to reply, and stop. On the later turn it
reloads `next`; only `CONFIRMED` permits repeating the exact apply or recovery
operation.

### 6. Lite preflight selects its real topology entry

The package-owned workflow definition will derive one entry target and status:

- full, any topology: `baseline` / `PREFLIGHTED`;
- lite, single repository: `implement` / `IMPLEMENTING`;
- lite, multiple repositories: `repository-plan` / `ORCHESTRATING`.

`lite-approval` and `gate.lite.approve` are removed. Full
`plan-approval` remains and multi-repository full continues to enter the shared
repository kernel after that gate. This keeps workflow depth, topology and
workspace strategy orthogonal.

### 7. Recovery eligibility is checked before confirmation

Recovery input, journal binding and mode-specific eligibility are validated
before creating a confirmation request. `settle` and a provable `abandon` use
the durable confirmation lifecycle and retain the existing receipt/absence
checks. `reattach` and `compensate` currently have no authenticated live
runtime or host-owned compensation bridge, so they return the existing bounded
operator-intervention result directly and do not ask the user to approve an
operation the controller cannot perform. Conversation agreement is never used
as live-runtime, effect-absence, receipt or compensation evidence.

### 8. Package and data lifecycle remain operator-visible

The manifest registers one `UserPromptSubmit` Hook whose launcher, CLI and MCP
resolve the same greenfield package and data directory. Focused package
validation executes a representative packaged Hook event and scans the entire
shipped/current source closure for the removed popup port, `osascript`,
120-second timeout, old channel schema and graphical prerequisites. Immutable
archive and stale review evidence may retain historical wording only when
explicitly excluded from packaging and current documentation.

Confirmation storage uses local-account-only directory/file permissions and
distinct fail-closed codes for missing session routing, Hook unavailability,
unsafe permissions/symlinks, corruption, lock/write failure and capacity. No
automatic repair or deletion is attempted. Upgrade is an atomic source
cutover: old authority records are not promoted to confirmation evidence and
there is no dual runtime. Uninstall removes the plugin package but preserves
the external controller data directory by default; separate explicit cleanup
is documented only after active tasks and audit needs are resolved. Codex
host-owned sandbox or tool permission dialogs are a separate boundary and are
not suppressed by this plugin.

## Risks / Trade-offs

- **Conversation evidence is weaker than an OS dialog against a hostile local
  process running as the same account.** → Document the boundary explicitly,
  expose no public confirm command, keep confirmation state outside the
  repository, accept only exact Hook event fields, and retain all
  workflow/revision/action/payload/scope/replay checks. Treat session and local
  account as correlation/audit fields, never authenticated-human identity.
  Environments requiring independent OS authentication must not claim that
  this mode provides it.
- **A short reply could target the wrong task.** → Bare agreement or denial
  works only for exactly one eligible request in the same session and
  repository context; otherwise the controller requires the request ID.
- **The Hook may be disabled or fail.** → The action stays pending with no
  state/effect mutation; CLI/MCP return a stable diagnostic explaining that a
  matching `UserPromptSubmit` event is required.
- **A denied request could be reopened by an indistinguishable transport
  retry.** → Denial is terminal for the exact binding. Reconsideration requires
  a new controller-owned revision/binding or task; neither the Skill nor an
  identical CLI/MCP retry can reopen it.
- **A confirmed request can become stale while the user is reading.** → Bind it
  to exact revision/action/payload/scope and require a new request after drift.
- **Removing the Lite node changes workflow identity.** → Treat the current
  candidate as invalidated, update focused identity tests and documentation,
  and do not add migration because no historical tasks exist.
- **Existing tests assume synchronous auto-confirmation through a fake popup.**
  → Replace the fake popup with helpers that assert the first pending response,
  deliver a simulated exact `UserPromptSubmit`, and repeat the same call.

## Migration Plan

1. Add the new OpenSpec capability and deltas, then validate this change.
2. Implement durable confirmation storage, event serialization and controller
   integration while extending task/effect evidence only with the exact
   confirmation request locator needed for crash reconciliation.
3. Integrate Hook, CLI, MCP and Skill behavior.
4. Remove the Lite approval placement and update topology-aware entry tests.
5. Update user/install/upgrade/diagnostic/uninstall/architecture documentation
   and complete popup source-closure/package validation.
6. Run only the directly affected macOS test selections plus skill and manifest
   validators. Record the prohibited full-suite gate as unverified.

Rollback is source-level only: restore the prior candidate before installation.
No dual runtime, format migration or fallback selector is introduced.

## Open Questions

None. The user selected conversation confirmation and removal of the Lite
approval popup explicitly; the documented trust trade-off is accepted as part
of that product choice.
