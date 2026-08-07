# adaptive-assurance-planning Specification

## Purpose
TBD - created by archiving change introduce-task-scoped-adaptive-assurance. Update Purpose after archive.
## Requirements
### Requirement: Assurance planning derives a canonical obligation plan
For every effective contract, the controller SHALL validate and canonicalize one `dev-flow-assurance-plan/0.4.0` from the selected workflow and its embedded `dev-flow-assurance-policy/0.4.0`, stable acceptance-criterion IDs, the complete roll-forward task change manifest, declared affected behavior and impact closure, governing inputs, risk classifications, current waivers, and absolute product bounds. `lite` SHALL derive the same plan shape from its bounded impact evidence. The plan SHALL contain a controller-derived plan identity and digest; a canonical impact manifest covering affected repositories, paths, symbols or stable labels, cross-repository edges, and confidence; stable obligation IDs and fingerprints; deterministic ordering; and explicit aggregate budgets.

Each obligation SHALL declare exactly one supported kind from `repository-check`, `integration-check`, `documentation-check`, `independent-review`, or `manual-evidence`; one or more current criterion IDs; exact member and task-change slice; impact closure; prerequisites; evidence contract; completion rule; invalidation and reuse rule; driver requirement; and execution budget class and allowance. Every effective criterion and every still-material roll-forward manifest entry SHALL be covered by at least one required obligation or one current criterion waiver whose authority permits that omission. The controller SHALL group obligations canonically as at most one repository check per required member, one integration check per distinct evidence contract over a sorted set of required canonical edges, and at most one documentation, manual-evidence, and independent-review obligation per plan; each grouped obligation SHALL bind the sorted union of applicable criteria, slices, and edges. The controller SHALL derive canonical IDs, digests, currentness, profile floors, criterion and manifest coverage, and budget validity and SHALL reject caller-supplied values that contradict those derivations. Missing coverage, cyclic prerequisites, unknown members or criteria, unbounded payloads, non-positive required allowances, non-canonical splitting, or a plan that exceeds product and workflow ceilings SHALL fail before assurance dispatch.

