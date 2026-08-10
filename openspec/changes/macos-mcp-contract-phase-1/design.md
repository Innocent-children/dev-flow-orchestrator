## Context

Workflow node declarations remain part of workflow identity and cannot be edited to
add transport/domain fields without invalidating existing tasks. The repair must
therefore derive an effective contract above immutable node declarations. Existing
`0.4.x` records may contain action payloads written before these derived fields were
strictly required and must remain replayable without rewriting persisted bytes.

Task creation also supports an omitted `task_id`. The Controller generates the ID,
but application and server exception guards currently retain only the original
arguments. Response validation happens after the Controller may have committed.

## Goals / Non-Goals

**Goals:**

- Make every payload field accepted on a live current action visible and required
  through one closed JSON Schema.
- Preserve existing impact assurance policy and exact ownership validation.
- Preserve the generated task ID through application and server uncertain-result
  paths, with `blind_retry=false` and an executable read-after-write directive.
- Load and replay existing `0.4.x` task records without migration or rewrite.

**Non-Goals:**

- Change any official workflow node, workflow identity, model, namespace, release,
  or persisted schema.
- Change Web lifecycle, POSIX or Windows locking, Store state read limits, or any
  Windows implementation.

## Decisions

### 1. Effective payload is a derived immutable-node view

`effective_payload_contract` starts with a node's declared payload types and adds
the domain-required `impact_manifest` for `impact-report` artifacts and
`ownership_claims` for non-preflight `produces-source` actions. It returns the
accepted field types, required field set, and closed JSON Schema. Controller live
validation and MCP projection use this same value. Guidance validates and describes
the projected schema rather than naming any hidden field.

Nested schemas use the existing domain constants, enum values, bounds, repository
IDs, and criterion IDs. Domain normalization and exact changed-path ownership checks
remain authoritative after JSON Schema validation; the transport schema does not
invent a wider or narrower policy.

### 2. Legacy compatibility is explicit and replay-only

Strict public/live action application requires every effective field. Historical
record replay accepts the derived fields but requires only the original immutable
node declaration, preserving old records whose hidden field was omitted. Existing
conservative defaults remain reachable only through this replay compatibility flag.
Loading or replaying a task does not write it or alter its bytes.

The same internal flag is propagated through record and artifact reconstruction to
impact normalization. Live normalization enforces the current confidence enum.
Replay normalization alone restores the baseline `0.4.x` rule: only
`source-confirmed` can retain confirmed confidence and every other persisted value
is conservatively derived as `unknown`. The original payload and sealed artifact
remain untouched. All non-confidence structure, identity, exact-field, and bound
checks execute identically in live and replay modes. No Controller, CLI, MCP
argument, or payload field can enable the replay flag.

### 3. One mutation execution context spans both MCP guards

A request-scoped context records the input task ID, then captures `data.task_id`
immediately after Controller dispatch returns. Direct application calls create and
reset their own context. The server creates the outer scope so that it survives
application return and remains available to the final structured-output guard.
All completion-uncertain branches read from this context.

The context is in-memory and response-only. It is not persisted, is not a workflow
authority, and does not make blind replay safe.

## Risks / Trade-offs

- The complete nested schemas make current-action results larger; existing MCP
  result byte limits remain the fail-closed bound.
- Replay compatibility intentionally differs from strict live validation. The flag
  is private to record replay so a normal MCP or Controller caller cannot silently
  omit required impact or ownership input.
