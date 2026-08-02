## Context

The V5 candidate has six confirmed defects across package delivery, action replay, and task discovery. The implementation must stay within the existing V5 schema and standard-library runtime and must not turn adjacent hardening ideas into new product scope.

## Goals / Non-Goals

**Goals:**

- Validate copied candidates using their own code and assets.
- Keep public guidance and recorded verification evidence truthful.
- Preserve declared object payloads across state reload.
- Isolate invalid task entries during inventory scans.
- Reject repository/data-directory containment in both directions at task start.

**Non-Goals:**

- Cryptographic state signing or a stronger Hook authority model.
- State migration, automatic repair, quarantine, or a new recovery protocol.
- Filesystem permission redesign, atomic-commit redesign, or parser/Unicode hardening.
- New inventory response fields or changes to direct task-operation errors.

## Decisions

### Validate foreign candidates in an isolated process

`validate(root)` will validate the current checkout in process and will invoke a different candidate's own validator through an argv-based isolated Python subprocess. This prevents the caller's imported workflow and product modules from becoming the candidate's source of truth. Loading a second package with the same module names into the current interpreter was rejected because it makes module provenance dependent on `sys.modules` state.

### Treat object payloads as mappings

Payload validation will accept `collections.abc.Mapping` for fields declared as `object`. The existing canonical JSON conversion already converts frozen mappings back to plain JSON values, so no data-model or serialization change is needed.

### Isolate only task-local discovery failures

Inventory scanning will catch `DevFlowError` around each individual `load_with_definition` call and omit that invalid entry while continuing. Failures to access or validate the inventory root still fail the operation. Direct `show`, `apply`, `cancel`, and load behavior remains unchanged. No quarantine directory or diagnostic protocol is introduced.

### Extend the existing start-time overlap check

Controller start will reject equality and parent/child containment in both directions using the already canonicalized paths. No resume-time migration or relocation behavior is added.

### Validate the public metadata that users invoke

Package validation will inspect the main skill's `agents/openai.yaml` in addition to `SKILL.md`, requiring the current V5 selector and `$follow-dev-flow` prompt reference. The installation procedure will execute the package validator before recording its result as evidence.

## Risks / Trade-offs

- A foreign candidate validator is executable code. Validation is limited to candidates explicitly supplied by the caller and uses an isolated interpreter invocation without a shell.
- Invalid tasks are omitted from inventory rather than surfaced through a new diagnostics schema. Direct task operations preserve the error for investigation.
- The overlap fix prevents new unusable tasks but does not relocate any existing local experimental state.

## Migration Plan

No migration is required. The task and workflow schemas remain V5. Existing valid tasks and packages remain compatible; invalid local task entries can still be inspected directly.

## Open Questions

None.
