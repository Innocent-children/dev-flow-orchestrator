## MODIFIED Requirements

### Requirement: Public skill guidance matches the current product
The packaged `follow-dev-flow` Skill and agent metadata SHALL describe product version 0.3.0 and one exact set of one to eight user-prepared local Git worktrees. Guidance SHALL explain official workflow selection; repeatable repository selection; active leases over canonical roots and worktree-specific Git administrative directories; one task and one current action for one Codex executor; structured contracts; the closed `dev-flow-assurance-policy/0.3.0` profile matrix and risk triggers; the immutable preflight ownership origin and roll-forward manifests; contract-revision interval anchors and exact drift adoption; ambient-drift handling; canonical assurance plans and obligations; structured causal review findings, `triage-required`, and impact-gap planning reentry; absolute recorded-attempt and total-action budgets; optional-driver fallback; explicit decisions; and Delivery Dossier completion. It SHALL explain that distinct linked worktrees sharing a Git common directory can support separate active tasks while one repository set rejects duplicate common-directory members. It SHALL keep branch/worktree creation and removal, Git publication, parallel Agent execution, and external CI/PR/release effects outside controller authority.

The Skill SHALL run only the current projected assurance obligation and the smallest command or manual check declared by that obligation. It SHALL NOT run undeclared retries outside the projected allowance, reuse stale or intersecting evidence, convert an adjacent observation into a blocking causal finding, claim ambient drift as task-owned without complete ownership claims, or present a non-required check as completed assurance. Only source-confirmed impact MAY support focused assurance; degraded, partial, unknown, stale, unavailable, or unconfirmed impact SHALL select the conservative assurance path and record the reason. A blocking unknown-causality finding SHALL keep review in bounded causal triage and SHALL NOT be presented as approval or sent directly to source rework. A proven affected relation outside the current closure SHALL invalidate the plan and reenter impact analysis and planning under the same contract; guidance SHALL request contract revision only when accepted scope or criteria must change.

The repository-mismatch cancellation handshake SHALL remain explicit. After the executor confirms that immutable repository membership cannot satisfy the accepted contract, it SHALL stop the current action, identify the exact active task, and obtain explicit user authority for cancellation unless the current request already provides it. Cancellation SHALL use the injected controller only at a declared stage and completion SHALL be reported only after `done: true`, `status: CANCELLED`, and `current_node: cancelled`. Failure or unavailability SHALL preserve the active state and worktree lease.

#### Scenario: Packaged agent metadata is inspected
- **WHEN** package validation reads the main Skill and agent metadata
- **THEN** stale version, schema, workflow, namespace, ownership, assurance-plan, finding, budget, repository-topology, or executor guidance causes validation to fail

#### Scenario: Multi-repository start guidance is inspected
- **WHEN** package validation reads the documented start path
- **THEN** it requires repeatable `--repo`, canonical exact-set semantics, active member leases, user-prepared worktrees, and one Codex executor

#### Scenario: Focused obligation is projected
- **WHEN** a current plan requires one focused repository check and no integration or review obligation
- **THEN** the Skill runs and records only that obligation and preserves the plan's explainable not-required decisions

#### Scenario: Adjacent review observation is found
- **WHEN** independent review reports a pre-existing, out-of-scope, or non-blocking unknown-causal observation
- **THEN** guidance records it truthfully and does not request task rework or expand the contract

#### Scenario: Blocking review causality is unknown
- **WHEN** independent review reports a current blocking finding whose causal relation is unknown or disputed
- **THEN** guidance preserves `triage-required`, runs only the projected bounded causal refresh, and claims neither approval nor direct source rework without a governed relation or authorized disposition

#### Scenario: Review identifies an impact gap
- **WHEN** current source evidence proves an affected relation outside the governing impact closure
- **THEN** guidance follows plan invalidation and impact/planning reentry under the same contract and requests contract revision only if accepted scope or criteria must change

#### Scenario: Repository mismatch lacks cancellation authority
- **WHEN** the accepted requirement cannot be satisfied by immutable membership and the user has not authorized cancellation
- **THEN** the executor stops, reports that the task and leases remain active, and requests the exact cancellation decision

#### Scenario: Repository mismatch cancellation is authorized
- **WHEN** the user authorizes cancellation at a stage that declares it
- **THEN** the executor invokes the controller and reports completion only after the returned terminal cancellation projection