The official policy SHALL use the closed confidence vocabulary `source-confirmed` and `unknown`; driver values such as degraded, partial, stale, unavailable, or unconfirmed SHALL normalize to `unknown`. It SHALL use the closed review-trigger IDs `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, and `protocol`. Trigger precedence SHALL be monotonic: unknown-impact expansion, mandatory risk triggers, the selected profile floor, and criterion/manifest coverage are unioned in that order, and no later rule may remove an earlier obligation. The six official profile floors and per-obligation execution allowance `A` SHALL be:

| Profile | Source-confirmed minimum assurance floor | Independent review | `A` |
| --- | --- | --- | --- |
| `lite` | One repository check per affected member and one integration check per distinct affected-edge evidence contract; other obligation kinds only when criteria require them | Closed risk triggers only | 2 |
| `feature` | The `lite` floor plus one documentation check when a criterion covers public behavior, API, configuration, or user documentation | Closed risk triggers only | 2 |
| `bugfix` | The `lite` floor plus a regression evidence contract proving pre-fix reproduction or equivalent baseline evidence and post-fix success | Closed risk triggers only | 2 |
| `investigation` | One manual-evidence obligation covering every investigation conclusion; repository or integration checks only for conclusions requiring executable reproduction; no fabricated source obligation | Closed risk triggers only | 2 |
| `refactor` | One repository check per affected member covering every declared invariant and one integration check per distinct affected-edge evidence contract | Closed risk triggers only | 2 |
| `full` | One repository check per task member, one integration check per distinct declared-edge evidence contract, one documentation check, and criterion-required manual evidence | Always required | 3 |

A custom workflow SHALL select one official base profile and MAY strengthen its floor, require review, or reduce allowances, but SHALL NOT remove a base obligation, weaken an unknown-impact or risk-trigger result, raise a product maximum, or introduce a free-form trigger.

One impact report SHALL contain at most 128 bounded impact entries and one assurance plan SHALL contain at most 64 obligations. Neither limit permits truncation. When a source-confirmed closure would require more than 128 report entries, the report SHALL record bounded overflow and the controller SHALL normalize the affected closure to `unknown` and derive conservative assurance. A plan that cannot express its canonical conservative obligations within 64 entries SHALL fail validation. Every action payload remains subject to the shared 64 KiB payload and 8 KiB per-text limits, and every effective contract remains subject to the 256-action ceiling defined by budget governance.

#### Scenario: Planning covers every effective criterion
- **WHEN** current impact evidence and risk classification map every unwaived criterion to one or more well-formed obligations
- **THEN** the controller derives one canonical plan whose obligation and criterion coverage are deterministic across replay

#### Scenario: One criterion has no assurance coverage
- **WHEN** a candidate plan omits an effective criterion that has no current criterion waiver
- **THEN** plan validation rejects it and assurance dispatch remains unavailable

#### Scenario: Lite derives a focused plan
- **WHEN** a `lite` task has bounded current impact evidence for a local low-risk change
- **THEN** the controller derives the same canonical assurance-plan schema used by the other official workflows with the obligations and ceilings required by the `lite` profile

#### Scenario: Governing plan input changes
- **WHEN** the effective contract, task change manifest, impact evidence, risk classification, workflow profile, or governing resource changes
- **THEN** the earlier plan ceases to govern new dispatch and the controller requires a newly validated canonical plan

#### Scenario: Controller restarts after planning
- **WHEN** replay sees the same contract, task capsule, impact evidence, policy authorities, and governing inputs
- **THEN** it derives the same plan digest, obligation fingerprints, dependency order, and absolute ceilings

#### Scenario: Candidate splits canonical assurance redundantly
- **WHEN** a candidate plan creates multiple repository checks for one member or multiple integration checks for the same edge evidence contract
- **THEN** plan validation rejects the non-canonical split rather than increasing actions or budgets

#### Scenario: Impact report exceeds its entry bound
- **WHEN** a source-confirmed impact closure would require a 129th bounded entry
- **THEN** the report is not truncated or treated as focused; it records overflow and the controller normalizes that closure to unknown conservative assurance

#### Scenario: Plan exceeds its obligation bound
- **WHEN** canonical grouping still requires a 65th obligation
- **THEN** plan validation fails before dispatch without omitting or merging obligations that have different evidence contracts

### Requirement: Member, integration, and review assurance are required only by impact and risk
The controller SHALL derive required assurance dimensions from accepted impact closure, criterion coverage, the normative official profile matrix, and the closed risk-trigger set. Repository-check obligations SHALL name exactly the members required by the profile and accepted closure. Integration-check obligations SHALL be required for the canonical edges required by the profile and whenever the closure reaches a cross-member contract or a protocol, persistence, installation, or other already declared integration edge. Independent-review obligations SHALL be required when the profile is `full` or the current impact evidence activates `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, or `protocol`. Documentation and manual-evidence obligations SHALL follow the exact selected profile floor and criterion rules.

A member, integration, review, documentation, or manual dimension that is not required SHALL be recorded with its derivation rule and `not-required` status in the plan and Delivery Dossier; it SHALL NOT receive fabricated passing evidence and SHALL NOT be projected as an action. Agent preference or a free-form low-risk label SHALL NOT remove a policy-required obligation. Current impact evidence that is missing, stale, internally inconsistent, degraded, partial, unavailable, unconfirmed, or not source-confirmed SHALL normalize to `unknown`. Unknown impact SHALL fail closed for every profile to repository checks for every task member, integration checks for every declared or applicable canonical edge, one independent-review obligation, and any documentation or manual obligation required by criteria or the selected profile. A risk trigger or unknown classification may only expand assurance; it SHALL NOT be downgraded by path count, workflow preference, or a caller-supplied confidence score.

