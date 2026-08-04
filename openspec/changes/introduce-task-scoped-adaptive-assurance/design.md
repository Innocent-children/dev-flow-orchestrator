## Context

Dev Flow 0.2.0 records one complete repository-set snapshot for every repository-backed action and uses a fixed workflow graph to move from implementation through verification, review, rework, and finalization. Its official assets prescribe two verification attempts for `lite` and `investigation`, two verification plus two review attempts for `feature`, `bugfix`, and `refactor`, and three verification plus three review attempts for `full`. This gives strong replay and aggregate identity, but it does not distinguish the task-owned delta from preflight dirt or concurrent ambient drift. Source-producing actions can absorb every Git-visible change made during their interval, independent review inspects the complete current worktree, and any later aggregate drift invalidates task-wide assurance. Review findings are free-form objects whose submitted outcome directly selects success or rework. Review-driven rework returns through shared assurance loops, so unrelated evidence can rerun and successful assurance executions reached through another rework loop can exceed the advertised count.

The runtime remains a local Python-standard-library controller for one task, one current action, one Codex executor, and one exact set of one to eight user-prepared Git worktrees. The controller remains the sole task-state writer. Git branch, worktree, commit, push, PR, CI, and release ownership remains with the user. OpenSpec, codebase-memory, and independent review remain optional external drivers whose outputs are recorded through strict controller contracts.

This change introduces a new persisted protocol family because it changes task identity, snapshot content, workflow dispatch, action payloads, replay, evidence freshness, and finalization. Version 0.3.0 uses a separate controller data namespace and rejects every 0.2.0 task and artifact as unsupported. Existing 0.2.0 bytes are not deleted or rewritten, but they are outside the 0.3.0 product boundary.

## Goals / Non-Goals

**Goals:**

- Give every active task exclusive ownership of each canonical member worktree for the duration of that task.
- Separate the immutable preflight baseline, controller-derived task-owned changes, and ambient workspace drift.
- Bind staged index content as well as worktree content in every snapshot and action binding.
- Derive required verification, integration, review, and manual obligations from acceptance criteria, affected behavior, and risk.
- Let current evidence survive a later change when the changed task slice does not intersect the evidence's declared impact closure.
- Require structured, fingerprinted, causal review findings and derive the workflow outcome in the controller.
- Give the user explicit authority over disputed scope, accepted risk, and contract expansion.
- Make every assurance and rework execution consume an absolute, visible budget reserved by the assurance plan.
- Preserve deterministic replay, append-only records, atomic repository-set snapshots, revision compare-and-swap, and fail-closed validation.

**Non-Goals:**

- Creating, switching, committing, stashing, resetting, cleaning, merging, rebasing, pushing, or deleting Git branches or worktrees.
- Running external CI, creating pull requests, publishing releases, or coordinating multiple Codex executors.
- Inferring semantic impact solely inside the controller; the controller validates declared impact evidence and applies conservative defaults when the evidence is incomplete.
- Migrating or mutating 0.2.0 task ledgers into 0.3.0 shapes.
- Treating a task lease as ownership of repository history or of user files outside the controller's evidence and mutation boundaries.

## Decisions

### 1. Version 0.3.0 is a separate protocol and data namespace

`PRODUCT_VERSION`, every current schema, workflow definition, digest domain, package identity, Skill contract, and controller data directory advances together to `0.3.0`. The runtime accepts only internally consistent 0.3.0 values. It performs no discovery, loading, replay, migration, translation, repair, or compatibility handling for 0.2.0 state. Installation is a clean protocol cut; any retained 0.2.0 data remains inert and unsupported.

### 2. Active worktree ownership is an atomic derived lease

A task owns an active lease on every canonical member worktree identity from successful revision-zero creation through a controller-confirmed `DONE`, `INCOMPLETE`, or `CANCELLED` state. A worktree identity consists of the canonical worktree root and its worktree-specific Git administrative directory. The lease is derived from persisted task membership and terminal state rather than stored in a second mutable registry.

Task creation acquires a data-directory-wide membership lock, canonicalizes and stably captures the complete requested set, scans current-namespace task membership, and rejects the whole start when any requested worktree root or worktree-specific Git directory is already leased. The rejection identifies the owning task and repository ID. It then persists the new task atomically before releasing the membership lock. Terminal transitions remain task-ledger mutations; a later start sees the terminal state and may acquire that worktree.

