---
name: review-dev-flow-change
description: Independently review a completed direct-route or OpenSpec implementation across one or more Git repositories. Use before workflow handoff to inspect the full committed, staged, unstaged, and untracked snapshot against the requirement, impact analysis, approved contract or current OpenSpec artifacts, tests, compatibility, migration, security, and cross-repository sequencing, and return PASS, CONDITIONAL, or FAIL.
---

# Review Dev Flow Change

Perform an independent, read-only review of the complete implementation. Use a fresh reviewer context when available and pass raw requirements, artifacts, snapshots, and test outputs rather than the implementer's conclusions. Rebuild the evidence from those inputs; do not accept the implementer's summary as proof.

## Establish the review contract

1. Collect the original requirement, repository paths, recorded base commit for each repository, impact report, selected route, recorded test evidence, the controller-generated review manifest, and each repository's current workspace-index project ID when available.
2. For the direct route, read the approved compact contract: goal, scope, non-goals, acceptance criteria, tests, and risks.
3. For the OpenSpec route, query current JSON status and instructions, then read the concrete artifact paths they return. Discover relevant project-generated `.codex/skills/openspec-*` guidance instead of assuming a fixed schema or artifact sequence.
4. Read [references/independent-review.md](references/independent-review.md) before inspecting changes.

If a base commit, repository, route contract, or required artifact is missing or ambiguous, identify the gap explicitly. Do not invent the comparison boundary.

Use codebase-memory only as a discovery aid. During review, explicitly pass the current-generation workspace project ID from `show.index_selection` to every graph query. The MCP server does not select it automatically. Use the baseline project only for a separately labelled before-state query, never as a fallback for a missing or stale workspace index. Confirm every material conclusion in current source and the controller snapshot.

## Inspect the complete snapshot

Verify the controller manifest and its recorded hashes when one is supplied. For every repository, independently inspect and retain separate evidence for:

- committed changes from the recorded base commit through `HEAD`;
- cached changes from `HEAD` to the index;
- unstaged changes from the index to the working tree;
- every untracked file not ignored by Git, including its content or an explicit binary/size classification.

Review the union, not just the latest commit or a single diff. Detect overlapping edits across layers, renames, deletions, mode changes, submodule changes, generated files, and unexpected repository state. Do not stage, edit, commit, reset, clean, stash, switch branches, or mark OpenSpec tasks complete.

Use the controller-produced patches and fingerprints as canonical Git evidence. Those commands disable external diff drivers and text conversion, force submodule visibility, and neutralize environment/configuration that could hide tracked changes. Do not replace them with an ordinary local `git diff`; report an incomplete or inconsistent snapshot instead.

## Evaluate the change

Trace each requirement and acceptance criterion to implementation and test evidence. Check for:

- omitted work, out-of-scope work, accidental files, and unexplained generated output;
- behavioral correctness, errors, boundary cases, concurrency, idempotency, and observability;
- test relevance, assertions, failures, skipped checks, per-repository binding to the current approved plan SHA-256 and unique approval ID (with time only as supporting evidence), and gaps between claimed and demonstrated behavior;
- public API, event, data, configuration, and backward-compatibility effects;
- migration ordering, rollback, mixed-version behavior, authentication, authorization, secret handling, and unsafe input/output paths;
- cross-repository contract agreement plus implementation, deployment, and rollback order.

Use OpenSpec verification, when available, only as supplementary evidence. Reproduce or challenge its claims and never translate its result directly into this review's gate.

## Return one verdict

Return exactly one overall verdict: `PASS`, `CONDITIONAL`, or `FAIL`, using the thresholds in the reference. Lead with actionable findings ordered by severity and include precise repository-relative file and symbol references. For every finding, state the violated requirement or risk, evidence, consequence, and required resolution.

Include the reviewed snapshot ID and SHA-256, snapshot coverage per repository, requirement coverage, test evidence, compatibility/migration/security findings, cross-repository sequencing, residual unknowns, and the conditions for re-review. If there are no findings, say so explicitly and still report evidence limits.
