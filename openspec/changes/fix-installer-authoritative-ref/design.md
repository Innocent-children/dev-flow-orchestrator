## Context

The public one-line installation entry points all download `main/scripts/install.sh`, and the repository has no release tags. The installer nevertheless lets `git clone` choose the remote default branch and lets `git pull --ff-only` operate on any existing branch. URL and dirty-tree checks therefore do not prove that the package being validated and activated is the authoritative `main` commit.

The installer is POSIX `sh`, supports macOS only, and must remain non-destructive. Runtime code may use only the Python standard library. Existing marketplace registration is an atomic JSON rewrite followed by `codex plugin add`.

The existing clean-tree check uses `git status --porcelain`, which intentionally omits ignored files. Git merge updates ignored files by default, so an otherwise eligible fast-forward can silently replace a local ignored file when the fetched commit begins tracking the same path. The worktree update therefore needs its own native overwrite guard in addition to the ordinary status check.

## Goals / Non-Goals

**Goals:**

- Make `main` the single explicit authoritative install ref for both new and existing source trees.
- Prove that the checkout is clean, on `main`, and exactly equal to the fetched authoritative commit before package validation and activation.
- Allow only a normal fast-forward from the installed commit to the fetched commit.
- Reject a fast-forward that would overwrite an ignored local path, without rejecting unrelated ignored content.
- Reject unexpected origin URLs, branches, local-ahead history, divergence, malformed marketplace data, and activation failure with actionable output.
- Exercise those decisions through isolated macOS behavior tests and focused CI/package validation.

**Non-Goals:**

- Normalizing equivalent HTTPS and SSH repository URLs.
- Adding release-tag selection, channels, rollback, migration, stash, reset, clean, or force operations.
- Changing runtime workflow behavior, plugin schemas, or supported operating systems.
- Automatically recovering from malformed user marketplace data or failed Codex activation.

## Decisions

### Pin a constant `main` ref in the installer

The installer will define `main` as a non-configurable repository branch, clone with `--branch main --single-branch --depth 1`, and fetch only `refs/heads/main` from the already verified `origin`. This matches every published installer URL and the repository's current default branch while preventing an environment override from weakening the authority boundary.

Alternative considered: trust the remote's symbolic default branch. Rejected because changing remote metadata would silently change which code the installer activates.

### Gate activation on an exact fetched commit

For both fresh and existing clones, the installer will require a clean attached `main` checkout, fetch the authoritative branch without tags, resolve `FETCH_HEAD` to a commit, and compare it with `HEAD`. If `HEAD` is an ancestor of the fetched commit, it will run `git merge --ff-only <fetched-commit>`. It will then re-check cleanliness and exact commit equality before package validation.

Alternative considered: continue using `git pull --ff-only`. Rejected because pull uses the current branch's configured upstream and treats a local-ahead branch as successful even though it is not the authoritative remote commit.

### Fail closed for local-ahead and diverged history

If the fetched commit is an ancestor of `HEAD`, the installer reports local commits and stops. If neither commit is an ancestor of the other, it reports divergence and stops. The installer never resets, stashes, cleans, switches branches, rewrites remotes, or overwrites files to repair these states.

Alternative considered: reset to the fetched commit. Rejected because it can discard operator work and violates the installer's authority boundary.

### Let Git guard ignored paths during the fast-forward

The installer will run the admitted update as `git merge --ff-only --no-overwrite-ignore <fetched-commit>`. The `--no-overwrite-ignore` option makes the same Git worktree update that performs the fast-forward reject an actual ignored-path collision. This keeps the check path-safe and coupled to the mutation, including names with whitespace or special characters, while unrelated ignored files do not block an otherwise safe upgrade.

Alternative considered: enumerate ignored and incoming paths in shell before merging. Rejected because POSIX shell cannot safely iterate arbitrary NUL-delimited Git paths without extra machinery, a separate preflight duplicates Git's overwrite rules, and the gap between a custom check and the merge adds a race.

Alternative considered: reject every ignored file. Rejected because build caches and local tooling outputs that do not collide with the incoming tree are harmless and should not disable normal upgrades.

### Test the shell entry point as a black box

A macOS-only standard-library unittest module will build temporary local Git remotes and source checkouts, provide an isolated marketplace path, and put a recording fake `codex` executable on `PATH`. Tests will invoke the real `scripts/install.sh` and assert process results, Git state, JSON contents, and activation calls for fresh install, idempotent/fast-forward upgrade, dirty tree, ignored-path collision, unexpected origin/ref, local-ahead/diverged history, malformed marketplace data, and activation failure.

The fixture's bare remote will advertise a non-`main` default branch while still containing `main`, proving that fresh installation explicitly selects the authoritative ref. The package copied into the remote will come from the candidate worktree so its validator evaluates the implementation under test.

Alternative considered: mock individual Git commands. Rejected because command-level mocks would not verify real branch, ancestry, shallow-clone, and fast-forward behavior.

## Risks / Trade-offs

- [The remote rewrites `main`] → A previously installed checkout will fail as local-ahead or diverged; the installer preserves it and requires explicit operator intervention.
- [The remote advances during installation] → The explicit fetch establishes the commit authorized for this invocation; validation and activation use exactly that fetched commit.
- [Incoming `main` starts tracking an ignored local path] → The native no-overwrite guard aborts the fast-forward before changing HEAD or worktree content; marketplace registration and activation do not run.
- [Local filesystem remotes behave differently from hosted transports] → Tests use real Git object graphs and command semantics, while shell syntax and package validators provide additional coverage; validation claims remain macOS-only.
- [Activation fails after marketplace registration] → Preserve the atomic marketplace entry and print the existing remove/add recovery commands; a regression test verifies the non-zero result and guidance.

## Migration Plan

1. Ship the updated installer and tests on the candidate branch.
2. Existing clean `main` installations continue normally and fast-forward when needed.
3. Existing installations on another branch, with local commits or divergence, or with an ignored path that the incoming tree would overwrite stop without changing the checkout and receive an actionable reason.
4. Rollback consists of restoring the prior installer; no repository or marketplace data migration is introduced.

## Open Questions

None. The current public distribution contract already identifies `main` as the authoritative ref, and release channels remain outside this change.
