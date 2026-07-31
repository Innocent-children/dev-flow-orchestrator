---
name: review-dev-flow-change
description: Independently review a completed V4 direct-route or OpenSpec implementation across one or more Git repositories. Use before workflow handoff to inspect the complete committed, staged, unstaged, and untracked snapshot against requirements, approved artifacts, focused tests, security boundaries, and cross-repository sequencing, then return PASS, CONDITIONAL, or FAIL.
---

# Review Dev Flow Change

Perform a fresh, independent, read-only review.

1. Collect the original requirement, repository paths, recorded base commits,
   approved direct contract or current OpenSpec artifacts, focused test
   evidence, frozen candidate identity, and controller review manifest.
2. For OpenSpec, query current JSON status and instructions, then read the
   concrete artifact paths returned. Do not assume a fixed phase sequence.
3. Verify the complete snapshot for every repository: committed changes from
   the recorded base, cached changes, unstaged changes, and every untracked
   file. Account for renames, deletions, modes, symlinks, submodules, and
   generated files.
4. Use the explicitly selected current-workspace `codebase-memory` project for
   discovery and confirm material findings in source.
5. Map every requirement and non-goal to implementation and focused test
   evidence. Inspect correctness, error paths, concurrency, idempotency,
   authorization, secret handling, path safety, effect settlement, and
   cross-repository ordering.
6. Do not edit files, controller state, Git state, OpenSpec tasks, or evidence.

Return exactly one verdict:

- `FAIL` for a blocking defect, unmet requirement, failing required test, or
  incomplete snapshot that prevents a safe decision;
- `CONDITIONAL` when no defect is demonstrated but explicit external evidence
  is still required;
- `PASS` only when no blocking or conditional finding remains.

Lead with findings ordered by severity and include precise paths or symbols,
consequence, smallest sufficient resolution, test evidence, skipped checks,
snapshot limitations, and conditions for re-review. Say `No actionable
findings` when appropriate. Also return `review_fingerprint` as the lowercase
SHA-256 of the bounded canonical review result so the full workflow can bind
the independently produced artifact without inventing a second actor identity.
