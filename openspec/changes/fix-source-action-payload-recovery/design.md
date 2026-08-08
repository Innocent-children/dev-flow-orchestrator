## Context

`plan.record` and other `produces-source` actions receive a binding whose
`starting_snapshot_digest` names the accepted source predecessor. The executor uses
that authority to change files and then submits the original binding. The Controller
derives the task-change manifest from that predecessor and the fresh snapshot and
requires exact ownership claims.

The generic MCP `stale_recovery` text currently treats any repository evidence
change as a reason to refresh. A refresh after source production cannot prove that
the observed drift is task-owned, so `agent_projection` correctly returns a blocked
action with a null binding. This creates an avoidable dead end after a payload-shape
error even though the original binding remains valid and no task mutation committed.

## Goals / Non-Goals

**Goals:**

- Make the projected payload contract sufficient to construct valid resource
  bindings without reading package source.
- Preserve and explain the existing atomic correction path after
  `NODE_OUTPUT_INVALID`.
- Keep workspace ownership and freshness protections fail-closed.

**Non-Goals:**

- Reissue a source-producing binding after the caller has lost it.
- Automatically classify existing workspace drift as task-owned.
- Change persisted task state, binding identity, ownership-claim validation, or
  repository snapshot semantics.

## Decisions

### 1. Specialize stale recovery by workspace role

The `produces-source` guidance overrides the generic stale-recovery rule. Expected
task-owned file changes do not by themselves invalidate the issued binding. After a
pre-commit payload validation error, the caller corrects the payload and resubmits
the exact issued binding if task revision, action, contract, inputs, and repository
membership remain unchanged. A changed task authority still requires a fresh action.

This keeps the Controller security model intact: only the previously issued binding
is usable, and current ownership claims must still cover every and only task-owned
change.

### 2. Publish the exact resource envelope

For an action whose declared payload contains `resources`, bounded guidance states
the canonical shape:

```json
{"resources":{"items":[{"repository_id":"<projected-id>","path":"relative/path","role":"governing|reported","normalizer":"none|openspec-tasks/0.4.0"}]}}
```

Validation errors include the expected container or item fields so callers can
correct the request without inspecting implementation source.

### 3. Return correct-request recovery for invalid action output

MCP result mapping classifies `NODE_OUTPUT_INVALID` as `correct-request`, names
`dev_flow_apply_action`, and keeps `blind_retry` false. The request must be corrected;
the same malformed request is never retried automatically. The mapping does not
claim a mutation committed.

## Risks / Trade-offs

- Longer guidance consumes part of the bounded action budget. Focused size tests
  retain the existing limit.
- A caller can still lose the original binding after refreshing. The safe recovery
  remains restore, authorized contract revision, or cancellation; the Controller
  does not infer ownership or mint replacement authority over unknown drift.