#### Scenario: Low-risk change is local to one member
- **WHEN** current source-confirmed impact evidence closes all changed behavior and criteria to one repository and no integration or review policy trigger applies
- **THEN** the plan requires the focused repository checks and records the other members, integration, and independent review as not required with rule identifiers

#### Scenario: Change crosses a repository contract
- **WHEN** one task-owned change affects a producer in one member and a consumer contract in another
- **THEN** the plan includes the required member checks and an integration-check obligation spanning the declared cross-repository edge

#### Scenario: High-risk trigger applies
- **WHEN** current impact evidence activates any closed trigger ID from `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, or `protocol`
- **THEN** the plan includes an independent-review obligation even if the changed path count is small

#### Scenario: Impact closure is unknown
- **WHEN** impact evidence is unavailable or cannot prove a bounded dependency closure for one task-owned path
- **THEN** the plan expands to the conservative member, integration, and independent-review obligation set and does not classify the change as locally closed

#### Scenario: Optional dimension is omitted without a rule basis
- **WHEN** a candidate plan omits integration or independent review but cannot identify the current policy rule and impact evidence that make it unnecessary
- **THEN** plan validation rejects the omission rather than treating the missing dimension as passed or skipped

#### Scenario: Lite remains focused
- **WHEN** a `lite` task has source-confirmed local impact in one member and no closed risk trigger
- **THEN** it receives one grouped repository check for that member and no integration or independent-review action

#### Scenario: Lite activates a risk trigger
- **WHEN** the same `lite` task reaches path-safety behavior
- **THEN** its focused checks are unioned with one independent-review obligation

#### Scenario: Feature changes public behavior
- **WHEN** a `feature` task has source-confirmed local user-visible behavior and documentation criteria with no review trigger
- **THEN** it receives the affected-member repository check and one documentation check without profile-only independent review

#### Scenario: Feature impact is unknown
- **WHEN** a `feature` task cannot source-confirm its impact closure
- **THEN** it receives every-member repository checks, every declared or applicable integration check, and independent review

#### Scenario: Bugfix has bounded regression evidence
- **WHEN** a `bugfix` task has source-confirmed local impact and a valid pre-fix reproduction or equivalent baseline
- **THEN** its member check requires that regression contract and post-fix success without profile-only review

#### Scenario: Bugfix reaches persistence or replay
- **WHEN** a `bugfix` task affects persistence or replay
- **THEN** the regression floor is unioned with the required integration scope and independent review

#### Scenario: Investigation has bounded conclusions
- **WHEN** an `investigation` task has source-confirmed conclusions that require no executable reproduction
- **THEN** one manual-evidence obligation covers every conclusion and no implementation, repository-check, integration-check, or profile-only review action is fabricated

#### Scenario: Investigation cannot bound impact
- **WHEN** an `investigation` task's material conclusion depends on unknown impact
- **THEN** its manual-evidence floor is unioned with every-member checks, applicable integration checks, and independent review

#### Scenario: Refactor preserves local invariants
- **WHEN** a `refactor` task has source-confirmed impact in one member and all declared invariants are local
- **THEN** one grouped member check covers every invariant and no profile-only independent review is required

#### Scenario: Refactor crosses a repository contract
- **WHEN** a `refactor` task affects a declared cross-repository contract
- **THEN** the affected-member and edge checks are unioned with independent review through the cross-repository-contract trigger

#### Scenario: Full uses its strongest floor
- **WHEN** a `full` task has source-confirmed impact limited to one member
- **THEN** the plan still includes one repository check per task member, integration checks covering every declared canonical edge grouped by evidence contract, one documentation check, and independent review with per-obligation cap three

#### Scenario: Full impact is unknown
- **WHEN** a `full` task cannot source-confirm its closure
- **THEN** the same strongest floor remains in force and any criterion-required manual evidence is added without duplicating obligations

### Requirement: Assurance dispatch projects one outstanding obligation deterministically
The controller SHALL derive obligation state from the current plan, current or reusable evidence, prerequisites, current waivers, absolute budget consumption, and current controller-governed review-finding status. Obligation state SHALL use an exact bounded vocabulary covering `required`, `blocked`, `outstanding`, `satisfied`, `reused`, `not-required`, `waived`, and `exhausted`. When multiple obligations are outstanding and their prerequisites are current, dispatch SHALL project exactly one action using the plan's canonical dependency and priority order. A projected action binding SHALL include the plan and obligation fingerprints, effective contract, task-change slice, impact closure, governing inputs, current evidence references, and applicable execution counters. Completing or failing the action SHALL append one record and return control to deterministic dispatch.

The planner SHALL consume current structured finding, derived review-outcome, impact-gap, and finding-disposition identities from the review-finding governance capability as authoritative routing inputs; it SHALL NOT reinterpret free-form reviewer summaries or redefine finding and disposition semantics. A current governance result that requires source rework SHALL create an exact finding-bound rework obligation with permitted source scope and budget class. A `triage-required` result SHALL project only the bounded causal prerequisite refresh permitted by the plan, and an impact gap SHALL invalidate the current plan and reenter impact planning under the same contract and counters before any source rework. When a current finding disposition changes the governed review status without a source change, dispatch SHALL recompute the affected review obligation without invalidating unrelated evidence. When no required obligation remains outstanding, dispatch SHALL project finalization rather than another assurance action.

#### Scenario: Two obligations are ready
- **WHEN** two outstanding obligations have current prerequisites
- **THEN** repeated projections select the same single obligation according to canonical plan order and do not mutate task state

#### Scenario: Obligation prerequisite is stale
- **WHEN** the next ordered obligation depends on stale impact evidence or governing input
- **THEN** dispatch marks it blocked and projects the deterministic action required to refresh that prerequisite before assurance execution

#### Scenario: Governed review status requires rework
- **WHEN** review-finding governance supplies a current controller-derived rework requirement for exact finding fingerprints
- **THEN** dispatch creates the bounded finding-linked rework obligation and uses the source scope and routing status supplied by that authority

#### Scenario: Governed disposition changes review status
- **WHEN** review-finding governance records a current finding disposition that changes whether a review obligation is satisfied or requires rework
- **THEN** assurance dispatch consumes the new governed status and preserves unrelated obligation evidence

#### Scenario: Review requires causal triage
- **WHEN** review-finding governance supplies a current `triage-required` result
- **THEN** dispatch keeps review outstanding and projects the bounded causal refresh prerequisite without authorizing source rework

#### Scenario: Review proves an impact gap
- **WHEN** review-finding governance proves an affected relation outside the current plan closure
- **THEN** dispatch invalidates the plan and reenters impact planning under the same contract and remaining counters

#### Scenario: All obligations are discharged
- **WHEN** every required obligation is satisfied, validly reused, or validly waived under its authoritative governance rules
- **THEN** the controller projects the appropriate Delivery Dossier finalization action without another repository check, integration check, or review

### Requirement: Evidence invalidation and reuse are obligation-slice aware
Every assurance result SHALL bind its effective contract, obligation ID and fingerprint, originating plan, covered criterion IDs, exact member and task-change slice, declared impact closure, governing inputs, commands or manual-evidence references, driver and environment limitations, and observed assurance snapshot. One execution SHALL contain at most 64 canonical evidence items, subject also to the shared payload and text byte limits; a 65th item SHALL reject the result without truncation or a partial record. After a later accepted source or planning change under the same contract, the controller SHALL compare the new task-change slice, criterion semantics, impact closure, obligation contract, and governing-input fingerprints with each prior result. It SHALL derive freshness, invalidation, and reuse; an agent payload SHALL NOT declare its own evidence current.

The controller SHALL reuse a prior result for an obligation in a replacement current plan only when the effective contract is unchanged, the obligation fingerprint and criterion semantics are equivalent, the changed slice is disjoint from the bound impact closure, all governing inputs and driver constraints remain current, and every prerequisite remains satisfied. It SHALL record a reuse derivation that references the original evidence and exact disjointness basis; reuse SHALL NOT create a new execution. Any intersection SHALL invalidate that obligation and its dependants without invalidating obligations whose declared closures are provably disjoint. An integration result SHALL be invalidated by a change in any member or contract edge in its declared closure. A changed governing resource, missing closure evidence, ambiguous intersection, or unknown impact SHALL invalidate conservatively. Historical results SHALL remain immutable and visible whether current, reused, stale, or superseded.

#### Scenario: Later change is disjoint from focused evidence
- **WHEN** a later task-owned change is outside a satisfied repository obligation's impact closure and its contract, criteria, governing inputs, driver constraints, and obligation fingerprint remain current
- **THEN** the controller reuses the prior result and does not schedule another execution for that obligation

#### Scenario: Later change intersects one obligation
- **WHEN** a rework source slice intersects one repository-check closure but is provably disjoint from two other satisfied obligations
- **THEN** only the intersecting obligation and its dependants become outstanding while the other two results remain reusable

#### Scenario: Integration closure changes
- **WHEN** a source change affects any member or cross-member edge covered by a satisfied integration obligation
- **THEN** the integration evidence becomes stale and dispatch requires a new integration execution if that obligation remains required

#### Scenario: Governing resource changes
- **WHEN** a command definition, assurance guidance, accepted impact resource, or other governing input bound to evidence changes
- **THEN** that evidence and its dependent obligations become stale even when the task-owned source paths are unchanged

#### Scenario: Intersection cannot be proven
- **WHEN** the controller lacks current evidence to prove that a later source slice is disjoint from an obligation's closure
- **THEN** it invalidates the result conservatively and records the missing or ambiguous closure as the reason

#### Scenario: Contract is revised
- **WHEN** a new effective contract and assurance plan replace the prior contract
- **THEN** prior-contract evidence remains historical and cannot satisfy current obligations through slice reuse

#### Scenario: Execution exceeds its evidence bound
- **WHEN** an assurance result supplies a 65th evidence item
- **THEN** apply rejects the complete execution without truncating evidence, consuming an execution unit, or appending a partial record

### Requirement: Assurance budgets are absolute per-contract execution ceilings
Each required assurance obligation SHALL begin with one execution unit and SHALL have the selected profile's per-obligation cap `A`: two for `lite`, `feature`, `bugfix`, `investigation`, and `refactor`, and three for `full`. Every dynamically materialized source-rework obligation SHALL have allowance one. Every obligation SHALL map to exactly one execution budget class, and every recorded execution SHALL consume one unit from its obligation allowance, applicable aggregate class ceiling, and total-action ceiling whether it passes, fails, is unavailable, or is later superseded. Evidence reuse and a controller-derived `not-required` classification SHALL NOT be counted as new assurance executions. A waiver, finding disposition, prerequisite-refresh, or separately persisted evidence-reuse mutation authorized inside the assurance region SHALL consume one total-action unit exactly once while consuming no verification, review, or source-rework execution unit; a read-only reuse derivation that appends no mutation consumes none.

The controller SHALL derive aggregate ceilings rather than accept arbitrary totals from an agent. Let `V` be the number of required non-review assurance obligations and `R` the number of required independent-review obligations. Let the initial plan's budget-reservation obligation set be the conservative canonical closure already required for the effective contract. For each obligation `o` in that set, `retry_units(o)` SHALL equal `max(allowance(o) - 1, 0)` when its evidence contract declares a source-rework route and zero otherwise. Let `U = Σ retry_units(o)` over that canonical set. The official ceilings SHALL be:

| Profile | `verification_ceiling` | `review_ceiling` | `rework_ceiling` |
| --- | --- | --- | --- |
| `lite`, `investigation` | `min(A × V, V + 1)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(1, U)` |
| `feature`, `bugfix`, `refactor` | `min(A × V, V + 2)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(2, U)` |
| `full` | `min(A × V, V + 4)` | `min(A × R, R + 2)` | `min(4, U)` |

When `U = 0`, `rework_ceiling` SHALL be zero. A failed assurance obligation SHALL materialize source rework only against its next unused canonical retry unit. When one review result contains one or more current blocking `introduced` or in-closure `affected` findings, the controller SHALL group all such current finding fingerprints into one finding-bound source-rework obligation against the governing review obligation's next unused retry unit. Materializing that obligation SHALL NOT increase or consume the ceiling; committing its source-rework execution SHALL consume the retry unit, one rework-ceiling unit, and one total-action unit. If the governing obligation has no unused reserved retry unit, dispatch SHALL NOT materialize source rework and SHALL follow deterministic incomplete finalization.

The initial valid plan SHALL fix the canonical budget-reservation set, `U`, every class ceiling, and consumed units for the effective contract. A replacement plan under the same contract SHALL inherit those values and MAY redistribute only remaining authority; it SHALL NOT add retry units, recompute any ceiling upward or downward, or reset consumption when impact, findings, or obligations change. An accepted contract revision SHALL derive a new canonical budget set for the new contract digest while preserving prior values historically.

`total_action_ceiling` SHALL equal the validated workflow's reachable fixed mutations under the current contract plus the three class ceilings, the exact product-bounded reserve for reachable unique waiver, disposition, persisted-reuse, and prerequisite-refresh subjects, and exactly one non-cancelled Dossier finalization; it SHALL NOT exceed 256. Since every permitted review execution can produce a distinct set of at most 64 findings, the initial conservative finding-disposition subject reserve SHALL equal `review_ceiling × 64`. The initial plan SHALL reserve one prerequisite-refresh subject for each conservative obligation that can acquire prerequisites, fingerprinted with that dependent reservation and its complete conservative prerequisite-reservation set. A same-contract replacement SHALL inherit this subject before validating its expanded obligation graph, and every new prerequisite SHALL be covered by the inherited set; it SHALL NOT recompute the total-action ceiling from the replacement's current prerequisite edges. A governance subject SHALL be unique by `(contract digest, mutation kind, subject fingerprint)` and SHALL reserve and consume at most one total-action unit: criterion or assurance fingerprint for waiver, finding fingerprint for disposition, obligation fingerprint for persisted reuse, and prerequisite fingerprint for refresh. The controller SHALL reject a second current-contract disposition for the same finding fingerprint before appending a record. It SHALL derive the reachable subject set from the conservative canonical criterion, obligation, finding, and prerequisite bounds rather than accept a caller-supplied reserve. A plan whose required first executions and reachable fixed mutations cannot fit these formulas and the product ceiling SHALL fail before dispatch rather than silently drop assurance.

Dispatch SHALL NOT project an executable obligation or rework action when its per-obligation allowance or any applicable aggregate ceiling has no remaining unit. No success edge, failure edge, rework route, review route, restart, action-template cycle, or transition between obligations SHALL create or reset allowance under one effective contract digest. Exhaustion before all required obligations are discharged SHALL route deterministically to `INCOMPLETE` finalization with the exact exhausted ceilings and unmet obligations. An accepted contract revision SHALL establish a new plan and explicit ceilings for the new contract digest while retaining every prior execution and counter historically. Workflow and plan validation SHALL reject any route whose budget consumption is ambiguous or whose executions can exceed a declared ceiling.

#### Scenario: Successful executions consume budget
- **WHEN** two verification-class obligations each execute successfully under one contract
- **THEN** both executions consume their per-obligation units, two aggregate verification units, and two total-action units

#### Scenario: Review rework returns to verification
- **WHEN** review-driven source rework invalidates an earlier verification and dispatch requires another verification execution
- **THEN** both the earlier and later executions count against the same absolute verification ceiling and the route cannot exceed that ceiling

#### Scenario: Reused evidence avoids execution
- **WHEN** a current obligation is satisfied by valid slice-aware reuse
- **THEN** dispatch records or reports the reuse basis without consuming another obligation, verification, review, or rework execution unit, and charges one total-action unit only when a separate reuse mutation is persisted

#### Scenario: Required action has no allowance
- **WHEN** an outstanding obligation requires an execution whose per-obligation or aggregate remaining count is zero
- **THEN** dispatch projects incomplete finalization and identifies the exhausted counter rather than projecting the action

#### Scenario: Controller restarts after attempts
- **WHEN** the controller replays passing, failing, unavailable, and superseded executions under one contract
- **THEN** it reconstructs identical used and remaining counters and grants no additional allowance

#### Scenario: Contract revision creates a new budget set
- **WHEN** an authorized next contract is accepted and a valid replacement plan is derived
- **THEN** the new contract receives its declared bounded allowances while every prior-contract counter remains immutable history

#### Scenario: Governance and reuse mutations are counted exactly
- **WHEN** a waiver, finding disposition, prerequisite refresh, or persisted reuse decision commits in the assurance region
- **THEN** it consumes one total-action unit and no verification, review, or source-rework unit, while an unpersisted read-only reuse derivation consumes none

#### Scenario: Replacement plan discovers more impact
- **WHEN** an impact gap adds obligations under the same effective contract
- **THEN** the replacement plan preserves the original canonical budget-reservation set, `U`, every class ceiling, and consumed count and uses only the remaining recorded authority

#### Scenario: No obligation permits source rework
- **WHEN** the canonical budget-reservation set contains no obligation whose evidence contract declares a source-rework route
- **THEN** `U` and `rework_ceiling` are both zero

#### Scenario: Retry units are below the profile cap
- **WHEN** a `feature` plan has exactly one canonical retry unit across all source-rework-capable obligations
- **THEN** `U` is one and `rework_ceiling` is exactly one

#### Scenario: Retry units meet or exceed the profile cap
- **WHEN** a `feature` plan has two or more canonical retry units across its source-rework-capable obligations
- **THEN** `rework_ceiling` is exactly two

#### Scenario: Review materializes finding-bound rework
- **WHEN** one review result contains multiple current blocking causal findings and its governing review obligation has an unused canonical retry unit
- **THEN** the controller groups the current finding fingerprints into one source-rework obligation whose execution consumes exactly that retry unit and one rework-ceiling unit

#### Scenario: Rework ceiling replays and survives same-contract replacement
- **WHEN** the controller restarts or a same-contract replacement plan is derived after retry and rework units were reserved or consumed
- **THEN** replay preserves the original canonical budget-reservation set, `U`, `rework_ceiling`, and consumed counts without recomputation, expansion, or reset

#### Scenario: Contract route exceeds the product action ceiling
- **WHEN** fixed mutations, required first executions, bounded retries, reachable governance subjects, and finalization would require more than 256 actions under one effective contract
- **THEN** plan validation fails before dispatch and does not omit obligations or authorize a 257th action

### Requirement: Projections expose obligations, budgets, and a finite maximum remaining action count
Every non-terminal `dev-flow-agent/0.4.0` projection and read-only task view SHALL expose a compact assurance summary containing the current plan identity and profile, impact confidence, every required obligation and its status, current and reused evidence references, `not-required`, waived, blocked, and exhausted reasons, the current obligation when one is projected, and used and remaining per-obligation and aggregate budget counts. It SHALL also expose a controller-derived `maximum_remaining_actions` for the current effective contract and plan. The maximum SHALL be a sound finite upper bound that includes the current projected mutation and every workflow action that can still be authorized before `DONE` or `INCOMPLETE` under current prerequisite states and remaining ceilings. It SHALL exclude hypothetical future contract revisions and user-selected cancellation, each of which produces a replacement bound when accepted.

The controller SHALL calculate the maximum from the validated obligation dependency graph, deterministic dispatch rules, remaining per-obligation allowances, rework allowances, governance prerequisites, and total-action ceiling. Repeated read-only projections of unchanged state SHALL return the same value. The maximum SHALL never exceed the plan's remaining total-action authority plus any explicitly modeled terminal mutation, and no subsequent route under the same governing plan state SHALL authorize more actions than the earlier bound. A workflow or plan for which the controller cannot prove a finite maximum SHALL fail validation rather than project an open-ended route. Conflict responses, restart projections, finalization, and the Delivery Dossier SHALL use the same replay-derived counters and maximum calculation.

#### Scenario: Projection shows a focused remaining route
- **WHEN** one repository check and finalization are the only remaining actions
- **THEN** the projection identifies the outstanding obligation, its remaining allowance, and a maximum remaining action count that covers those two actions

#### Scenario: Failure and rework remain possible
- **WHEN** the current obligation has a failure route and remaining ceilings permit one rework plus one repeated assurance execution
- **THEN** the projected maximum includes that bounded route and cannot be exceeded by taking it

#### Scenario: Projection is repeated without mutation
- **WHEN** callers invoke `next` or `show` repeatedly against unchanged task state
- **THEN** every response reports identical obligation status, counters, and maximum remaining action count without consuming allowance

#### Scenario: Bound cannot be proven
- **WHEN** an obligation dependency, governance prerequisite, or workflow route can repeat without consuming a finite applicable ceiling
- **THEN** validation rejects the plan or workflow before that route can be projected

#### Scenario: Task reaches terminal state
- **WHEN** the task commits `DONE` or `INCOMPLETE` finalization
- **THEN** its projection reports no current action, zero maximum remaining actions, and the final obligation and budget summary

### Requirement: Completion authority is explainable and controller-derived
The controller SHALL derive completion readiness from the current task change capsule, effective contract coverage, validated assurance plan, current obligation states, current waivers, unresolved ambient drift, absolute budget state, and the current review and disposition status supplied by review-finding governance. An agent-supplied aggregate pass, approval, skip, or outcome SHALL NOT override those inputs. `DONE` SHALL require no unresolved ambient drift, `triage-required` review, or impact gap; every effective criterion proven or validly waived; every required obligation satisfied or validly reused or waived by its exact permitted authority; every required review obligation satisfied under current finding governance; and no stale governing input. When a required obligation is failed, missing, stale, blocked, or exhausted and cannot be completed within the remaining ceilings, the controller SHALL select `INCOMPLETE` finalization.

The projection, task view, and Delivery Dossier SHALL expose the rule basis for every required and not-required assurance dimension, the evidence or authority satisfying each obligation, every reuse and invalidation comparison, current governed finding and disposition references, exhausted counters, unmet criteria, and the exact facts supporting the derived terminal outcome. An optional dimension absent by a valid plan rule SHALL not block completion; its omission SHALL remain explicit and SHALL not be reported as passing evidence.

#### Scenario: Focused obligations establish completion
- **WHEN** a low-risk local task has no required integration or review obligation, its required focused checks are current, every criterion is covered, and no ambient drift remains
- **THEN** the controller SHALL derive `DONE` eligibility and report the rules that made integration and review not required

#### Scenario: Agent claims success with an outstanding obligation
- **WHEN** an action payload reports aggregate success while one current required obligation is unsatisfied
- **THEN** the controller ignores or rejects the contradictory outcome and withholds successful finalization

#### Scenario: Governed finding state changes
- **WHEN** review-finding governance records a new current outcome or disposition for a finding referenced by the plan
- **THEN** the controller recomputes obligation readiness and completion from that governed identity without interpreting reviewer prose

#### Scenario: Budget exhausts with unmet assurance
- **WHEN** an absolute ceiling is exhausted while one or more required obligations remain unsatisfied
- **THEN** the controller derives `INCOMPLETE`, and the Dossier names the unmet obligations, criteria, findings, and exhausted counters

#### Scenario: Non-required check has no evidence
- **WHEN** the plan validly classifies a member, integration, or review dimension as not required
- **THEN** completion evaluates the recorded rule basis and never fabricates a passing result for that dimension
