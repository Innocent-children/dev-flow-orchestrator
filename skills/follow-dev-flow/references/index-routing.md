# Dual-index routing

## The selection rule

`codebase-memory-mcp` does not inspect Dev Flow state and does not choose an index automatically. Every graph or source query requires an explicit `project` argument. Use the exact project identifier returned by `index_repository` and recorded by the controller; never derive a project ID from a path or choose the most recently created project.

Dev Flow keeps two independent index roles for each repository:

| Role | Indexed path | Purpose | Stored field |
|---|---|---|---|
| `baseline` | Detached analysis worktree pinned to `base_sha` | Initial impact analysis, route decision, reassessment, and before-state evidence | `repositories[].index` |
| `workspace` | Current-generation managed implementation worktree | Planning discovery, implementation navigation, verification, and independent-review discovery | `repositories[].workspace_index` |

The baseline role always targets the immutable pinned analysis worktree. Reindexing replaces only the current record, archives the superseded record in `repositories[].index_history`, and makes dependent impact evidence stale as before. Refreshing a workspace index must not change the current baseline record, its impact binding, or the route approval.

## Phase-to-project matrix

Use `show` before graph work. Its `index_selection` object reports `automatic: false`, the `selected_role`, and the recorded/recommended project for every repository.

| Workflow phase | Required role | Query behavior |
|---|---|---|
| `BASELINED`, `INDEXED`, `IMPACT_REVIEW`, `ROUTE_APPROVED` | `baseline` | Pass each repository's recorded baseline project explicitly |
| `WORKSPACE_READY`, `PLANNING`, `IMPLEMENTING`, `VERIFYING`, `REVIEWING`, `FINALIZING`, `DONE` | `workspace` | Pass the current-generation workspace project explicitly |
| Before/after comparison | both, separately | Make one call per project, label each result by role, then compare |
| Cross-repository analysis | one coherent family | Use all-baseline projects for impact work or same-generation workspace projects for implementation work; never mix roles or generations |

For `BLOCKED`, use the role of its recorded `from_status`. `INTAKE`, `PREFLIGHTED`, and `CANCELLED` have no selectable index. `DONE` retains the workspace selection for read-only handoff/history; it does not reopen the task.

If the selected workspace project is missing or stale, refresh and record it. Do not silently query the baseline project as a substitute: it represents different bytes and can hide newly added, renamed, or deleted implementation symbols.

## Create and record projects

Always pass an explicit, role-specific `name` and `persistence=false` to `index_repository`:

```text
baseline:  devflow-<task-id>-<repository-id>-baseline
workspace: devflow-<task-id>-<repository-id>-workspace-r<workspace-generation>
```

The name is a collision-resistant recommendation, not proof of the returned identifier. Record and subsequently query the exact project ID returned by the MCP tool.

Baseline example:

```text
index_repository(
  repo_path=<analysis_workspace.path>,
  name=<recommended-baseline-name>,
  mode=<fast|moderate|full>,
  persistence=false
)
<ctl> record-index ... --role baseline --repo <id> --commit <base-sha> \
  --index-id <returned-project-id> --metadata-json <json-object>
```

Workspace example:

```text
index_repository(
  repo_path=<workspace.path>,
  name=<recommended-workspace-name>,
  mode=<fast|moderate|full>,
  persistence=false
)
<ctl> record-index ... --role workspace --repo <id> \
  --index-id <returned-project-id> --metadata-json <json-object>
```

`persistence=false` prevents codebase-memory from writing its optional portable database artifact into the indexed business worktree. Codebase-memory still owns and manages the external graph identified by the returned project ID.

Record a workspace index immediately after workspace creation and refresh it after any managed-worktree planning or source change before crossing the controller gates into `PLANNING`, `IMPLEMENTING`, or `VERIFYING`, or before `review-snapshot`. The controller binds the record to the current canonical worktree path, branch, `HEAD`, workspace generation, approved workspace-plan hash, and complete Git fingerprint. Staged, unstaged, untracked, or committed changes therefore make an older workspace record stale.

Project identifiers must be unique across repository/role pairs and retained history within a task. Every replacement archives the full prior record and old/new mapping in state/event evidence. A later refresh of the same baseline role may reuse one of that repository's project IDs; a workspace refresh may reuse its own project ID only in the same workspace generation. A baseline and workspace record, different repositories, or different workspace generations must never share one.

## Evidence limits and cleanup

For a baseline project, the controller records the detached analysis-worktree path, exact base commit, project ID, metadata, and optional receipt after verifying that the worktree is clean and pinned. For a workspace project, it additionally binds the current canonical path, `HEAD`, branch, approved workspace-plan hash, generation, and complete Git fingerprint. It verifies any supplied receipt hash for either role. The MCP response does not expose a cryptographic digest of every indexed source byte, so this is provenance enforcement rather than cryptographic proof of graph contents. Confirm material conclusions in current source and use the controller snapshot as canonical review evidence.

Dev Flow records project identifiers but does not delete codebase-memory projects automatically. Superseded baseline/workspace records remain in `index_history`, and the live workspace record retired by reassessment remains in workspace history. Remove external indexes only as a separate, explicitly authorized maintenance action after they are no longer needed.
