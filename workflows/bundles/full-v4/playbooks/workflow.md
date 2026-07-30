# Full workflow node playbook

## intake
Run the complete all-repository preflight preview. Present the exact decision
and apply only its confirmed token. Preserve all repository dirt.

## preflighted
Present the baseline/fetch/materialization scope, record the matching
`baseline-fetch` approval, then run the deterministic baseline action.

## baselined
Create or refresh each baseline index. A failed index requires the separate
`impact-degraded` gate. The final current index advances to `INDEXED`.

## indexed
Produce and record the bounded, source-backed impact artifact. Select the
`direct` or `openspec` route only after presenting material unknowns.

## impact-review
Bind route approval to the current impact artifact. This does not authorize a
workspace or any later transition.

## route-approved
Create the deterministic workspace plan, show every repository path and
branch, bind the `workspace` approval, then execute that exact plan.

## workspace-ready
Record current workspace indexes for every repository. Use only the exact
automatic `WORKSPACE_READY -> PLANNING` edge.

## planning
Load current source context through the workspace indexes. Record the direct
contract or apply-ready OpenSpec directory, bind plan approval, refresh indexes,
then explicitly confirm entry into implementation.

## implementing
Edit only approved controller-owned worktrees and paths. Replan or reassess
through the declared rework edges. Refresh indexes before the exact automatic
verification edge.

## verifying
Run the approved checks and record each real result. Refresh workspace indexes,
then use `review-snapshot`; its exact edge to review is automatic.

## reviewing
Review the complete current snapshot independently. Record the structured
report and bind review approval. Rework through the declared edge when needed.

## finalizing
Present current scope, evidence, tests, review, worktrees, risks, and handoff.
`DONE` remains irreversible and requires one fresh explicit intent.

## blocked
Preserve the recorded origin and evidence. Resume only through the matching
declared recovery edge; a preflight blocker resumes through preflight itself.
Cancellation remains explicit.

## done
Read-only handoff only. Commit, push, merge, archive, cleanup, and worktree
removal remain separate explicitly authorized operations.

## cancelled
Read-only history only. Never reopen or reinterpret the cancelled task.
