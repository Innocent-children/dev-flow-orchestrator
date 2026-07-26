# Implementation, verification, and review gates

Read this bundle for a full task in `IMPLEMENTING`, `VERIFYING`, `REVIEWING`, or
`FINALIZING`.

## Implementation and verification

Work only in recorded current-generation worktrees and within the approved
plan. Requirement or repository-set changes require explicit cancel/replace;
impact or plan corrections for the same immutable requirement use the backward
paths in [../flow-full.md](../flow-full.md).

After implementation, refresh and record every workspace index, then confirm
`IMPLEMENTING -> VERIFYING`. Run approved checks yourself and record exactly
what ran:

```text
<ctl> record-test --task <task-id> --expected-revision <revision> [--repo <id> ...] --name <name> --command <executed-command> --exit-code <code> [--output <file>]
```

`record-test` is a recorder, not an executor. Its compact receipt contains the
new revision, outcome, bindings, and fingerprint hashes; it deliberately omits
the full fingerprint payload. The state points to one task-local immutable
blob per unique fingerprint, so repeated tests reuse it. Keep optional output
files under `<evidence-root>` and immutable.

Under the current plan approval, group records by repository and stable test
identity (name plus exact command). Every group's latest result must pass,
bind the current plan SHA and unique approval ID, and match the live
fingerprint; every repository needs coverage. A different passing test cannot
hide a current failure. A legitimate command change requires replanning rather
than renaming a failure away.

Tests/formatters may change bytes. Refresh every workspace index again after
all checks and before snapshot generation.

## Independent review

With every repository currently passing, confirm and run:

```text
<ctl> review-snapshot --task <task-id> --expected-revision <revision>
```

It captures committed `base...HEAD`, cached, unstaged, and untracked evidence
for every repository and enters `REVIEWING`. The response is a compact receipt
with snapshot/manifest identity, not the full manifest. Pass its manifest and
raw governing evidence to `$review-dev-flow-change` in a fresh reviewer
context. Use `show --section review-snapshots` only if the recorded snapshot
object is needed; do not issue an unconditional full `show`.

The reviewer must validate each external fingerprint reference and inspect the
complete snapshot, current plan, impact report, tests, source, and explicit
workspace project IDs. Save a report whose first non-empty line is exactly one
of `Verdict: PASS`, `Verdict: CONDITIONAL`, or `Verdict: FAIL`, then record:

```text
<ctl> record-artifact --task <task-id> --expected-revision <revision> --kind review-report --path <report> --verdict <PASS|CONDITIONAL|FAIL>
```

- `FAIL`: report findings and confirm rework to `IMPLEMENTING`.
- `CONDITIONAL`: satisfy and re-review, or obtain explicit acceptance where
  policy permits; approve with `--accept-conditional`.
- `PASS`: obtain explicit acceptance, then approve without that flag.

```text
<ctl> approve --task <task-id> --expected-revision <revision> --gate review --note <note> --artifact-sha256 <report-sha256> [--accept-conditional]
<ctl> transition --task <task-id> --expected-revision <revision> --to FINALIZING
```

Snapshot, report, verdict, and approval are one immutable set. The controller
rehashes manifest, patches, untracked evidence, external fingerprint blobs,
and report before final states. Any changed/missing evidence or newer snapshot
invalidates the set.

## Finalization

At `FINALIZING`, present scope, artifacts, repositories/worktrees, tests,
review verdict, residual risks, and requested handoff. `DONE` is irreversible
and must never be automatic. Ask for the single `FINALIZING -> DONE` edge only
when required evidence is current and user-required handoff is complete.
Commit, push, PR creation, merge, OpenSpec archive, and worktree removal remain
separate explicitly authorized actions.