#### Scenario: Repository mismatch cannot be cancelled
- **WHEN** cancellation is unavailable or a member cannot be captured
- **THEN** the executor reports the active state, retained leases, and required restoration or operator action without substituting repositories

#### Scenario: Packaged mismatch guidance is inspected
- **WHEN** package validation reads the main Skill
- **THEN** omission of mismatch stop, explicit authority, active-state, lease, controller-cancellation, or terminal-verification guidance causes validation to fail

### Requirement: Candidate validation proves supported repository topology
The candidate package SHALL expose authoritative current capability definitions for repository topology, active member leases, task change ownership, assurance planning, finding governance, and absolute recorded-attempt budgets. Validation SHALL cover runtime, CLI, Hook, Skills, official workflows, custom workflow validation, installed journeys, strict version-boundary rejection, and public documentation. Evidence SHALL include one-member and larger exact sets, secondary-member resume, pre-existing dirty baselines, staged/unstaged/untracked task changes, ambient drift, explicitly scoped resources, selective evidence reuse, structured findings and dispositions, obligation exhaustion, and aggregate Dossier generation.

Candidate validation SHALL prove that every official workflow embeds the exact closed `dev-flow-assurance-policy/0.3.0`; uses only the trigger IDs `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, and `protocol`; and normalizes every non-source-confirmed, degraded, partial, stale, unavailable, unconfirmed, or unknown impact result to conservative every-member, declared-or-applicable-integration, and independent-review assurance plus profile- or criterion-required documentation and manual evidence. It SHALL reject custom policies that remove a base-profile obligation, weaken a risk or unknown result, raise an allowance or product maximum, or introduce a free-form trigger. It SHALL validate canonical grouping as at most one repository check per required member, one integration check per distinct evidence contract over the sorted required boundaries, and at most one documentation, manual-evidence, and independent-review obligation per plan.

Candidate validation SHALL derive rather than accept class budgets. With `V` required non-review obligations, `R` required independent-review obligations, `A = 2` for every profile except `full`, `A = 3` for `full`, and `U` equal to the sum of `max(allowance - 1, 0)` for each source-rework-capable obligation in the initial plan's conservative canonical budget-reservation set, it SHALL prove these ceilings:

| Profile | `verification_ceiling` | `review_ceiling` | `rework_ceiling` |
| --- | --- | --- | --- |
| `lite`, `investigation` | `min(A × V, V + 1)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(1, U)` |
| `feature`, `bugfix`, `refactor` | `min(A × V, V + 2)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(2, U)` |
| `full` | `min(A × V, V + 4)` | `min(A × R, R + 2)` | `min(4, U)` |

Candidate validation SHALL prove `rework_ceiling = 0` when `U = 0`, the exact value below the profile cap, and the exact cap when `U` meets or exceeds it. It SHALL prove that one review result groups all current blocking causal findings into one finding-bound source-rework obligation against the governing review obligation's next unused retry unit, that materialization creates no authority, and that execution consumes exactly one reserved retry and rework unit. Restart and same-contract replacement SHALL preserve the initial reservation set, `U`, ceiling, and consumption without recomputation or reset; only a new contract digest derives a new set.

The validated total-action ceiling SHALL be the exact sum of reachable fixed mutations, all three class ceilings, the product-bounded reserve for reachable unique waiver, finding-disposition, persisted-reuse, and prerequisite-refresh subjects, and one non-cancelled Dossier finalization, and SHALL be at most 256 per effective contract. Persisted waiver, disposition, reuse, and prerequisite-refresh mutations SHALL each charge one total-action unit and no verification, review, or source-rework unit; read-only reuse derivation SHALL charge none. Same-contract replacement plans SHALL inherit consumption and SHALL NOT change original ceilings.

Installed-package evidence SHALL execute both a source-confirmed focused journey and a closed-trigger journey for each of `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full`. The journeys SHALL prove the exact profile floor, review rule, per-obligation allowance, class formulas, not-required reasons, and Dossier result from the installed artifact rather than source-tree-only fixtures. Additional installed journeys SHALL prove contract-revision carry-forward with exact adopted drift, blocking unknown-causality triage, affected impact-gap planning reentry, corrupt-current-inventory admission failure, and concurrent admission of distinct linked worktrees.

Boundary validation SHALL exercise both the exact maximum and the first excess value for 4,096 snapshot paths per repository, 12,288 Git index stage entries per repository, 2 MiB of Git index command output per repository capture, 128 ownership claims per source action, 4,096 current roll-forward manifest entries per task, 128 impact entries, 64 plan obligations, 64 findings per review execution, 64 evidence items per assurance execution, 256 actions per effective contract, the shared 64 KiB action payload, and the shared 8 KiB per-text limit. Exact maximums SHALL remain admissible when every other rule holds. First-excess values SHALL fail atomically without truncation or partial mutation, except that a 129-entry impact closure SHALL record bounded overflow, normalize to unknown, and select conservative assurance rather than submit a truncated focused closure.

Candidate validation SHALL require exact version 0.3.0 in plugin manifest, package metadata, lock file, runtime authority, workflow and assurance-policy documents, schema identifiers, Hook and Skill guidance, installed evidence, and current English and Chinese public documentation. Unsupported generation-coded or component-specific identities SHALL be rejected from executable current assets. Runtime action validation SHALL require the complete 0.3.0 schema family for driver results, snapshots, task change manifests, assurance plans, verification coverage, independent review, review findings, action bindings, projections, records, and Dossiers. Any supplied missing, mixed, or non-0.3 identity SHALL fail closed during initial application and replay without conversion or partial recording. Discovery and admission tests SHALL prove that the 0.3 runtime never enumerates, discovers, reads, replays, migrates, translates, repairs, or deletes retained 0.2 namespace bytes.

#### Scenario: Runtime and capability definition drift
- **WHEN** the candidate advertises task-scoped adaptive assurance but any runtime, CLI, workflow, Hook, Skill, Dossier, or installed journey retains fixed aggregate-only behavior
- **THEN** candidate validation fails

#### Scenario: Unsupported later-stage capability is claimed
- **WHEN** candidate assets claim automatic branch/worktree management, parallel repository executors, per-repository partial assurance reuse, or external CI/PR/release orchestration
- **THEN** candidate validation fails because those capabilities are outside the multi-repository personal delivery core

#### Scenario: Installed exact-set journey succeeds
- **WHEN** the installed candidate executes a task over two user-prepared worktrees, resumes it from the second repository, verifies current aggregate evidence, and finalizes delivery
- **THEN** the recorded dossier identifies both repositories and candidate validation accepts the journey

#### Scenario: Installed one-member journey succeeds
- **WHEN** the installed candidate executes and finalizes a task with one `--repo` argument
- **THEN** its snapshot, projection, structured verification, scoped resources, and Dossier use the same current repository-set schemas as the larger-set journey

#### Scenario: Embedded current-product schema is missing or unsupported
- **WHEN** an action submits a manifest, plan, verification, review, finding, driver, or decision value without its exact current schema and binding
- **THEN** action validation fails without recording a partial result

#### Scenario: Non-current value is supplied
- **WHEN** a caller supplies a 0.2.0 or otherwise non-0.3 workflow, policy, task, record, snapshot, artifact, action value, or binding to a current input boundary
- **THEN** the 0.3 runtime rejects the value as unsupported without compatibility parsing, replay, migration, translation, repair, fallback, or partial mutation

#### Scenario: Retained prior-namespace bytes exist
- **WHEN** retained 0.2 namespace bytes are present beside the installed 0.3 data namespace
- **THEN** discovery, admission, replay, and package validation leave those bytes unchanged and never enumerate, discover, read, migrate, translate, repair, or delete them

#### Scenario: Unsupported workspace or delivery authority is claimed
- **WHEN** candidate assets claim automatic branch/worktree creation or deletion, parallel repository executors, or external CI/PR/release orchestration
- **THEN** candidate validation fails because those effects remain outside controller authority

#### Scenario: Closed trigger vocabulary is exhaustive
- **WHEN** candidate tests exercise each of `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, and `protocol` and then supply one additional trigger ID
- **THEN** every supported trigger requires independent review without removing any profile-floor obligation, and the additional trigger is rejected rather than interpreted as policy

