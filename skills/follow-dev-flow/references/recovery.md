# Resume and recovery

## Resume idempotently

1. Call `show` for the recorded task before touching a repository.
2. Read the current state, revision, repositories, baselines, indexes, artifact hashes, route, workspaces, approvals, tests, and review evidence.
3. Inspect external reality read-only: repository `HEAD` and status, branch/worktree registrations, evidence under `<state-dir>/tasks/<task-id>/artifacts/`, artifact hashes, OpenSpec JSON status, and any claimed test/review files.
4. Classify each next action as `not started`, `completed and recorded`, `completed but unrecorded`, `partially completed`, or `conflicting`.
5. Reuse completed matching work. Record recoverable unrecorded evidence through the controller only after verifying identity and content. Never repeat a side effect just because its original response was lost.
6. Use the latest returned revision for one mutation, reload, and repeat.

For every codebase-memory call, read the controller's current `index_selection` and pass the named `recorded_project` explicitly. The MCP server does not select between baseline and workspace projects for you.

## Reconcile common interruptions

### Controller succeeded, response was lost

Reload the task. If state/evidence already reflects the action, continue. If not, inspect the external artifact. Adopt it only when task ID, repository, baseline, branch/worktree, path, and content hash match the intended action; otherwise pause as a conflict.

### Worktree or branch already exists

Reload the latest current-generation `workspace-plan` and workspace approval. Verify the canonical worktree path, Git common directory, branch, baseline ancestry, generation, and task identity. Retry `prepare-workspace --execute` only with the exact options that produced the approved plan. A worktree already recorded by the task may contain expected implementation changes; a not-yet-recorded worktree is accepted only as a clean partial side effect when its path, branch, exact base `HEAD`, common directory, and approved plan all match and a porcelain status including ignored entries is empty. Paths and branches claimed by another task or retired by this task are not adoptable. Treat staged, unstaged, untracked, ignored, cross-task-owned, retired, or otherwise nonmatching collisions as user-owned; record a new dry-run plan with a new per-repository path/branch override, approve its returned hash, and execute that exact plan. Never delete, detach, reset, or repoint the collision automatically.

After a workspace is created or adopted, create and record its current-generation workspace index before continuing to `PLANNING`. Do not reuse the baseline project ID or a retired generation's project ID.

### Workspace-plan response was lost

Reload the task before using the old revision. A successful dry run already recorded a deterministic `workspace-plan` artifact and incremented the revision. If identity is uncertain, repeat the identical dry-run arguments: an intact matching plan returns `unchanged`; a new plan returns a new hash/revision and clears the older workspace approval. Approve the latest `plan_artifact.sha256`, then execute with the exact same arguments. Treat `WORKSPACE_PLAN_MISMATCH` as a request to re-plan, not permission to bypass the gate.

### Repository drifted

Pause when `HEAD`, branch, worktree, or pre-existing changes no longer match recorded evidence. Show the recorded and observed values. Ask whether to adopt a new baseline, restore the expected context through a separately approved action, or cancel. Never silently widen the snapshot.

### Baseline analysis workspace is missing

Reload the task and verify the immutable `base_sha` plus the recorded `baseline-fetch` approval. Confirm that every live remote URL still equals the value bound by the approved preflight evidence. `preflight` is not a legal backward transition from `BASELINED`: on `REMOTE_URL_CHANGED`, present the drift and ask whether to restore the exact approved URL or cancel/replace the task; never rewrite the baseline or fetch from the new endpoint inside the old task. From `BASELINED`, call `baseline --materialize` with the current revision to recreate or revalidate the detached analysis worktree. Reuse it only when its Git common directory matches the source repository, `HEAD` equals `base_sha`, no branch is attached, and its initial status is clean. Stop on a path collision; never remove or repoint the conflicting path automatically. Do not index the user's source worktree as a fallback.

### Artifact changed after approval

Let the controller re-hash the recorded path; do not alter state to match new bytes. On `ARTIFACT_CHANGED`, explain the delta and stop using the old approval.

- For a changed workspace proposal, run `prepare-workspace` again without `--execute`, approve the new `workspace-plan` hash, and execute the identical options.
- For a changed direct/OpenSpec plan after `PLANNING`, transition back with `transition --to PLANNING --note <reason>`, then record and approve the new plan. This clears plan/review approvals and review snapshots.
- For a changed review report while still in `REVIEWING`, record it again and obtain a new review approval bound to its hash and latest snapshot.
- For a changed impact report before route approval, record the corrected `impact` in `INDEXED` or `IMPACT_REVIEW` and approve the latest hash. After `ROUTE_APPROVED`, restore the exact approved content when mutation was accidental. For a legitimate reassessment, call `transition --to INDEXED --note <reason>`, then record a new impact and repeat route, workspace, plan, test, and review gates.

### Baseline or workspace index is stale or incomplete

First read `show.index_selection`; codebase-memory never chooses the correct project automatically.

