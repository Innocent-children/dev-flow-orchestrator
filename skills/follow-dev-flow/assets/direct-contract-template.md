# Direct change contract: <short requirement name>

## Traceability

- Task ID: `<task-id>`
- Requirement: <normalized requirement>
- Impact report: `<path and sha256>`
- Route reason: <why the bounded direct route is appropriate>

## Goal and acceptance

### Goal

<State the observable behavior to deliver.>

### Acceptance criteria

- [ ] <Observable successful behavior>
- [ ] <Boundary or failure behavior>

## Scope by repository

| Repository | Baseline | Implementation worktree | Components/files/symbols |
|---|---|---|---|
| `<repository-id>` | `<base-sha>` | `<path>` | <approved scope> |

### Non-goals

- <Behavior, refactor, repository, migration, or operational action explicitly excluded>

## Implementation contract

1. <Change and its reason>
2. <Required cross-repository or migration order>

### Public contracts and compatibility

- <API, event, schema, configuration, versioning, mixed-version, or compatibility rule>

### Security and data handling

- <Authentication, authorization, validation, secrets, privacy, or migration constraint>

## Verification

| Stable test name | Repository scope | Command | Expected evidence |
|---|---|---|---|
| `<unit|integration|lint|project-specific name>` | `<repository-id or all>` | `<exact command>` | <assertions or observable outcome> |

Include at least one verification command for every configured repository. Add a cross-repository aggregate command only when the project actually provides or requires one.

Run and record these commands after this contract is approved. Use a stable `--name` and exact command for each logical suite; together they form its identity. For every repository, the latest result for every test identity recorded under the current approval must pass with a matching worktree fingerprint; an unrelated passing name or command never hides a failed suite. Keep results bound to both the approved contract SHA-256 and that approval's unique `approval_id`; time is supporting evidence only.

## Risk, rollout, and rollback

- Risk: <failure mode and mitigation>
- Rollout: <ordering, flag, monitoring, or compatibility step>
- Rollback: <safe reversal or explicit limitation>

## Approval handoff

- Material unknowns: <none or named uncertainty>
- Approval note to record: <user's explicit decision>