#### Scenario: Non-source-confirmed impact cannot focus
- **WHEN** installed planning receives degraded, partial, stale, unavailable, unconfirmed, internally inconsistent, or otherwise unknown impact evidence
- **THEN** every profile derives repository checks for all task members, integration checks for every declared or applicable boundary, independent review, and its profile- or criterion-required documentation and manual evidence

#### Scenario: Installed lite journeys prove focused and triggered policy
- **WHEN** the installed suite runs a source-confirmed repository-local `lite` journey with no risk trigger and a second `lite` journey with a `path-safety` trigger
- **THEN** the first groups one repository check for the affected member with integration, documentation, manual, and review dimensions marked not required as applicable, while the second adds independent review without changing `A = 2`

#### Scenario: Installed feature journeys prove focused and triggered policy
- **WHEN** the installed suite runs a source-confirmed `feature` journey whose criterion covers public behavior and a second `feature` journey with an `authorization` trigger
- **THEN** the first groups affected-member and affected-boundary checks plus one documentation check without profile-only review, while the second adds independent review and both use `A = 2`

#### Scenario: Installed bugfix journeys prove focused and triggered policy
- **WHEN** the installed suite runs a source-confirmed local `bugfix` journey and a second `bugfix` journey reaching a `persistence-replay` boundary
- **THEN** each proves one regression evidence contract with pre-fix reproduction or equivalent baseline and post-fix success, the focused journey requires no profile-only review, and the triggered journey adds the affected integration and independent-review obligations with `A = 2`