Admission fails closed when any entry in the current 0.3 namespace cannot be validated well enough to prove its terminal state and immutable membership. The controller preserves the bytes, exposes read-only corruption diagnostics, and creates no new task while the lease inventory is unresolved; it never treats corruption as an implicit terminal transition or lease release. This rule applies only to the current namespace and does not discover or inspect retained 0.2 data.

The lease prevents two valid active tasks from intentionally producing source in the same physical worktree. Distinct linked worktrees have different roots and worktree-specific Git directories, so they may be leased by different tasks even though they share a Git common directory. Existing repository-set topology rules still reject two members with the same Git common directory inside one task.

### 3. The task change capsule has three explicit layers

The controller represents repository state with:

1. **Preflight baseline** — the immutable task-level ownership origin accepted at preflight, including `HEAD`, branch, porcelain status, worktree entries, index entries, and declared resources.
2. **Task change manifest** — the cumulative controller-derived inventory of every still-material task-owned change across the task's complete contract history.
3. **Ambient drift** — a current Git-visible difference from the latest accepted source artifact that has not been claimed and committed by the projected source-producing action.

Every manifest entry is keyed by `(repository_id, path)` and contains the change kind, before and after worktree kind/mode/content digest, before and after index entry set, producer record and action, classification, acceptance-criterion IDs, and an agent-supplied purpose. The controller derives paths, change kinds, content and index digests, and producer identity; the agent supplies only bounded classification, criterion mapping, and purpose. Apply requires claims to cover exactly every changed manifest path. Unknown, omitted, duplicate, cross-root, or contract-incompatible claims fail without a record.

An intentional source action may be retried with corrected claims while its task revision, contract, predecessor, and binding remain current. A claim that expands accepted scope requires a complete contract revision before the source successor can commit. Changes observed outside a bound source-producing interval are projected as ambient drift with exact member and path diagnostics. Repository-dependent assurance remains blocked until the user restores the recorded source, authorizes a contract revision that claims the drift, or explicitly cancels at a stage that supports cancellation.

A contract revision records a complete aggregate `revision-source` as the interval anchor for subsequent actions, but it does not replace the immutable preflight ownership origin or erase current task ownership. The controller rolls the current manifest forward by carrying every prior entry whose task-owned bytes remain material, adding every exact ambient path explicitly adopted by the revision, and then applying later source successors. Inherited entries retain their original producer and before identity; adopted entries retain the drift observation and revision decision as their ownership provenance; all entries record their current after identity and current-contract criterion mapping. Revision validation rejects a missing, silently dropped, or incompatible inherited/adopted entry. Assurance, review, coverage, freshness, and the Dossier consume this canonical roll-forward manifest, while generation-local sources and manifests remain immutable replay history.

Preflight dirt is part of the task environment baseline and not part of the task change manifest. It remains content-bound so any later change to that baseline path is detectable.

### 4. Snapshot identity includes the complete relevant Git index entry set

Each changed, untracked, or declared resource path records the worktree observation and the canonical `git ls-files --stage` entries for stages 0 through 3. A regular file or symlink records its index mode, object ID, and stage when present; a gitlink continues to bind its index object ID and current submodule `HEAD`. The workspace digest includes the ordered index-entry set. Repeated enumeration detects index races during capture, and a later staged-blob replacement changes the persisted digest even when `HEAD`, porcelain status, path, and worktree bytes are unchanged.

Unmerged index stages are representable for read-only diagnosis but block a source successor, assurance record, or successful finalization until the workflow explicitly supports that state. Object IDs are validated according to the repository's Git object format.

### 5. Assurance is a validated obligation plan

Planning produces `dev-flow-assurance-plan/0.3.0`. `lite` derives the same shape from its contract and recorded impact evidence. The plan contains:

- one stable plan ID and digest bound to the effective contract and selected workflow;
- an impact manifest of affected repositories, paths, symbols or stable labels, cross-repository edges, and confidence;
- one or more obligations keyed by stable obligation ID;
- each obligation's kind (`repository-check`, `integration-check`, `documentation-check`, `independent-review`, or `manual-evidence`), criterion IDs, member scope, impact closure, prerequisites, evidence contract, invalidation rules, and absolute execution allowance;
- aggregate verification, review, rework, and total-action ceilings;
- the deterministic ordering rules used to project the next obligation.

