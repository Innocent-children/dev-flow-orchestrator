## Why

The current V4 controller opens a 120-second macOS dialog as soon as an
authority-gated action is applied. Real users need enough time to read a plan
or recovery decision and may be away from the computer, so the timeout turns a
safety gate into an unreliable interruption instead of a durable decision
point.

## What Changes

- **BREAKING** Replace every macOS popup authority decision with a durable,
  controller-owned conversation confirmation request. The workflow stops,
  presents the exact request in chat, and resumes only after a later
  `UserPromptSubmit` event explicitly agrees to that request.
- Bind each request and confirmation to the exact task, revision, action,
  grant, validated payload context, actor role, repository or lease scope, and
  Codex session/turn evidence; consume it once and reject stale, ambiguous,
  mismatched, denied, missing, or replayed confirmation.
- Serialize cross-task request selection and session/turn decisions through
  one data-directory confirmation index, retain exact task/effect success
  evidence across commit/consume crashes, and make denial terminal for the
  exact binding.
- Allow an exact bare reply such as `同意` only when one pending request is
  unambiguous for the current session and repository context. Otherwise require
  the displayed confirmation request ID.
- Keep Hooks thin: they forward bounded `UserPromptSubmit` evidence to the
  controller but never apply a workflow transition or synthesize confirmation
  from model output.
- Remove the Lite-specific approval node. After preflight, `lite@4` enters
  implementation directly for one repository and the shared repository-plan
  node directly for multiple repositories.
- Update CLI, MCP, Skill, Hook, recovery, validation, installation, architecture
  and user documentation for the durable request/confirm/apply protocol.
- Define private-store permissions, corruption/capacity diagnostics, old-popup
  upgrade, data-preserving uninstall and complete packaged-source popup
  removal. Codex host sandbox/tool permission prompts remain outside this
  plugin's control.
- Preserve explicit confirmation for every actionable non-Lite authority
  grant. Recovery modes that can only return operator intervention are
  diagnosed before requesting confirmation. This change removes popup
  timeouts, not actionable safety gates or destructive-Git policy.

## Capabilities

### New Capabilities

- `durable-conversation-confirmation`: Durable exact-bound confirmation
  requests, later user-prompt confirmation, ambiguity handling, one-time
  consumption, failure behavior, audit evidence and recovery confirmation.

### Modified Capabilities

- `codex-runtime-adapters`: CLI, MCP, Hook and Skill expose one controller-owned
  request/confirm/apply protocol instead of invoking macOS dialogs.
- `compact-agent-protocol`: The current projection reports whether an action
  needs a confirmation request, is waiting for a user reply, or has a confirmed
  request ready for exact application.
- `pluggable-workflow-execution`: `lite@4` no longer contains or requires a
  workflow-specific approval placement between preflight and execution.
- `multi-repository-orchestration`: Lite multi-repository execution enters the
  shared repository kernel directly while retaining the kernel's own authority
  contracts.

## Impact

The change affects `workflow.py`, `engine.py`, `authority.py`,
`controller.py`, `hook.py`, the JSON CLI and MCP schemas, workflow identities,
effect recovery, focused greenfield tests, package validation, the Follow Dev
Flow skill, installation requirements, architecture documentation and
English/Chinese user guides.

It is intentionally stacked on the in-progress
`refactor-v4-runtime-architecture` greenfield V4 change and supersedes only
that change's macOS-dialog authority requirement and directly dependent
artifacts. Its implementation invalidates the current frozen candidate and
must be revalidated with only the smallest directly affected macOS test
selections. No historical authority data or compatibility migration is added
because the product has no historical data.

`runtime-architecture` does not yet exist under `openspec/specs/`, so OpenSpec
cannot validate a `MODIFIED` delta against main. The directly superseded
Requirement and multi-repository principal wording are therefore updated in
the unarchived stacked change itself and content-pinned in this change's review
manifest. The stacked change is not archived, and no unrelated requirement is
rewritten.