#### Scenario: Installed investigation journeys prove focused and triggered policy
- **WHEN** the installed suite runs a source-confirmed `investigation` whose conclusions require no executable reproduction and a second investigation with a `security` trigger whose conclusion requires bounded executable reproduction
- **THEN** the first uses one manual-evidence obligation and no fabricated repository, integration, review, source, or implementation action, while the second adds only the exact reproduction checks and independent review required by policy and both use `A = 2`

#### Scenario: Installed refactor journeys prove focused and triggered policy
- **WHEN** the installed suite runs a source-confirmed member-local `refactor` and a second refactor reaching a `cross-repository-contract` boundary
- **THEN** the first groups one affected-member check over every declared invariant without profile-only review, while the second groups the affected-member and distinct boundary checks plus independent review and both use `A = 2`

#### Scenario: Installed full journeys prove focused and triggered policy
- **WHEN** the installed suite runs a source-confirmed `full` journey and a second `full` journey with a `protocol` trigger
- **THEN** each requires one repository check per task member, one integration check per distinct declared-boundary evidence contract, one documentation check, necessary criterion-required manual evidence, independent review, and `A = 3`, while the triggered journey records the trigger without duplicating grouped obligations

#### Scenario: Installed exact-set adaptive journey succeeds
- **WHEN** the installed candidate executes a task over two user-prepared worktrees, resumes from the second member, changes one member, requires only plan-derived member and integration obligations, and finalizes
- **THEN** the Dossier identifies both repositories, the exact task manifest, required and not-required assurance, evidence reuse basis, and complete criterion coverage

#### Scenario: Installed one-member focused journey succeeds
- **WHEN** an installed one-member task requires one focused check and no integration or independent review
- **THEN** its coverage omits synthetic integration and review evidence while the Dossier proves why those obligations were not required

#### Scenario: Installed revision carries ownership and adopts exact drift
- **WHEN** an installed journey revises its contract after one task-owned entry exists, authorizes exact adoption of one ambient-drift entry, and later produces another task-owned entry
- **THEN** the revision source anchors only the new interval and the current manifest contains every still-material inherited entry, the exact adopted entry, and the later entry with complete producer, adoption, contract-generation, and criterion lineage

#### Scenario: Installed revision omits current ownership
- **WHEN** a replacement contract manifest omits a still-material inherited entry or an exact ambient-drift entry adopted by the revision
- **THEN** the complete revision fails atomically and preserves the prior contract, interval, manifest, and workspace authority

#### Scenario: Installed blocking unknown finding requires triage
- **WHEN** installed review records a current `blocking: true` finding whose causality is `unknown`
- **THEN** the controller derives `triage-required`, keeps review unresolved, and permits only bounded causal prerequisite refresh or an authorized disposition before approval or source rework

#### Scenario: Installed affected finding exposes an impact gap
- **WHEN** installed review supplies source-confirmed causal evidence that a task-owned change affects a location outside the current impact closure
- **THEN** the controller records `impact-gap`, invalidates the plan, and reenters bounded impact analysis and planning under the same contract and remaining counters before any source rework

#### Scenario: Installed impact gap changes accepted scope
- **WHEN** the proven affected relation cannot be covered without changing accepted scope or criteria
- **THEN** the installed route requires an authorized complete contract revision, while a relation already covered by the contract reenters planning without revision

#### Scenario: Installed current inventory is corrupt
- **WHEN** installed task admission encounters a 0.3 namespace entry whose immutable membership or controller-confirmed terminal state cannot be validated
- **THEN** admission fails closed for the current inventory, preserves the corrupt bytes, reports bounded diagnostics, creates no task or partial lease, and does not infer that any member was released

