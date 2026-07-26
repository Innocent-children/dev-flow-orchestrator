# Preflight gate

This gate is shared by lite and full tasks. It is the only supported path from
`INTAKE` (or a preflight-origin `BLOCKED`) to `PREFLIGHTED`.

## Two-phase protocol

Run preview first:

```text
<ctl> preflight --task <task-id> --expected-revision <revision> [--repo <id> ...] [--remote <name>] [--base <branch>] --preview
```

Preview commits no task state and performs only lightweight identity,
decision, blocker, and worktree-summary observation. It returns exactly one
`transition_preview` and token. When `changes_status` is true, show its exact
Chinese source/target and remaining workflow and obtain confirmation for that
edge.

`preflight --confirm-preview` is the status-changing half of the pair when the
preview reports an edge; preview itself never changes status.

Apply the identical selection and overrides:

```text
<ctl> preflight --task <task-id> --expected-revision <revision> [--repo <id> ...] [--remote <name>] [--base <branch>] --confirm-preview <token>
```

Confirm performs the complete, double-observed repository fingerprint and
records evidence. A selected-repository pair may record evidence but cannot
change status. Finish with a fresh pair without `--repo`; any preflight status
transition and any refresh of a `PREFLIGHTED` task must cover every configured
repository.

If the status decision changes, confirm returns
`PREFLIGHT_PREVIEW_STALE`. Discard the token, rerun preview, and obtain a new
edge confirmation when needed.

If only the lightweight observation changes while the decision remains valid,
confirm returns `PREFLIGHT_EVIDENCE_REFRESH_REQUIRED` with current evidence and
a reusable token. Present that evidence and obtain explicit acceptance, then
retry the same selection, overrides, revision, and token with
`--accept-evidence-refresh`. This accepts refreshed evidence only; it does not
authorize another decision or edge.

## Evidence and blockers

Inspect and report:

- canonical root, configured remotes/URLs, current branch and `HEAD`;
- resolved base/default branch and candidate SHA;
- staged, unstaged, untracked, conflict, merge, rebase, and cherry-pick state;
- repository instructions that govern the work;
- full tracked-byte manifest, untracked bytes, Git identity, capability
  profile, hidden index flags, filters, and submodule state from confirmed
  evidence.

Conflicts, detached `HEAD`, unresolved remote/base, active Git operations,
`assume-unchanged`/`skip-worktree` paths, sparse-checkout gaps, dirty
initialized submodules, and tracked clean/process filters such as Git LFS fail
closed. Do not clear flags, expand sparse checkout, remove filters, stash,
reset, clean, or absorb dirty work automatically.

Ordinary dirt is preserved. Ask the user to resolve it, or carry the exact
snapshot to the applicable structured `--allow-dirty` approval. Hidden index
flags and filters are never covered by that flag.

Network status is informative only. Preflight does not fetch, and “current”
remote evidence is not proof that a later network fetch is authorized.
