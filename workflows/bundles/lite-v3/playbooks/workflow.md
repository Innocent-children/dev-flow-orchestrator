# Lite workflow node playbook

## intake
Run the single-repository preflight preview and apply only its exact confirmed
token. Preserve all checkout dirt and record complete current evidence.

## preflighted
Present the immutable requirement, target paths, branch, `HEAD`, dirt, and live
risk result. Bind the `lite` approval, including explicit dirty acceptance when
needed, then explicitly confirm entry into implementation.

## implementing
Edit only declared low-risk paths in the approved checkout. Reopen preflight
with a reason when scope or checkout evidence changes. The exact
`IMPLEMENTING -> VERIFYING` edge is automatic only after the live risk guard.
Unsafe scope persists `BLOCKED` and requires a replacement full-flow task.

## verifying
Run real checks and record each exact command and result. Current passing
coverage must bind the live approval and fingerprint. Rework implementation or
reopen preflight through the declared edges. `DONE` is irreversible and always
requires a fresh explicit intent after live-risk and current-test checks.

## blocked
Preserve the recorded origin. A preflight blocker resumes through preflight;
a manual blocker resumes only to its exact origin. A `lite-risk` blocker never
resumes and can only be explicitly cancelled before starting a full task.

## done
Read-only handoff only. Commit, push, PR, merge, and cleanup remain separate
explicitly authorized actions.

## cancelled
Read-only history only. Never reopen or convert the cancelled task.