#### Scenario: Installed linked worktrees run as separate active tasks
- **WHEN** two concurrent installed starts use prepared linked worktrees with distinct canonical roots and worktree-specific Git administrative directories but the same Git common directory
- **THEN** both tasks may acquire their independent leases, while a repeated root or worktree-specific directory across tasks and duplicate common-directory members within one task remain rejected

#### Scenario: Unrelated finding does not trigger rework
- **WHEN** installed independent review reports a fingerprinted non-causal observation beside an otherwise complete task
- **THEN** controller-derived outcome does not schedule source rework and the observation remains in the Dossier

#### Scenario: Review rework invalidates an affected slice
- **WHEN** a blocking causal finding is fixed and the accepted manifest change intersects one prior obligation but not another
- **THEN** installed replay schedules only the intersecting obligation and required re-review, preserving the disjoint proof with an explicit reuse basis

#### Scenario: Absolute budget is exhausted
- **WHEN** recorded assurance and rework executions consume an obligation or aggregate allowance
- **THEN** no workflow route projects another execution beyond that allowance and the exact unmet obligation reaches incomplete finalization

#### Scenario: Installed rework ceiling is uniquely derived
- **WHEN** installed budget journeys exercise `U = 0`, a positive `U` below each profile cap, `U` equal to each cap, and `U` above each cap
- **THEN** replay derives `rework_ceiling` as exactly `min(profile_rework_cap, U)` in every case

#### Scenario: Installed finding-bound rework consumes reserved authority
- **WHEN** one installed review result contains multiple current blocking causal findings and the governing review obligation has one unused canonical retry unit
- **THEN** the controller materializes one grouped finding-bound rework obligation, creates no new budget, and its execution consumes exactly one reserved retry unit and one rework-ceiling unit

#### Scenario: Installed rework budget replays exactly
- **WHEN** an installed controller restarts after rework reservation or consumption
- **THEN** it derives the same reservation set, `U`, `rework_ceiling`, and used counts before projecting another action

#### Scenario: Same-contract replacement preserves budgets exactly
- **WHEN** an installed impact-gap journey derives a replacement plan under the same effective contract
- **THEN** replay preserves the original reservation set, `U`, every verification, review, source-rework, and total-action ceiling, and every consumed counter exactly

#### Scenario: Persisted and read-only reuse have distinct charges
- **WHEN** installed journeys apply one waiver, finding disposition, prerequisite refresh, persisted reuse decision, and read-only reuse derivation
- **THEN** each persisted mutation consumes exactly one total-action unit and no verification, review, or source-rework unit, while the read-only derivation consumes no unit

#### Scenario: Every exact product bound is admissible
- **WHEN** installed boundary tests submit otherwise-valid values at exactly 4,096 snapshot paths, 12,288 index stage entries, 2 MiB of index output, 128 ownership claims, 4,096 current manifest entries, 128 impact entries, 64 obligations, 64 findings, 64 evidence items, 256 effective-contract actions, 64 KiB of action payload, and 8 KiB in one text field
- **THEN** each value passes its collection or byte-bound check and remains subject to all other current validation rules

#### Scenario: Every first-excess product value fails atomically
- **WHEN** installed boundary tests submit otherwise-valid values at 4,097 snapshot paths, 12,289 index stage entries, 2 MiB plus one byte of index output, 129 ownership claims, 4,097 current manifest entries, 65 obligations, 65 findings, 65 evidence items, 257 effective-contract actions, 64 KiB plus one byte of action payload, or 8 KiB plus one byte in one text field
- **THEN** the responsible operation rejects the complete value without truncation, a partial record, omitted coverage, or excess action authority

#### Scenario: First-excess impact uses conservative assurance
- **WHEN** an installed impact closure would require a 129th bounded impact entry
- **THEN** the report records bounded overflow without truncation, normalizes confidence to unknown, and derives the conservative assurance plan

#### Scenario: Candidate splits canonical obligations
- **WHEN** a candidate workflow or installed plan splits one required member, boundary evidence contract, documentation check, manual-evidence check, or independent-review check into redundant obligations
- **THEN** validation rejects the non-canonical grouping without increasing any allowance or action ceiling

#### Scenario: Staged content changes under a stable worktree
- **WHEN** an installed journey replaces a staged blob while worktree bytes and porcelain status remain stable
- **THEN** snapshot identity changes and stale review or verification binding is rejected
