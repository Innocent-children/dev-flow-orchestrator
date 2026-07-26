# Token optimization v2

This document is the implementation contract for the v2 work listed in
`token-optimization-plan.md`.  V2 changes the human-confirmation and risk
contracts, so new tasks use a new task-state schema while the evidence
contract remains at v2.

## Compatibility boundary

- New tasks use task schema v2.
- The controller can still read and finish schema-v1 tasks with their legacy
  confirmation behavior.
- New schema-v2 tasks fail closed when a controller does not understand the
  v2 confirmation and risk fields.
- The evidence contract stays at v2.
- A task's flow and workspace strategy remain immutable.  A lite task that is
  found to require full flow is blocked and must be cancelled/replaced; it is
  never converted in place.

## Transition confirmation

Schema-v2 tasks use a default-explicit policy with this exact automatic
whitelist:

| Flow | Action | Edge |
|---|---|---|
| full | final `record-index` | `BASELINED -> INDEXED` |
| full | `transition` | `WORKSPACE_READY -> PLANNING` |
| full | `transition` | `IMPLEMENTING -> VERIFYING` |
| full | `review-snapshot` | `VERIFYING -> REVIEWING` |
| lite | `transition` | `IMPLEMENTING -> VERIFYING` |

Every other status edge is explicit.  `DONE` and `CANCELLED` are always
explicit and cannot be added to the automatic whitelist.

An explicit `transition` or `cancel` first returns a preview.  The caller then
confirms the returned intent against the same task revision and live evidence.
The intent is a canonical SHA-256 projection of:

- task id, task revision, flow, source and target;
- action and behavior-changing parameters;
- target-specific live evidence;
- side-effect classification and confirmation mode.

Changing any input makes the old intent stale.  Confirmation intents use their
own namespace and are not interchangeable with preflight preview tokens or
mutation-quarantine journals.

When one approved action both approves a gate and advances status, the durable
outbox records separate `gate_approved` and `state_transitioned` facts.  They
have distinct event ids and share a transaction id, revision, and intent id.

## Lite/full risk policy

Risk is determined from both a declared change category and paths:

- low-risk categories: `internal`, `tests`, `docs`;
- full-only categories: `public-api`, `schema`, `auth`, `migration`,
  `infrastructure`, `cross-repo`;
- an absent or unknown category fails closed;
- more than one repository requires full flow;
- a target or changed path matching a configured protected-path glob requires
  full flow;
- an actual changed path outside the task's declared target paths requires
  full flow;
- changed Git links/submodules require full flow;
- unreadable or ambiguous Git/path evidence fails closed.

Lite creation therefore requires one repository, at least one low-risk
category, and explicit repository-relative target paths.  The task stores the
normalized declaration plus the exact risk-policy snapshot and digest.

Before a schema-v2 lite task enters `VERIFYING` or `DONE`, the controller
classifies the live diff from the preflight HEAD, including committed, staged,
unstaged and untracked paths.  A `requires_full` or `unknown` assessment is
committed as:

```json
{
  "status": "BLOCKED",
  "blocked": {
    "phase": "lite-risk",
    "required_flow": "full",
    "from_status": "IMPLEMENTING",
    "details": []
  }
}
```

The source checkout is left untouched.  The user explicitly cancels and starts
a replacement full-flow task.

Protected-path globs use normalized POSIX repository-relative paths.  Absolute
paths, drive-qualified paths, NUL bytes and `..` segments are invalid.

## Funnel impact analysis

Impact analysis starts with exact paths/symbols and expands only when a
documented trigger is present.  A report may claim `complete` only when all
required source, path, contract and test checks are complete and no unresolved
truncation or material unknown remains.  Query-budget exhaustion produces
`degraded`, never a false complete result.

The controller validates the structured
`dev-flow-impact-analysis/v1` declaration and its repository coverage.  It
cannot prove raw MCP call counts without signed tool receipts; query counts
remain auditable declarations.

## Session checkpoint deduplication

Only `UserPromptSubmit` checkpoints are deduplicated.  Marker files are keyed
by `sha256(session_id)` and contain a digest of the compact checkpoint content.
`SessionStart` always emits.  Missing session ids, corrupt markers, and marker
I/O failures all emit the checkpoint, preserving fail-open behavior.  Markers
are written best-effort only after stdout has been written and flushed.
