# Independent review procedure

## Contents

- [Preserve independence](#preserve-independence)
- [Capture each repository snapshot](#capture-each-repository-snapshot)
- [Load the governing artifacts](#load-the-governing-artifacts)
- [Build a coverage matrix](#build-a-coverage-matrix)
- [Classify findings and verdict](#classify-findings-and-verdict)
- [Report format](#report-format)

## Preserve independence

- Treat the requirement, approved contract or OpenSpec artifacts, impact report, implementation snapshot, and test output as separate evidence sources.
- Reconcile disagreements explicitly. Prefer current source and reproducible behavior over summaries; prefer the approved requirement over implementation convenience.
- Stay read-only. Do not fix findings during the review, update planning artifacts, stage files, commit, or change task checkboxes.
- Run a test only when it is safe and expected not to modify the reviewed worktree. Otherwise use existing evidence or run in a disposable copy outside the reviewed worktree when separately authorized. Recheck repository status after any command and report test-created pollution.

## Capture each repository snapshot

Start from the workflow's recorded implementation worktree and exact base commit. Confirm that the base object exists and report the current branch, `HEAD`, index state, and worktree state. Do not substitute the merge base, default branch, or an assumed `main`/`master` commit.

When `review-snapshot` produced a manifest, verify its hash, read all referenced committed/cached/unstaged patches, inspect the untracked manifest and archive without extracting into the reviewed repository, and compare their fingerprints with the live worktree. The controller records the committed patch as `base...HEAD`; also inspect the exact `base..HEAD` commit/diff boundary below. Explain any difference caused by ancestry or merges instead of silently dropping it.

Let `<evidence-git>` mean `git -c core.fileMode=true -c core.symlinks=true -c core.trustctime=true -c core.checkStat=default -c core.fsmonitor=false -c core.ignoreStat=false -c core.untrackedCache=false -c core.ignoreCase=false -c core.quotePath=true`. Use equivalent read-only evidence commands to capture these distinct layers:

```text
<evidence-git> status --porcelain=v2 --branch --untracked-files=all
<evidence-git> diff --no-ext-diff --no-textconv --ignore-submodules=none --no-color --find-renames --summary <base>..HEAD
<evidence-git> diff --no-ext-diff --no-textconv --ignore-submodules=none --no-color --find-renames --stat <base>..HEAD
<evidence-git> diff --no-ext-diff --no-textconv --ignore-submodules=none --no-color --find-renames <base>..HEAD
<evidence-git> diff --no-ext-diff --no-textconv --ignore-submodules=none --no-color --cached --find-renames --summary
<evidence-git> diff --no-ext-diff --no-textconv --ignore-submodules=none --no-color --cached --find-renames
<evidence-git> diff --no-ext-diff --no-textconv --ignore-submodules=none --no-color --find-renames --summary
<evidence-git> diff --no-ext-diff --no-textconv --ignore-submodules=none --no-color --find-renames
<evidence-git> ls-files --others --exclude-standard
```

Run with `GIT_NO_REPLACE_OBJECTS=1`, point `GIT_GRAFT_FILE` at the platform null device, and unset Git environment redirects for repository/worktree/index/object/config/shallow/namespace discovery plus `GIT_EXTERNAL_DIFF` and `GIT_DIFF_OPTS` when the execution surface permits environment control. The explicit configuration/flags are mandatory even then; they override repository/global stat-cache, case/path quoting, file-mode/symlink, diff-driver, text-conversion, color, and submodule-ignore settings that could otherwise hide or transform evidence. These commands are supplementary spot checks and never replace the controller's canonical sanitized snapshot.

Open every untracked regular text file. For binary, very large, symlink, or special files, record the path, kind, size, and why content inspection was limited. Inspect submodule pointer and nested status when a submodule changes. Account for deleted files, executable-bit changes, symlink targets, rename pairs, and files present in more than one layer.

Fail closed when an initialized submodule worktree itself has staged, unstaged, or untracked content. A parent repository exposes only a gitlink plus a generic dirty marker, so different nested bytes can otherwise produce identical parent evidence. Require the submodule to be included as a configured repository and brought to a clean commit/pointer state through separately authorized actions; do not issue `PASS` from the parent snapshot alone.

Also fail closed when any tracked path carries Git's `assume-unchanged` or `skip-worktree` index flag, checking recursively inside every initialized nested submodule as well as the top-level repository. Those flags—including sparse-checkout entries—can suppress real worktree bytes from both the nested repository and its parent status/diff evidence. Require the user to restore a complete, normally tracked view through a separately authorized action and regenerate all fingerprints/tests/snapshots; never clear the flags during review.

Fail closed as well when a tracked path selects a Git clean/process content filter, including Git LFS, at any initialized submodule depth. v0.1 cannot prove the relationship between worktree bytes, filtered index bytes, and review patches without filter-specific evidence. Do not remove filter attributes or rewrite LFS files during review; route the repository through a separately governed compatible flow.

Build a per-repository manifest:

| Layer | Base/target | Files inspected | Limitations |
|---|---|---|---|
| Committed | `<base>..HEAD` | `<paths>` | `<none or reason>` |
| Cached | `HEAD -> index` | `<paths>` | `<none or reason>` |
| Unstaged | `index -> worktree` | `<paths>` | `<none or reason>` |
| Untracked | Git-visible, not ignored | `<paths>` | `<binary/size/etc.>` |

If the recorded base is absent, fail closed: report that complete committed coverage cannot be established and request the correct baseline.

## Load the governing artifacts

For a direct route, require the approved contract to contain:

- goal and observable acceptance criteria;
- in-scope repositories/files or components;
- explicit non-goals;
- intended tests and quality checks;
- known risks, compatibility constraints, and rollout assumptions.

For an OpenSpec route:

1. Locate the repository's generated `.codex/skills/openspec-*` skills and read the descriptions/body relevant to status, apply context, and verification.
2. Run `openspec status --change "<change>" --json` from the resolved OpenSpec root, adding a store argument when the current project guidance requires one.
3. Parse the returned schema, planning roots, artifact identifiers, statuses, concrete paths, and action context. Do not assume proposal/design/spec/tasks names.
4. Run `openspec instructions apply --change "<change>" --json` when `apply` is supported and read every concrete path in `contextFiles`. For another schema/action, request the action and artifact instructions indicated by status rather than forcing `apply`.
5. Run artifact-specific `openspec instructions <artifact-id> --change "<change>" --json` when its rules are material to review.
6. Optionally invoke the current generated OpenSpec verification skill or equivalent read-only verification. Preserve its output as one evidence source only.

Missing or incomplete artifacts may be a finding, but artifact completion alone does not prove implementation correctness.

## Build a coverage matrix

Map each requirement, scenario, acceptance criterion, and approved non-goal:

| Contract item | Implementation evidence | Test evidence | Status | Notes |
|---|---|---|---|---|
| `<item>` | `<repo:path symbol>` | `<test or command>` | covered/partial/missing/conflict | `<reason>` |

Then review these dimensions.

### Scope

- Identify required components with no implementation evidence.
- Identify changed files or behavior with no trace to an approved item.
- Distinguish necessary supporting changes from opportunistic refactors.
- Check generated, lock, vendored, fixture, snapshot, and documentation changes for intent and reproducibility.

### Behavior and tests

- Follow changed branches through validation, state changes, external calls, and error handling.
- Check null/empty/boundary inputs, retry and duplicate delivery, concurrency, partial failure, resource cleanup, and degraded dependencies when relevant.
- Confirm tests assert observable outcomes rather than merely execute lines.
- Match test level to risk: unit, integration, contract, migration, end-to-end, security, or performance.
- Under the current plan approval, group test records by repository and stable identity (name plus exact command). Confirm every group's latest record names the approved plan SHA-256 and unique `approval_id`, was recorded after the approval, passed, and still matches the reviewed worktree fingerprint; require at least one current passing group per repository. When a record names captured output, independently confirm that the file still exists and matches its recorded size and SHA-256. An unrelated passing name or command must not mask a failed suite. Do not accept time ordering as a substitute for the approval ID.
- Separate tests run by the implementer, tests reproduced by the reviewer, tests not run, and failures. A task checkbox is not test evidence.

### Compatibility, migration, and security

- Compare both sides of APIs, serialized data, events, schemas, configuration, feature flags, and version negotiation.
- Check expand/migrate/contract ordering, backfill behavior, restartability, idempotency, rollback, and mixed-version operation.
- Check trust boundaries, authentication, authorization, tenant isolation, secret exposure, injection, path handling, deserialization, logging, and denial-of-service risks where applicable.

### Multiple repositories

- Verify shared contract names, versions, field optionality/defaults, error semantics, timeouts, retries, and idempotency on every producer and consumer.
- State the implementation, merge, deployment, migration, and rollback order.
- Flag any lockstep dependency, unsafe intermediate state, or repository omitted from the approved impact report.

## Classify findings and verdict

Classify findings as:

- `blocking`: unmet requirement, incorrect behavior, failing required test, data-loss or security risk, unsafe migration, incompatible contract, missing mandatory repository change, or an incomplete snapshot that prevents a safe decision;
- `conditional`: no demonstrated defect, but a named external verification, environment check, owner approval, rollout safeguard, or bounded uncertainty must be satisfied before handoff;
- `advisory`: maintainability or polish improvement that does not threaten the approved behavior or delivery safety.

Choose the overall verdict:

- `FAIL` when any blocking finding exists. Do not soften a concrete defect into a condition.
- `CONDITIONAL` when no blocking finding exists and one or more explicit, independently checkable conditions remain. Name the owner/evidence needed where known.
- `PASS` only when no blocking or conditional finding remains, required evidence is present, and the reviewed snapshot matches the approved scope. Advisory notes may remain.

An OpenSpec validation or verification success cannot force `PASS`; a failure from it is evidence to investigate and classify independently.

## Report format

Use this order:

1. `Verdict: PASS|CONDITIONAL|FAIL` as the first non-empty line; use exactly one verdict line in the report
2. Reviewed snapshot ID, manifest path, and SHA-256
3. Findings, ordered `blocking`, `conditional`, then `advisory`
4. Requirement and non-goal coverage matrix
5. Per-repository snapshot manifest
6. Tests: claimed, reproduced, failed, skipped, and missing
7. Compatibility, migration, security, and cross-repository sequence
8. Residual unknowns and evidence limitations
9. Required fixes or conditions for re-review

For each finding include:

- concise title and severity;
- repository-relative path and symbol or tight line reference;
- violated contract item or risk category;
- direct evidence and consequence;
- smallest sufficient resolution and the evidence needed to close it.

Say `No actionable findings` when appropriate; never omit snapshot or evidence limitations merely because the verdict is `PASS`.
