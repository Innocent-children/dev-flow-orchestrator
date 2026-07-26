# Lite flow

Read this file only when `show.flow` is `lite`.

## State order

```text
INTAKE -> PREFLIGHTED -> IMPLEMENTING -> VERIFYING -> DONE
```

Supported backward edges are `VERIFYING -> IMPLEMENTING` for rework and
`IMPLEMENTING/VERIFYING -> PREFLIGHTED --note <reason>` when checkout drift or
scope growth requires a new approval. The controller rejects full-only states,
commands, and gates.

Schema-v2 lite tasks start only with exactly one repository, one or more
low-risk categories (`internal`, `tests`, `docs`), and explicit
repository-relative target paths outside the configured protected globs:

```text
<ctl> start --repo <path> --workspace-strategy <in-place|branch> --change-category <internal|tests|docs> [--change-category ...] --target-path <path> [--target-path ...] --requirement <requirement>
```

Any full-only, missing, or unknown category/path fails with
`LITE_REQUIRES_FULL`; select `worktree` and start a full task instead.

## Commands

```text
<ctl> preflight --task <task-id> --expected-revision <revision> --preview
<ctl> preflight --task <task-id> --expected-revision <revision> --confirm-preview <token> [--accept-evidence-refresh]
<ctl> approve --task <task-id> --expected-revision <revision> --gate lite --note <note> [--allow-dirty]
<ctl> transition --task <task-id> --expected-revision <revision> --to IMPLEMENTING --preview
<ctl> transition --task <task-id> --expected-revision <revision> --to IMPLEMENTING --confirm-intent <intent-id>
<ctl> transition --task <task-id> --expected-revision <revision> --to VERIFYING
<ctl> record-test --task <task-id> --expected-revision <revision> [--repo <id> ...] --name <name> --command <executed-command> --exit-code <code> [--output <file>]
<ctl> transition --task <task-id> --expected-revision <revision> --to DONE --preview
<ctl> transition --task <task-id> --expected-revision <revision> --to DONE --confirm-intent <intent-id>
```

## Procedure

1. At `INTAKE`, read [gates/preflight.md](gates/preflight.md) and complete its
   all-repository preview/confirmation pair.
2. Present the requirement and every repository's exact branch, `HEAD`, and
   complete worktree evidence. Obtain explicit approval to edit those
   checkouts in place. Record `approve --gate lite`, adding `--allow-dirty`
   only when the user explicitly accepts the exact recorded dirty snapshot.
   Every later preflight clears this approval.
3. Preview `PREFLIGHTED -> IMPLEMENTING`, confirm its exact intent, and enter
   `IMPLEMENTING`. The controller rechecks the approved branch, `HEAD`, and
   preflight fingerprint. `CHECKOUT_DRIFT` or
   `PREFLIGHT_WORKTREE_CHANGED` requires fresh preflight and approval. The
   branch remains immutable for the task.
4. Call the exact automatic `IMPLEMENTING -> VERIFYING` transition without a
   separate state-edge prompt. The controller first classifies the live diff
   against the declared targets and protected policy. If it is not safe, the
   task becomes `BLOCKED` with `required_flow: full`; do not edit or convert
   its flow—preview and confirm cancellation, then start a replacement full
   task. Otherwise run each real check yourself, then record the exact name,
   command, exit code, repository coverage, and optional immutable output
   file. The compact receipt supplies the new revision and fingerprint hashes;
   use `show --section tests` only when detailed records are needed. Tests bind
   the unique current lite approval. For every repository, the latest result
   for every current test identity must pass and match the live worktree
   fingerprint before `DONE`.
5. Present a change/test/risk summary, preview the irreversible
   `VERIFYING -> DONE` intent, and apply it only after explicit confirmation.
   The controller rechecks live risk before completion. An unsafe preview is
   read-only and reports `required_flow: full`; any actual apply attempt
   persists the lite-risk `BLOCKED` state instead of `DONE`. Commit, push, and
   PR creation remain separate explicitly authorized actions.

Reopening to `PREFLIGHTED` uses the explicit preview/intent protocol, records
the now-dirty tree, requires a new lite approval (and explicit `--allow-dirty`
when applicable), and makes tests under the previous approval historical. If
the work stops being bounded and low-risk, let the controller persist the
lite-risk block, then explicitly cancel/replace it with a full task.
