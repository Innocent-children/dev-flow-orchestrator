---
name: follow-dev-flow
description: Start or resume the guarded V4 Dev Flow workflow for code, configuration, test, generated-file, or OpenSpec work across one or more Git repositories. Use the injected current controller locator to run full@4 or lite@4, pause and resume durable conversation confirmation correctly, and follow their shared multi-repository kernel.
---

# Follow Dev Flow

Treat the V4 controller as the only workflow writer and source of truth.

## Use the injected controller

Preserve the exact Hook-injected controller path and data directory as:

```text
<ctl> = <injected-controller> --data-dir <injected-data-dir>
```

Prefer the current MCP tools when available. MCP and CLI are independent
transports. Preserve the exact Hook-injected `conversation_routing`; it grants
no authority. Never read or edit controller state files directly.

## Start or resume

For an existing task, call MCP `task-next` or run:

```text
<ctl> next <task-id> --session-id <hook-injected-session-id>
```

For a new task, make workflow depth and workspace strategy explicit:

```text
<ctl> start \
  --requirement <text> \
  --workflow <full|lite> \
  --workspace-strategy <in-place|branch|worktree> \
  --repo <absolute-path> [--repo <absolute-path> ...]
```

Both `full@4` and `lite@4` accept one or multiple repositories. Repository
count never changes workflow depth. Every task uses task schema v4.

## Execute the current node

1. Read `task-next` and treat its revision, current node, primary action,
   additional actions, authority, confirmation projection and write set as
   authoritative.
2. Complete only the current node's declared payload.
3. Apply the exact action through MCP `action-apply` or:

   ```text
   <ctl> apply <task-id> \
     --expected-revision <revision> \
     --action <action-id> \
     --payload-json <json-object> \
     --session-id <hook-injected-session-id>
   ```

   Preserve the Hook-injected conversation-session routing required by the
   current transport; `--request-turn-id` is optional routing when the current
   turn ID is available. Never invent routing or pass an approval boolean,
   request or authority ID, actor assertion, raw prompt, or serialized
   confirmation as authority.
4. If the action requires `task-revision+<grant>` and no matching confirmation
   is ready, the first exact call only creates or reloads a durable request. It
   performs no guarded state mutation, Git operation, or external effect.
   Explain the exact operation and display its request ID. Ask for one exact
   reply form from the projection: bare `同意` or `approve` only when the
   request is unambiguous, otherwise `同意 <request-id>` or
   `approve <request-id>`. Then end the current turn.
5. Never poll pending confirmation, repeat `apply` in the same turn,
   auto-confirm, turn model output into a reply, or invoke a Hook manually. A
   later real `UserPromptSubmit` event only records the decision; it does not
   apply the action. Treat its session and turn fields as conversation
   evidence, not operating-system or authenticated-human identity.
6. On a later turn, reload `task-next` before doing anything else:

   - if the exact request is `CONFIRMED`, repeat only the same action, revision,
     payload and scope;
   - if an attempted decision was ambiguous or named no eligible request,
     explain the bounded next reply and end the turn again;
   - if it remains `PENDING` because the user's prompt was unrelated, leave it
     pending and follow the new instruction without claiming confirmation;
   - if it is `DENIED`, explain that denial is terminal for that binding and
     stop without retrying or reopening it;
   - if the revision, action, payload or scope drifted, use only the new
     controller-projected binding.

   Exact `拒绝`, `deny`, or their request-ID forms deny under the same
   ambiguity rules. Unrelated prompts do not decide a request.
7. Reload `task-next` after every successful mutation, lost response or
   revision conflict.
8. For multi-repository work, record only the dependency DAG, concurrency and
   retry limit; the controller derives the active owner. Then follow the shared
   lease/result/barrier/integration nodes. Submit a result only for the active
   lease and only while repository HEAD still matches its pinned HEAD. The
   controller owns ownership, ordering, retry, cancellation and CAS.
9. Record only real implementation, test and review evidence.

Use `$analyze-change-impact` at the full workflow impact node and
`$review-dev-flow-change` at the full workflow review node.

`lite@4` has no workflow-entry approval. After preflight, single-repository
Lite enters implementation and multi-repository Lite enters the shared
repository-plan node. Any later shared node that declares additional authority
still uses the durable confirmation flow above.

## Recover safely

Use MCP `effect-inspect` before MCP `effect-recover`, or run
`<ctl> effect-inspect`. Let the controller validate the execution, journal and
selected recovery mode before asking for confirmation. If reattach or
compensate is unavailable, return the bounded operator-intervention result and
stop; do not ask the user to approve an operation the controller cannot
perform. An actionable recovery request follows the same durable
request/end-turn/reload/exact-retry lifecycle as an action. Conversation
agreement is never effect-absence, settlement, receipt, reattachment or
compensation proof. The controller binds the prechecked evidence digest, then
reloads and proves it again under the execution fence on the exact retry. If it
returns `EFFECT_SETTLEMENT_UNPROVEN`, `EFFECT_ABSENCE_UNPROVEN`, or
`EFFECT_RECOVERY_EVIDENCE_CHANGED`, report the bounded operator intervention,
stop, and do not reuse the stale request as authority.

Never fabricate settlement, compensation, confirmation, receipt or recovery
proof.

Do not stash, reset, clean, force-push, rebase, merge, commit, push, archive an
OpenSpec change, delete a worktree, or cancel a task without explicit authority
for that exact action.