- For baseline staleness, resolve freshness before calling `set-route`. While still `BASELINED` or `INDEXED`, refresh the affected detached analysis workspace under its baseline-specific project name with `persistence=false`, record the exact returned project identifier with `record-index --role baseline`, rerun dependent cross-repository intelligence, and record a new impact report in `INDEXED`. If material baseline staleness is discovered after entering `IMPACT_REVIEW`, correct the report before approval when existing index provenance remains valid; otherwise restart the task. After route approval, use `transition --to INDEXED --note <reason>` for a supported impact reassessment and repeat every downstream gate.
- For workspace staleness, index the current recorded implementation path under the current generation's workspace-specific name with `persistence=false`, then call `record-index --role workspace`. Refresh after staged, unstaged, untracked, committed, OpenSpec, generated, or test-created changes before crossing the next workspace-index gate. A missing or stale workspace project is not permission to query the baseline project.
- For multi-repository queries, refresh every member of the same role/generation first. Never combine baseline and workspace projects, or current and retired workspace generations, in one claimed-complete cross-repository result.

For an upgraded 0.1.x task that reached `REVIEWING` or `FINALIZING` before workspace indexes existed, preserve and finish the already immutable snapshot/review chain when no rework is needed. If implementation or planning must resume, use the supported impact reassessment to `INDEXED` and rebuild the downstream workspace/index evidence; do not bypass the new gate or repurpose the baseline project.

If a recorded receipt hash no longer matches, treat the record as stale and refresh it. The controller validates project provenance against path, branch, `HEAD`, plan, generation, and the complete Git fingerprint, but the MCP receipt does not expose a cryptographic digest of every graph source byte; confirm material conclusions in source.

### OpenSpec is unavailable or inconsistent

Preserve the OpenSpec route and planning evidence. Diagnose availability, project root, store, generated skills, `status --json`, and `instructions --json`. Before route approval, offer initialization/update or a deliberate route change as explicit user decisions. After route approval, fix the OpenSpec environment; if the user chooses another route, transition to `INDEXED` with a reassessment note and repeat route plus downstream gates. Never silently fall back to a hardcoded process or direct implementation.

### Implementation requires replanning

From `IMPLEMENTING`, `VERIFYING`, `REVIEWING`, or `FINALIZING`, call `transition --to PLANNING --note <reason>`. Expect the controller to clear plan/review approvals and review snapshots. Update the direct contract under the task evidence root or the OpenSpec `changeRoot` in the managed implementation workspace, record the new plan only while in `PLANNING`, bind a new plan approval, refresh every workspace index, and return through implementation and verification. Record a new passing result for every repository after the new approval because tests are tied to the current plan SHA-256 and unique approval ID; refresh the workspace indexes again after implementation/testing changes, then create and review a fresh snapshot. Keep prior evidence in history.

### Tests or review fail

Record the exact command/verdict and failure evidence. A structured `FAIL` review report cannot be approved; a `CONDITIONAL` report requires the user's explicit acceptance and `approve --gate review --accept-conditional`. Return through only controller-supported states, make the smallest approved correction, and rerun each failed logical test under the same stable name and exact command until that identity's latest current-approval result passes; an unrelated passing test does not supersede it. Regenerate the full snapshot and perform a fresh independent review. Do not erase earlier failures from history.

After any new `review-snapshot`, treat every older `review-report` and review approval as stale. Record the new report while still in `REVIEWING` with its exact `--verdict`, verify its automatic `metadata.review_snapshot_sha256` and verdict bindings, and obtain a new approval bound to the new report SHA-256.

### Lite task drifted or outgrew its approval

A lite task has no baseline or managed worktree to restore; its recoverable evidence is the preflight snapshot, the lite approval, and the test records. On `CHECKOUT_DRIFT` or `PREFLIGHT_WORKTREE_CHANGED`, show the recorded and observed branch/`HEAD`/fingerprint values and ask how to proceed; returning the checkout to the approved snapshot is the user's action, never an automatic reset. To continue with the changed reality, transition back to `PREFLIGHTED` with a note when needed, rerun `preflight`, and obtain a new `approve --gate lite` decision (`--allow-dirty` for the now-dirty tree); older test records become historical because they bind the superseded approval ID. If the change no longer fits a bounded in-place fix, stop and ask the user to cancel/replace the task as a full task — the flow is immutable.

### Revision conflict

Treat optimistic-lock failure as evidence another invocation advanced the task. Reload and reconcile. Never overwrite state or retry a mutation with a fabricated `--expected-revision`.

## Handle controller or tool failure

- Retry once only for an obviously transient read operation.
- Do not retry Git-changing or artifact-writing commands until external state is inspected.
- Preserve stdout, stderr, exit status, task ID, revision, and observed side effects.
- Do not edit controller state files to unblock progress.
- Use a controller-supported `BLOCKED` transition when available and name one concrete unblock condition.
- If state cannot be read safely, stop before further mutations and ask for direction with the diagnostic evidence.

## Cancel safely

Call `cancel` only after explicit user confirmation. Cancellation records intent; it does not authorize deleting worktrees, branches, artifacts, or uncommitted changes. Report all retained paths and explain that cleanup needs a separate explicit decision.
