# Greenfield Product Contract

## Product identity

- plugin: `dev-flow-orchestrator`
- task schema: `4`
- workflows: `full@4`, `lite@4`
- supported host for this change: current macOS only
- runtime dependency: Python standard library only
- historical data: none and out of scope

## Independent dimensions

### Workflow depth

- `full@4`: complete governed delivery workflow.
- `lite@4`: bounded delivery workflow with fewer gates.

### Repository topology

- `single-repository`: exactly one canonical Git repository.
- `multi-repository`: at least two distinct canonical Git repositories.

### Workspace strategy

- `in-place`: use the current checkout under explicit user authority.
- `branch`: use an explicitly selected current checkout branch.
- `worktree`: create or use a controller-owned worktree through a gated Git effect.

Repository count never chooses workflow depth. Workspace strategy never silently chooses
workflow depth.

## Four profiles

| Profile | Minimum suite set |
|---|---|
| `full@4` / `single-repository` | `greenfield-skeleton`, `greenfield-core-workflow`, `greenfield-effect-recovery`, `greenfield-adapters` |
| `full@4` / `multi-repository` | full single suites plus `greenfield-multi-repository` |
| `lite@4` / `single-repository` | `greenfield-skeleton`, `greenfield-core-workflow`, `greenfield-effect-recovery`, `greenfield-adapters` |
| `lite@4` / `multi-repository` | lite single suites plus `greenfield-multi-repository` |

Suite names describe current greenfield behavior. They are not predecessor compatibility
profiles.

## Creation request

A new task requires:

- non-empty requirement;
- explicit `workflow`: `full` or `lite`;
- explicit `workspace_strategy`;
- one or more `repository` paths;
- explicit `data_dir` from the launcher/config/test;
- optional task ID.

The controller derives topology only from the count of distinct canonical repositories. It
does not derive workflow depth. An unsupported workflow/workspace combination is rejected by
the one product matrix before task state is written.

## Initial task state

The first committed state contains only current product fields:

- `schema_version: 4`;
- task identity, requirement and timestamps;
- revision;
- exact workflow identity and profile;
- workspace strategy;
- canonical repository records;
- current node/status;
- approvals, evidence and effects as empty current-V4 collections;
- exact product/bundle identity.

The workflow identity covers the entry/preflight contract, the selected full/lite graph,
the shared repository graph when applicable, shared repository cancellation, every direct
handler ID and every effect port.

No schema selector, predecessor field, migration marker or compatibility response mode exists.

## Workflow difference

`full` and `lite` are two explicit graphs over shared node contracts. A node that is common to
both workflows resolves to the same implementation. Full-only gates exist in the full graph;
lite does not call them and ask them to no-op.

Repository topology adds shared map/barrier/integration nodes to either graph. It does not
rewrite one graph into the other.