Every acceptance criterion must be covered by at least one obligation or by a current criterion waiver. The controller applies the closed `dev-flow-assurance-policy/0.3.0`; official and custom workflows cannot add free-form trigger semantics or weaken its floors. The only risk-trigger IDs are `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, and `protocol`. Only `source-confirmed` impact confidence permits a focused plan. `degraded`, `partial`, and `unknown` confidence all select the conservative plan: one repository check for every task member, integration checks for every declared or applicable cross-member edge, and independent review, unioned with the selected profile floor and criterion-required evidence.

The official profile matrix is normative:

| Profile | Minimum canonical obligation set | Independent review | Per-obligation cap |
| --- | --- | --- | ---: |
| `lite` | One repository check per affected member; integration checks for affected boundaries; criterion-required evidence | Closed risk trigger only | 2 |
| `feature` | `lite` floor plus one documentation check when public behavior, API, configuration, or user-documentation criteria are present | Closed risk trigger only | 2 |
| `bugfix` | `lite` floor plus one regression evidence contract binding pre-fix reproduction or an equivalent baseline and post-fix success | Closed risk trigger only | 2 |
| `investigation` | One manual-evidence obligation covering all conclusions; executable checks only when reproduction requires them; no fabricated implementation obligation | Closed risk trigger only | 2 |
| `refactor` | One repository check per affected member covering all declared invariants; integration checks for affected boundaries | Closed risk trigger only | 2 |
| `full` | One repository check per task member; integration checks for all declared boundaries; one documentation check; criterion-required manual evidence | Always | 3 |

Canonical grouping permits at most one repository check per member, one integration check per distinct evidence contract over the sorted required edge set, and one obligation of each of documentation, manual-evidence, and independent-review kinds; grouped criterion IDs are the sorted union. Risk and conservative requirements are unioned with the profile floor, never duplicated or allowed to replace a stronger obligation.

The controller validates shape, coverage, graph acyclicity, budgets, profile floors, and conservative fallback. It does not execute driver code or trust the plan to declare its own digest or currentness.

The obligation plan avoids a general predicate language, keeps workflow dispatch deterministic, and gives each projected action a typed evidence contract that can be validated and replayed.

### 6. Official workflows dispatch outstanding obligations deterministically

The 0.3.0 workflow language adds an `assurance.dispatch` handler and typed obligation completion/rework targets. Fixed product stages such as preflight, impact, planning, source production, contract revision, cancellation, and dossier finalization remain explicit. The assurance region projects the next unmet obligation whose prerequisites are current. Completing an obligation records its evidence and returns to dispatch. A current plan with no unmet obligation advances to success finalization.

Failure creates a bounded rework obligation that names the exact failed obligation or blocking finding IDs and its permitted source scope. A committed rework source manifest invalidates only obligations whose impact closure intersects the changed task slice or whose governing inputs changed. Dispatch then projects those obligations again. A disposition that resolves a finding without a source change does not fabricate a source producer or invalidate unrelated verification.

Custom workflows use the same typed dispatch contracts. Workflow validation rejects an assurance region that can schedule an obligation or rework execution outside the plan's absolute ceilings.

### 7. Review findings are structured and the controller derives the outcome

`review.record` accepts a fingerprinted `dev-flow-independent-review/0.3.0` result and a list of `dev-flow-review-finding/0.3.0` values. Every finding contains:

- stable finding ID and fingerprint;
- severity and explicit blocking flag;
- causal relation: `introduced`, `affected`, `pre-existing`, `out-of-scope`, or `unknown`;
- criterion IDs;
- repository ID and bounded path, symbol, resource, or integration label;
- evidence and smallest sufficient resolution;
- the reviewed task-change-manifest, assurance-plan, guidance, and snapshot digests.

The controller validates identifiers, member/path containment, criterion references, fingerprints, and exact review inputs. A finding schedules source rework only when it is current, `blocking: true`, and causally `introduced` or `affected` within the current plan's impact closure. Pre-existing and out-of-scope findings remain visible adjacent observations. A non-blocking unknown finding remains advisory, but a `blocking: true` unknown finding leaves the review obligation in `triage-required` rather than approving or scheduling source rework. Bounded impact refresh, current causal evidence, or an authorized finding disposition must resolve that state before completion.

When valid review evidence proves an `affected` relation outside the current impact closure, the controller records an impact-gap result, invalidates the governing impact evidence and assurance plan, and reenters bounded impact planning under the same contract and remaining total-action authority. Once a replacement plan contains the proven relation, finding governance may schedule its causal rework. Contract expansion is required only when the accepted delivery scope or criteria must change. The controller derives `approved`, `changes-requested`, `triage-required`, or `unavailable`; the agent cannot select a contradictory outcome. Independent approval still requires a genuinely independent available reviewer or an exact current assurance waiver for unavailability.

This boundary permits reviewers to report useful adjacent observations while preventing them from scheduling task rework by themselves, without allowing unresolved blocking causality or an underestimated impact closure to produce approval.

### 8. Finding dispositions preserve user authority

The existing decision mutation adds a `finding-disposition` kind whose subject is the exact finding fingerprint. Supported outcomes are:

- `accepted-risk`: records explicit acceptance and makes that current blocking causal or unresolved-causality finding non-blocking for the current contract while preserving its evidence, uncertainty, and risk in coverage and the Dossier;
- `confirmed-out-of-scope`: records the user's scope decision and prevents the finding from scheduling rework under the current contract;
- `expand-contract`: requires and atomically accompanies a complete next contract revision before the finding can become implementation scope.

Dispositions require a rationale and actor label, are unique per finding and contract digest, and become historical after contract revision or review-fingerprint replacement. They never relabel self-review as independent approval and never supply missing verification evidence.

### 9. Evidence reuse is slice-aware and conservative

Every assurance artifact records the exact obligation, plan digest, task-change-manifest digest, covered criterion IDs, member scope, impact closure, commands or manual evidence, environment limitations, and observed assurance snapshot. Freshness compares a later manifest delta and governing inputs with that bound closure:

- disjoint changes preserve the artifact as current;
- an intersection invalidates the artifact and its dependent obligations;
- an integration obligation is invalidated by a change in any member or contract edge in its declared closure;
- changed governing resources always invalidate descendants;
- missing, stale, or ambiguous closure evidence invalidates conservatively.

The full current repository-set snapshot remains attached to records for forensic replay and ambient-drift detection. Completion authority is derived from the task change capsule and all currently required obligations, not from partial member approval. Reused evidence remains one task-wide plan result with explicit member scope; it does not create independent per-member terminal states.

### 10. Budgets are absolute reserved executions

Each plan reserves integer allowances for every obligation and bounded rework obligation plus aggregate verification, review, rework, and total workflow-action ceilings. Every recorded execution consumes one unit whether it passes, fails, becomes unavailable, or is later superseded. Dispatch cannot project an execution with zero remaining allowance. Cross-obligation routes cannot create new allowance.

Let `V` be the number of required non-review assurance obligations, `R` the number of required independent-review obligations, and `A` the profile's per-obligation cap: two for every profile except `full`, whose cap is three. Let `U` be the canonical retry-unit total in the initial plan's conservative budget-reservation obligation set: each obligation whose evidence contract permits source rework contributes `max(allowance - 1, 0)`, and every other obligation contributes zero. The controller derives, rather than accepts, these class ceilings:

| Profile | Verification ceiling | Review ceiling | Rework ceiling |
| --- | --- | --- | --- |
| `lite`, `investigation` | `min(A × V, V + 1)` | `0` if `R = 0`, else `min(A × R, R + 1)` | `min(1, U)` |
| `feature`, `bugfix`, `refactor` | `min(A × V, V + 2)` | `0` if `R = 0`, else `min(A × R, R + 1)` | `min(2, U)` |
| `full` | `min(A × V, V + 4)` | `min(A × R, R + 2)` | `min(4, U)` |

When `U` is zero, the rework ceiling is zero. A failed assurance obligation uses its next unused canonical retry unit when its source-rework execution commits. Current blocking causal findings from one review result are grouped into one finding-bound source-rework obligation for the governing review obligation's next unused retry unit; materialization creates no budget, and the recorded rework execution consumes one reserved rework unit. The initial valid plan fixes `U`, the rework ceiling, and consumed units for that effective contract. A same-contract replacement inherits them unchanged and cannot add, recompute, or reset retry authority; a valid contract revision derives a new bounded set while retaining prior history.

The total-action ceiling is the exact sum of reachable fixed mutations under the effective contract, the three class ceilings, the product-bounded reserve for reachable unique waiver, disposition, persisted-reuse, and prerequisite-refresh subjects, and one non-cancelled Dossier finalization; it cannot exceed 256. A governance subject is unique by contract, mutation kind, and criterion, assurance, finding, obligation, or prerequisite fingerprint as applicable, and may reserve and consume at most one total-action unit. A persisted reuse, waiver, disposition, or prerequisite refresh consumes one total-action unit but no verification, review, or rework unit. A read-only reuse derivation that appends no record consumes nothing.

`next`, `apply`, conflict projections, `show`, and the final Dossier expose used and remaining counts, unmet obligations, and a deterministic `maximum_remaining_actions`. Exhaustion routes to the plan's incomplete finalizer with the exact unmet obligations and findings.

### 11. Delivery Dossier reports the task boundary and assurance rationale

The 0.3.0 Dossier includes the immutable preflight ownership origin, every contract-revision interval anchor, final roll-forward task change manifest, ambient-drift status, assurance plan and profile, required obligations, executed and reused evidence, skipped non-required checks with their rule basis, structured findings and dispositions, absolute budget usage, criterion coverage, member and integration scope, remaining risks, and handoff guidance. `DONE` requires no unresolved ambient drift, `triage-required` review, impact gap, incomplete current criterion coverage, or missing current evidence for a required obligation. `INCOMPLETE` reports every unmet or exhausted obligation without promoting stale or out-of-scope evidence.

## Risks / Trade-offs

- **Incorrect impact claims could preserve evidence that should be rerun** → Bind every claim to source-confirmed evidence, enforce workflow-profile floors, and expand unknown or degraded impact to the conservative obligation set.
- **Exclusive leases reduce same-worktree concurrency** → Return the owning task and support concurrent delivery through distinct user-prepared worktrees, including linked worktrees with separate worktree-specific Git directories.
- **Per-path index and manifest capture increases snapshot cost** → Reuse existing path and content budgets, add index-entry count and byte limits, and keep two-pass complete-set stability checks.
- **Dynamic dispatch increases replay and validation complexity** → Use a closed obligation vocabulary, deterministic ordering, canonical plan digests, and reject arbitrary predicate expressions.
- **Selective reuse can obscure why a check did not rerun** → Project and persist the exact closure comparison and include every reuse or skip basis in the Dossier.
- **A source action can submit misleading ownership purpose text** → Derive the changed path set and digests in the controller, require criterion mapping, and make claims review inputs; unknown or incompatible claims fail closed.
- **A corrupted current task cannot safely prove lease release** → Preserve its bytes and diagnostics and fail current-namespace admission closed until valid membership and terminal authority can be established; never infer release from corruption.

## Implementation Plan

1. Add 0.3.0 product, schema, digest-domain, snapshot, manifest, assurance-plan, finding, projection, record, and Dossier constants under a new data namespace.
2. Implement index-aware snapshots and roll-forward task change manifest primitives with focused race, staged-blob, dirty-baseline, contract-revision, drift-adoption, resource, and multi-repository tests.
3. Implement atomic worktree-specific active-membership checks, current-namespace corrupt-inventory fail-closed behavior, and terminal lease release semantics derived from task state.
4. Implement closed assurance-policy validation, obligation dispatch, structured findings, triage and impact-gap reentry, dispositions, slice-aware freshness, hard budgets, and deterministic replay.
5. Convert all six official workflows and custom-workflow validation to the 0.3.0 obligation-dispatch language.
6. Update the three Skills, package metadata, Hook projection, CLI views, candidate validation, installed journeys, and Delivery Dossier rendering.
7. Update English public documentation first, then fully synchronize the Simplified Chinese counterparts.
8. Validate the candidate package and installed task journeys across clean, pre-dirty, staged, unstaged, untracked, multi-repository, rework, restart, conflict, and exhausted scenarios.

Code rollback may reinstall an earlier release, but that runtime cannot operate 0.3.0 state and no cross-version task migration is provided. Reinstalling 0.3.0 restores access only to valid 0.3.0 tasks under the unchanged namespace.

## Resolved Product Bounds

The following `0.3.0` values are product contracts, not implementation choices:

| Bounded collection or output | Maximum |
| --- | ---: |
| Snapshot paths per repository | 4,096 |
| Git index stage entries per repository | 12,288 |
| Git index command output per repository capture | 2 MiB |
| Ownership claims per source action | 128 |
| Entries in the current roll-forward manifest | 4,096 |
| Entries in one impact report | 128 |
| Obligations in one assurance plan | 64 |
| Findings in one review | 64 |
| Evidence items in one assurance execution | 64 |
| Workflow actions under one effective contract | 256 |

These collection limits apply together with the existing 64 KiB action-payload and 8 KiB text-field limits. A value beyond a bound is rejected atomically without truncation or a partial record. An impact report that cannot enumerate its closure within 128 entries may record the bounded reason and `unknown` confidence, which selects the conservative assurance plan; it cannot submit a truncated focused closure. No product decision remains open for implementation.
