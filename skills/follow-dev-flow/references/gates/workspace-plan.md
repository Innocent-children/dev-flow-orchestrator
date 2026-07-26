# Workspace and planning gates

Read this bundle for a full task in `ROUTE_APPROVED`, `WORKSPACE_READY`, or
`PLANNING`. Read [../index-routing.md](../index-routing.md) for workspace-index
selection and [../openspec-route.md](../openspec-route.md) only after choosing
OpenSpec.

## Workspace plan and execution

Both routes require a task branch and independent task-owned linked worktree
for every repository. Record a deterministic all-repository plan:

```text
<ctl> prepare-workspace --task <task-id> --expected-revision <revision> [--branch <branch>] [--path <single-repo-path>] [--workspace-path <repo>=<absolute-path> ...] [--workspace-branch <repo>=<branch> ...] --dry-run
```

Dry-run changes no Git but records `workspace-plan`, clears older workspace
approval, and usually increments revision. An identical intact plan in the
same generation returns `unchanged`. Paths/branches cannot overlap source
checkouts, registered worktrees, analysis worktrees, controller namespaces,
other tasks/generations, protected branches, or one another.

Show every repository, path, branch, base SHA, generation, and plan hash.
After explicit approval:

```text
<ctl> approve --task <task-id> --expected-revision <revision> --gate workspace --note <note> --artifact-sha256 <workspace-plan-sha256>
<ctl> prepare-workspace --task <task-id> --expected-revision <revision> [the exact approved options] --execute
```

Execution must match the approved plan byte-for-byte in meaning;
`WORKSPACE_PLAN_MISMATCH` requires a new plan and approval. Successful
all-repository `prepare-workspace --execute` enters `WORKSPACE_READY`. On lost
response, inspect compact/sectioned state; never create a duplicate. A partial
worktree may be adopted only when path, branch, base `HEAD`, common Git
directory, clean state, and approved plan all match.

Index every returned workspace path with the current generation's recommended
name and `persistence:false`, then record:

```text
<ctl> record-index --task <task-id> --expected-revision <revision> --role workspace --repo <id> --index-id <project-id> --metadata-json <json>
```

Workspace records bind plan, path, branch, `HEAD`, generation, and complete
fingerprint. Every repository needs a current successful workspace index
before `PLANNING`; never substitute its baseline project.

## Planning gate

Call the exact whitelisted automatic transition
`WORKSPACE_READY -> PLANNING` without a separate state-edge prompt:

```text
<ctl> transition --task <task-id> --expected-revision <revision> --to PLANNING
```

For `direct`, create the linked direct-contract template with goal, observable
acceptance criteria, per-repository scope/non-goals, intended components,
tests, risks, compatibility/migration/security/rollout/rollback concerns, and
multi-repository order. Save under `<evidence-root>` and record:

```text
<ctl> record-artifact --task <task-id> --expected-revision <revision> --kind direct-contract --path <contract>
```

For `openspec`, follow generated status/instructions and the OpenSpec reference;
do not assume artifact names. When apply-ready, record the complete returned
change directory as `openspec-plan`.

Present the complete plan and obtain explicit approval:

```text
<ctl> approve --task <task-id> --expected-revision <revision> --gate plan --note <note> --artifact-sha256 <plan-sha256>
```

Refresh and record all workspace indexes after planning bytes change. Then
preview `PLANNING -> IMPLEMENTING`, show the returned intent and remaining
workflow, and apply `--confirm-intent <intent-id>` only after explicit
confirmation.

If implementation or review changes the approved plan, use the replanning path
in [../flow-full.md](../flow-full.md). Revise only after returning to
`PLANNING`; record/approve a new-generation artifact and repeat tests, snapshot,
and review. Replanning cannot rewrite impact or silently change route.
