# personal-delivery-workflows Specification

## Purpose
TBD - created by archiving change complete-personal-delivery. Update Purpose after archive.
## Requirements
### Requirement: The product ships an official personal workflow family
The product SHALL provide built-in `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full` workflows using the current `dev-flow-workflow/0.3.0` language. Each workflow SHALL begin with bounded read-only preflight over the task's exact repository set and task-owned change capsule, remain within one task, one current action, and one Codex executor, declare the artifacts and assurance policy it can produce, and finalize non-cancelled delivery through the current aggregate Delivery Dossier. Official workflow definitions SHALL declare deterministic delivery phases, obligation-capable action templates, the versioned closed `dev-flow-assurance-policy/0.3.0`, and absolute budget ceilings. After impact and task-change evidence are current, the controller SHALL project only the actions needed to discharge the current assurance plan's outstanding obligations.

The official assurance policy SHALL use the exact following profile matrix. `A` is the per-obligation execution allowance.

| Profile | Source-confirmed minimum assurance floor | Independent review | `A` |
| --- | --- | --- | --- |
| `lite` | One repository check per affected member and one integration check per distinct affected-boundary evidence contract; documentation or manual evidence only when required by current criteria | Only when a closed risk trigger applies | 2 |
| `feature` | The `lite` floor plus one documentation check when a current criterion covers public behavior, API, configuration, or user documentation | Only when a closed risk trigger applies | 2 |
| `bugfix` | The `lite` floor plus one regression evidence contract proving pre-fix reproduction or an equivalent baseline and post-fix success | Only when a closed risk trigger applies | 2 |
| `investigation` | One manual-evidence obligation covering every conclusion; repository or integration checks only for conclusions requiring executable reproduction; no fabricated implementation or source obligation | Only when a closed risk trigger applies | 2 |
| `refactor` | One repository check per affected member covering every declared invariant and one integration check per distinct affected-boundary evidence contract | Only when a closed risk trigger applies | 2 |
| `full` | One repository check per task member, one integration check per distinct declared-boundary evidence contract, one documentation check, and every necessary criterion-required manual-evidence check | Always required | 3 |

The policy SHALL use only the review-trigger IDs `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, and `protocol`. Only current `source-confirmed` impact MAY produce a focused obligation set. Missing, stale, degraded, partial, unavailable, unconfirmed, internally inconsistent, or otherwise non-source-confirmed impact SHALL normalize to `unknown` and expand to repository checks for every task member, integration checks for every declared or applicable canonical boundary, independent review, and any documentation or manual evidence required by the selected profile or current criteria. A custom workflow SHALL select one official base profile and MAY strengthen its floor, require review, reduce allowances, or reduce aggregate ceilings; it SHALL NOT remove a base obligation, weaken unknown-impact or risk-trigger expansion, raise a product maximum, or introduce a free-form trigger.

Cancellation availability SHALL be declared explicitly by workflow stage. Official workflows SHALL make cancellation available from the normal majority of non-terminal stages while allowing a stage to omit cancellation when its product semantics require completion or another operator action. Repository topology SHALL be independently selectable as an exact set of one to eight user-prepared local Git worktrees. Across active tasks, prepared linked worktrees that share one Git common directory MAY be used concurrently only when their canonical roots and worktree-specific Git administrative directories are distinct. A repeated canonical root or worktree-specific Git administrative directory across active tasks SHALL be rejected, and one task's repository set SHALL continue to reject duplicate Git-common-directory members. Workflow depth SHALL NOT imply repository count, controller-managed workspaces, parallel executors, external delivery effects, or a fixed count of verification and review actions.

#### Scenario: User selects each official workflow
- **WHEN** a caller starts a task with any official workflow ID and one or more valid repository roots
- **THEN** the controller validates the packaged current-version workflow definition, pins its identity and exact repository set, and projects its preflight action using the same current product version

#### Scenario: Official workflow uses multiple repositories
- **WHEN** a caller starts any official workflow with two valid user-prepared worktrees
- **THEN** that workflow retains one task, one current action, one absolute assurance budget set, and one Codex executor while its task-change manifest, artifacts, obligations, and final dossier bind the complete repository set

#### Scenario: Separate linked worktrees support concurrent tasks
- **WHEN** two active tasks use prepared linked worktrees with distinct canonical roots and worktree-specific Git administrative directories but the same Git common directory
- **THEN** both task admissions may succeed with independent member leases

#### Scenario: Active tasks request the same worktree identity
- **WHEN** a new task requests a canonical root or worktree-specific Git administrative directory already leased by another active task
- **THEN** admission rejects the complete new repository set and identifies the owning task and member

#### Scenario: One task repeats a Git common directory
- **WHEN** one requested repository set contains two members whose canonical roots and worktree-specific Git administrative directories differ but whose Git common directory is the same
- **THEN** repository-set validation rejects the complete task because duplicate common-directory members are not valid inside one task

#### Scenario: Investigation has no implementation
- **WHEN** an investigation task reaches its delivery path without a code change
- **THEN** its workflow records investigation evidence and projects only the assurance obligations required by that investigation without requiring a fabricated implementation artifact

#### Scenario: Official policy value drifts
- **WHEN** an official or custom workflow supplies an assurance-policy schema, profile floor, review trigger, allowance, or maximum that conflicts with `dev-flow-assurance-policy/0.3.0`
- **THEN** workflow validation rejects the definition before task creation or assurance dispatch

#### Scenario: A stage declares cancellation
- **WHEN** the current non-terminal stage declares a cancellation contract
- **THEN** the controller may cancel through the declared complete-snapshot, action-binding, revision-CAS, and one-record mutation boundary

#### Scenario: A stage does not declare cancellation
- **WHEN** the current non-terminal stage has no cancellation contract
- **THEN** the controller preserves the current action and rejects cancellation according to that workflow definition

#### Scenario: Workflow catalog and files drift
- **WHEN** an official ID lacks a file or a packaged official file is absent from the catalog
- **THEN** package validation fails

#### Scenario: Repository topology changes workflow semantics
- **WHEN** package or runtime metadata binds a workflow ID to one repository count, managed workspace strategy, execution topology, or unconditional assurance loop
- **THEN** validation fails because workflow depth and repository, workspace, execution, and task-derived assurance dimensions are independent product dimensions

#### Scenario: No independent review obligation remains
- **WHEN** the current assurance plan contains no outstanding independent-review obligation
- **THEN** the controller advances without projecting a review action and the Delivery Dossier reports why independent review was not required

### Requirement: Assurance failures are persisted and rework is bounded
Every verification, review, and rework execution SHALL persist its result, obligation identity, assurance-plan identity, task-change slice, and execution count. Each effective contract's assurance plan SHALL reserve an absolute integer allowance for every assurance obligation and every dynamically materialized finding-bound source-rework obligation. Each required assurance obligation SHALL have the profile allowance `A`; each source-rework obligation SHALL have allowance one. Every execution, whether passing, failing, unavailable, or later superseded and regardless of the route that projected it, SHALL consume its obligation allowance, applicable aggregate class ceiling, and total-action ceiling exactly once.

Let `V` be the canonical number of required non-review assurance obligations and `R` the canonical number of required independent-review obligations. Let `U` be the canonical retry-unit total in the initial plan's conservative budget-reservation obligation set: a source-rework-capable obligation contributes `max(allowance - 1, 0)` and every other obligation contributes zero. The controller SHALL derive the following aggregate ceilings and SHALL reject caller-supplied alternatives:

| Profile | `verification_ceiling` | `review_ceiling` | `rework_ceiling` |
| --- | --- | --- | --- |
| `lite`, `investigation` | `min(A × V, V + 1)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(1, U)` |
| `feature`, `bugfix`, `refactor` | `min(A × V, V + 2)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(2, U)` |
| `full` | `min(A × V, V + 4)` | `min(A × R, R + 2)` | `min(4, U)` |

When `U` is zero, the source-rework ceiling SHALL be zero. A failed assurance obligation SHALL use its next unused canonical retry unit. Current blocking causal findings from one review result SHALL be grouped into one finding-bound source-rework obligation for the governing review obligation's next unused retry unit; its committed execution consumes that retry unit and one source-rework-ceiling unit. The initial valid plan SHALL fix its canonical budget-reservation set, `U`, ceilings, and consumption for the effective contract. Restart and same-contract replacement SHALL preserve those exact values and SHALL NOT add, recompute, or reset retry authority. `total_action_ceiling` SHALL equal the validated workflow's reachable fixed mutations under the effective contract plus the verification, review, and source-rework ceilings, the exact product-bounded reserve for every reachable unique waiver, finding disposition, persisted-reuse decision, and prerequisite-refresh subject, and exactly one non-cancelled Dossier finalization. The total SHALL NOT exceed 256 actions under one effective contract. A waiver, finding disposition, separately persisted reuse decision, or prerequisite refresh in the assurance region SHALL consume exactly one total-action unit and no verification, review, or source-rework unit. A controller-derived read-only reuse or `not-required` derivation that appends no mutation SHALL consume no unit.

A failed verification SHALL leave its obligation outstanding and may project rework only while all applicable allowances and ceilings permit the complete remaining route. A review SHALL project source rework only for current blocking findings whose causal relation is `introduced` or `affected` within the current plan closure. Exhausting any allowance or ceiling before all required obligations are satisfied SHALL project deterministic incomplete Dossier finalization. A replacement plan under the same effective contract SHALL inherit all consumed counters and SHALL NOT increase any original per-class or total-action ceiling; it may redistribute only remaining reserved authority. An accepted contract revision SHALL retain all prior-contract execution and counter history while installing a newly derived bounded plan for the new effective contract digest. No transition, nested route, restart, action-template cycle, evidence invalidation, or same-contract plan replacement SHALL reset or exceed an allowance. Workflow validation SHALL reject a definition or policy whose `maximum_remaining_actions` cannot be proven finite.

#### Scenario: Verification fails and later passes
- **WHEN** verification records a failed required check while the absolute verification and rework ceilings can cover its repair route, rework completes, and the next verification passes
- **THEN** both executions remain in history, both count against the same effective-contract ceilings, and the satisfied obligation advances without repeating unaffected obligations

#### Scenario: Review requests changes
- **WHEN** review records a current blocking finding whose causal relation is `introduced` or `affected` within the impact closure and the absolute review and rework allowances can cover its repair route
- **THEN** the controller creates a finding-bound rework obligation and later projects only the verification and review obligations invalidated by the resulting task-change slice

#### Scenario: Rework budget is exhausted
- **WHEN** the next required verification, review, rework, or remaining route would exceed an absolute ceiling
- **THEN** the task advances deterministically to incomplete Dossier finalization with the exhausted ceiling, outstanding obligations, findings, and prior executions retained

#### Scenario: Contract changes after a failed attempt
- **WHEN** a contract revision is accepted after one or all assurance executions were consumed under the prior digest
- **THEN** the revised contract receives a newly derived plan and explicit ceilings while every prior-contract execution remains historical and cannot be recounted as an execution under the new digest

#### Scenario: Same-contract replacement discovers more impact
- **WHEN** a replacement plan under the same effective contract adds obligations after impact refresh
- **THEN** it preserves the original canonical budget-reservation set, `U`, every aggregate and total-action ceiling, and consumed count and uses only the remaining recorded authority

#### Scenario: Persisted governance consumes only total-action authority
- **WHEN** a waiver, finding disposition, prerequisite refresh, or persisted reuse decision commits in the assurance region
- **THEN** the mutation consumes exactly one total-action unit and no verification, review, or source-rework unit

#### Scenario: Reuse is derived read-only
- **WHEN** the controller derives current evidence reuse without appending a separate mutation
- **THEN** the derivation consumes no obligation, class, source-rework, or total-action unit

#### Scenario: Total route exceeds the product ceiling
- **WHEN** reachable fixed mutations, all three aggregate class ceilings, exact reachable governance, persisted-reuse and prerequisite-refresh subjects, and one non-cancelled Dossier finalization would require a 257th action
- **THEN** workflow or plan validation fails without omitting obligations or authorizing the excess action

#### Scenario: Workflow contains an unbounded cycle
- **WHEN** any action-template route can repeat without consuming an applicable absolute allowance or the controller cannot derive finite `maximum_remaining_actions`
- **THEN** workflow validation rejects the definition

#### Scenario: Passing verification is followed by review rework
- **WHEN** a passing verification is later invalidated by rework for an `introduced` or `affected` finding
- **THEN** the original verification remains counted, only affected obligations are outstanding, and no repeated action can exceed the original contract's absolute ceilings

### Requirement: Optional drivers have an explicit degraded path
An official workflow action template that names an optional OpenSpec, codebase-memory, or independent-review driver SHALL declare its tool, produced artifact or evidence type, fallback instructions, and the assurance obligations that can require it. The runtime SHALL project driver metadata only when the current action is required by an outstanding obligation and SHALL NOT dynamically load or execute driver code. The main Skill SHALL use the named tool when available or follow the declared fallback and record the resulting driver status. Degraded, partial, stale, unavailable, unconfirmed, or otherwise incomplete driver impact evidence SHALL normalize to `unknown` and SHALL invoke the conservative policy result. Review evidence SHALL distinguish `independent` and `self` assurance, but the controller SHALL derive satisfaction, rework, causal triage, disposition, or exhaustion from the current review obligation, structured findings, causal status, waivers, and absolute budgets rather than trusting an agent-supplied aggregate outcome.

#### Scenario: Optional tool is available
- **WHEN** Codex can invoke an outstanding obligation's named optional tool
- **THEN** the produced artifact or evidence records that tool as its source path and binds the obligation and task-change slice it evaluated

#### Scenario: Optional tool is unavailable
- **WHEN** a required optional tool cannot be invoked
- **THEN** the Skill follows the declared fallback, records degraded driver status, and preserves the obligation's current completion requirements

#### Scenario: Independent tool approves
- **WHEN** the independent-review driver produces current evidence with no unresolved blocking finding, causal-triage state, or impact gap for the exact required task-change slice
- **THEN** the controller marks that review obligation satisfied and does not project an additional review for the same current obligation fingerprint

#### Scenario: Fallback self-review finds changes
- **WHEN** the independent-review tool is unavailable and fallback self-review reports a current blocking `introduced` or `affected` finding
- **THEN** the controller records self assurance and projects the finding-bound route permitted by the current obligations and absolute budgets

#### Scenario: Fallback review cannot establish causality
- **WHEN** independent or fallback review reports a current `blocking: true` finding with `unknown` causal relation
- **THEN** the controller derives `triage-required`, keeps review outstanding, and permits only bounded causal prerequisite refresh or an authorized finding disposition before approval or source rework

#### Scenario: Fallback cannot provide independence
- **WHEN** fallback self-review finds no unresolved blocker, causal-triage state, or impact gap but the assurance plan requires independent review and no exact current assurance waiver exists
- **THEN** the independent-review obligation remains outstanding and eventually reaches incomplete finalization when its absolute execution or action ceiling cannot permit another attempt

#### Scenario: Operator waives unavailable independent review
- **WHEN** an exact current `assurance-waiver` decision governs the independent-review obligation and the driver records unavailable independent assurance
- **THEN** the controller marks that obligation waived while the Dossier reports the actor, rationale, and remaining risk and never labels self-review as independent approval

#### Scenario: Optional review is not required
- **WHEN** the current assurance plan does not require independent review for the affected behavior and risk
- **THEN** no independent-review driver action or fallback self-review is projected

### Requirement: Optional tool outputs follow tool-specific correctness contracts
OpenSpec stages SHALL request current machine-readable status and instructions for the selected change and SHALL record the concrete artifact paths and digests they used. An OpenSpec stage that creates or updates repository files SHALL be a source-producing stage with a pinned source predecessor, a controller-derived task-change manifest successor, and authoritative governing resource bindings for proposal, design, and specs. Its `tasks.md` SHALL record a raw progress digest and a governing semantic digest that ignores only task-list checkbox state while preserving text, order, and test obligations. Machine-generated status output MAY be reported without governing plan freshness. Codebase-memory stages SHALL keep baseline and current-generation workspace project IDs separate, select the graph appropriate to the current workflow phase, confirm material conclusions in source, bind conclusions to affected repositories, paths, symbols, and behavior, and record stale, unavailable, or unconfirmed graph evidence as degraded. Independent review SHALL emit `dev-flow-independent-review/0.3.0` evidence with `dev-flow-review-finding/0.3.0` values and bind reviewer identity, assurance, base revision, assurance-plan and obligation fingerprints, reviewed task-change-manifest and slice digests, guidance and complete snapshot digests, and per-finding evidence to the exact reviewed slice. Each finding SHALL declare its stable finding ID, fingerprint, severity, blocking flag, one of the causal relations `introduced`, `affected`, `pre-existing`, `out-of-scope`, or `unknown`, acceptance-criterion IDs, repository ID, bounded path, symbol, resource, or integration locator, evidence, and smallest sufficient resolution. These contracts SHALL be enforced by controller validation where authoritative and by Skill guidance and package validation where driver execution remains outside the controller.

#### Scenario: OpenSpec stage uses current instructions
- **WHEN** an OpenSpec-backed stage runs
- **THEN** its source-producing artifact records the selected change, current JSON status and instructions, concrete returned artifact paths and authoritative digests, governing versus reported resource roles, and its controller-derived task-change-manifest successor

#### Scenario: Code graph generation changes
- **WHEN** impact analysis compares a baseline with current code
- **THEN** it uses separate project IDs, selects each by phase, confirms every material graph conclusion against source, and records an explicit impact closure over the affected task-change slice

#### Scenario: Graph evidence cannot be confirmed
- **WHEN** codebase-memory output is unavailable, stale, or materially unconfirmable in source
- **THEN** the fallback artifact records degraded coverage, leaves impact closure unknown for the affected region, and does not present the graph conclusion as complete proof

#### Scenario: Independent review snapshot drifts
- **WHEN** the base revision, reviewed task-change-manifest or slice digest, obligation fingerprint, or guidance snapshot changes during review
- **THEN** the evidence cannot satisfy the current independent-review obligation and review must be rerun only for the invalidated obligation or resolved through an authorized disposition

#### Scenario: Review submits a free-form blocking outcome
- **WHEN** review output supplies an aggregate `changes-requested` outcome without valid structured findings and current causal evidence
- **THEN** the controller rejects the output without entering source rework

### Requirement: One pre-release version seals the supported protocol
The product SHALL expose exact semantic version `0.3.0` from one `PRODUCT_VERSION` runtime authority. Plugin and package metadata, task state, workflow and assurance-policy documents, controller data namespace, every current schema identifier and digest domain, projections, task-change manifests, assurance plans, obligations, structured findings, snapshots, action bindings, records, evidence, Delivery Dossier, receipt, Skills, tests, and public guidance SHALL use that same value. The product SHALL derive one current `PRODUCT_IDENTITY` from the shared version, accepted schema vocabulary, and one-to-eight repository topology authorities. Selected-workflow identity SHALL bind only the workflow selector, current schema, and canonical document.

Every supplied workflow, policy, task, contract, record, snapshot, binding, manifest, plan, obligation, finding, projection, evidence, and Dossier value SHALL carry its exact supported 0.3.0 identity; a supplied non-0.3 value SHALL be rejected at the current input boundary without migration, translation, repair, recovery, fallback parsing, or partial recording. Runtime discovery SHALL be confined to the 0.3 data namespace. The 0.3 runtime SHALL never enumerate, discover, read, import, migrate, translate, repair, reinterpret, recover, or delete retained 0.2 namespace bytes. Retained 0.2 bytes SHALL remain byte-for-byte unchanged outside the 0.3 product boundary and SHALL have no effect on current installation, discovery, admission, replay, or task operations.

#### Scenario: Current task loads
- **WHEN** a task and every persisted value match the installed current identities and schemas
- **THEN** deterministic replay derives the same task-change manifest, assurance plan, satisfied and outstanding obligations, budget consumption, state, and current action

#### Scenario: Product surfaces are inspected
- **WHEN** package validation inspects runtime constants, plugin and package metadata, workflow assets, Skills, tests, and public guidance
- **THEN** every current version equals `0.3.0` and any generation-coded or component-specific current version causes validation to fail

#### Scenario: Workflow document changes
- **WHEN** the canonical selected workflow document differs from the pinned selected-workflow identity
- **THEN** the task fails with a workflow identity mismatch

#### Scenario: Unsupported schema is encountered
- **WHEN** a caller supplies any workflow, policy, task, record, snapshot, action binding, task-change manifest, assurance plan, obligation, finding, projection, verification, or Dossier value whose identity is not exactly supported by 0.3.0
- **THEN** the current input boundary rejects the value without invoking an alternate parser, compatibility path, conversion, repair, or partial mutation

#### Scenario: Repository topology authority changes
- **WHEN** the supported topology or current schema vocabulary changes
- **THEN** the derived product identity changes and persisted tasks under the prior identity are not reinterpreted

#### Scenario: Prior-version files remain on disk
- **WHEN** persisted `0.2.0` bytes exist outside the `0.3.0` data namespace
- **THEN** the current runtime leaves them byte-for-byte unchanged, never enumerates, discovers, reads, migrates, translates, repairs, or deletes them, and excludes them from current installation and task operations

### Requirement: Assurance plans project only outstanding task-scoped obligations
After preflight and every accepted contract, impact, task-change-manifest, finding disposition, or evidence change, the controller SHALL derive or replay one canonical `dev-flow-assurance-plan/0.3.0` from `dev-flow-assurance-policy/0.3.0`. The plan SHALL bind a stable plan ID and digest to the effective contract, selected workflow, complete roll-forward task-change manifest, affected behavior and impact closure, governing inputs, closed risk classification, current waivers, and absolute budgets. It SHALL enumerate stable obligation IDs and fingerprints whose kinds are exactly `repository-check`, `integration-check`, `documentation-check`, `independent-review`, or `manual-evidence`. Each obligation SHALL declare its acceptance-criterion IDs; exact member and task-change slice; path, symbol, resource, or integration scope; prerequisites; evidence contract; impact closure; completion, invalidation, and reuse rules; driver requirement; execution class; and absolute allowance.

Obligations SHALL be grouped canonically as at most one repository check for each required member, one integration check for each distinct evidence contract over the sorted set of required canonical boundaries, and at most one documentation, manual-evidence, and independent-review obligation per plan. Each grouped obligation SHALL bind the sorted union of applicable criteria, slices, and boundaries. The plan SHALL reserve bounded finding-disposition and source-rework routes and aggregate verification, review, source-rework, and total-action ceilings without treating those routes as additional assurance kinds. The controller SHALL project exactly one action using deterministic plan order, reuse evidence only when the declared slice, closure, criteria, prerequisites, and governing fingerprints remain current, and derive obligation state only from `required`, `blocked`, `outstanding`, `satisfied`, `reused`, `not-required`, `waived`, and `exhausted`.

The 0.3 product bounds SHALL be:

| Bounded collection or output | Maximum |
| --- | ---: |
| Snapshot paths per repository | 4,096 |
| Git index stage entries per repository | 12,288 |
| Git index command output per repository capture | 2 MiB |
| Ownership claims per source action | 128 |
| Entries in the current roll-forward manifest across the task | 4,096 |
| Entries in one impact report | 128 |
| Obligations in one assurance plan | 64 |
| Findings in one review execution | 64 |
| Evidence items in one assurance execution | 64 |
| Workflow actions under one effective contract | 256 |

These bounds SHALL apply together with the shared 64 KiB action-payload and 8 KiB per-text limits. No collection, payload, text value, or command output MAY be truncated to fit a bound, and an over-bound mutation SHALL fail atomically without a partial record. An impact closure that would require a 129th entry SHALL record bounded overflow, normalize confidence to `unknown`, and derive the conservative assurance set; it SHALL NOT submit a truncated focused closure. A canonical conservative plan that would require a 65th obligation SHALL fail before dispatch.

A contract revision's complete aggregate `revision-source` SHALL anchor later source intervals only. It SHALL NOT replace the immutable ownership origin or erase task-owned work. The replacement current manifest SHALL roll forward every still-material inherited task-owned entry, every exact ambient-drift entry adopted by the authorized revision, and every later task-owned entry with current criterion mappings and lineage. A missing inherited entry, unclaimed adopted path, incompatible mapping, or silently changed identity SHALL reject the revision atomically.

#### Scenario: Low-risk local change has targeted obligations
- **WHEN** current impact evidence closes a low-risk task change to one repository-local behavior and no policy requires independent review
- **THEN** the plan projects the required targeted criterion and repository checks without unrelated integration or review actions

#### Scenario: A later change does not affect prior evidence
- **WHEN** a source action changes a slice disjoint from a satisfied obligation and its governing inputs, criterion meaning, impact closure, and obligation fingerprint remain current
- **THEN** the controller reuses that evidence and projects only obligations affected by the new slice

#### Scenario: Impact closure is unknown
- **WHEN** the controller cannot establish the affected behavior or dependency closure for a task-owned change
- **THEN** the assurance plan requires repository checks for every task member, integration checks for every declared or applicable canonical boundary, independent review, and every profile- or criterion-required documentation or manual-evidence obligation

#### Scenario: Canonical grouping would be split
- **WHEN** a candidate plan contains two repository checks for one required member, two integration checks for the same boundary evidence contract, or multiple documentation, manual-evidence, or independent-review obligations
- **THEN** validation rejects the non-canonical plan without increasing budgets or actions

#### Scenario: Impact report overflows
- **WHEN** a source-confirmed impact closure would require a 129th bounded entry
- **THEN** the report records overflow without truncation and the controller normalizes the closure to unknown conservative assurance

#### Scenario: Plan exceeds its obligation bound
- **WHEN** canonical grouping would still require a 65th obligation
- **THEN** validation fails before assurance dispatch without dropping or merging obligations with different evidence contracts

#### Scenario: Contract revision rolls current ownership forward
- **WHEN** an authorized replacement contract is accepted after task-owned changes and exact adopted ambient drift are present
- **THEN** its revision source starts the next interval while the replacement manifest retains every still-material inherited entry, exact adopted entry, and later task-owned entry with immutable lineage

#### Scenario: All obligations are discharged
- **WHEN** every required obligation is satisfied, validly reused, or explicitly waived and no disposition or causal blocking finding remains outstanding
- **THEN** the next projected action is Delivery Dossier finalization rather than another verification or review action

#### Scenario: Plan changes after restart
- **WHEN** a restarted controller replays the same records, task-change manifest, governing inputs, and effective contract
- **THEN** it derives the same assurance-plan digest, obligation states, absolute budget consumption, and current action

### Requirement: Structured review findings gate rework by task causality
The controller SHALL accept review evidence only through `dev-flow-independent-review/0.3.0` and `dev-flow-review-finding/0.3.0`. It SHALL validate each finding's stable ID and fingerprint, severity, blocking flag, causal relation, criterion bindings, repository ID, bounded path, symbol, resource, or integration locator, evidence, smallest sufficient resolution, reviewed task-change-manifest, assurance-plan, review scope, guidance, snapshot, and reviewer fingerprints. The controller SHALL derive review-obligation status and the aggregate `approved`, `changes-requested`, `triage-required`, or `unavailable` outcome from the complete current finding set, current dispositions, reviewer availability, and independence.

Only a current `blocking: true` finding whose relation is `introduced` or `affected` within the current plan's impact closure SHALL create source rework. A `pre-existing`, `out-of-scope`, or `blocking: false` unknown finding SHALL remain reportable evidence and SHALL NOT consume source-rework budget or expand task scope by itself. A current `blocking: true` finding with `unknown` or disputed causality SHALL keep the review obligation unresolved in `triage-required`; it SHALL permit neither approval nor direct source rework until bounded causal prerequisite refresh establishes a governed relation or an authorized current finding disposition resolves it.

An `affected` relation SHALL require current source-confirmed evidence connecting at least one task-owned manifest entry to the finding location or behavior. When that evidence proves an affected relation outside the governing impact closure, the finding SHALL record an `impact-gap`; the controller SHALL invalidate the current plan and reenter bounded impact analysis and planning under the same effective contract and remaining counters before any source rework. The replacement plan may authorize rework only after its closure contains the proven relation. Contract revision SHALL occur only when the accepted scope or criteria must change. The controller SHALL expose exact current findings for user-authorized `accepted-risk`, `confirmed-out-of-scope`, or `expand-contract` dispositions; an unrecorded or Agent-supplied disposition SHALL have no authority. Rework completion SHALL identify the exact finding fingerprints addressed, and later review SHALL close or replace those findings without losing lineage.

#### Scenario: Review finds an unrelated legacy issue
- **WHEN** a current review reports a blocking issue in a path outside the task-change slice with evidence establishing it as `pre-existing` or `out-of-scope`
- **THEN** the controller reports the finding without projecting rework, rerunning unaffected assurance, or expanding the contract

#### Scenario: Review finds a task-introduced or affected blocker
- **WHEN** a current structured finding is blocking, bound to the reviewed task-change slice, and causally `introduced` or `affected` within the impact closure
- **THEN** the controller creates one finding-bound rework obligation subject to the absolute rework ceiling

#### Scenario: Finding causality is disputed
- **WHEN** a blocking finding has `unknown` causal relation or its asserted relation is disputed
- **THEN** the controller derives `triage-required`, keeps the review obligation unresolved, and permits bounded causal refresh or an authorized disposition but neither approval nor direct source rework

#### Scenario: Non-blocking unknown finding is advisory
- **WHEN** a current finding has `blocking: false` and `unknown` causal relation
- **THEN** the controller retains it as an advisory observation without consuming source-rework authority or blocking completion by itself

#### Scenario: Review proves an affected impact gap
- **WHEN** current source evidence proves that a task-owned change affects a location or criterion outside the governing impact closure
- **THEN** the controller records an impact gap, invalidates the current plan, and reenters impact analysis and planning under the same contract and remaining counters before any source rework

#### Scenario: Impact gap fits the accepted contract
- **WHEN** replacement impact closure can include the proven affected relation without changing accepted scope or criteria
- **THEN** planning remains under the same effective contract and no contract revision is required

#### Scenario: Agent contradicts derived review status
- **WHEN** an Agent supplies an approval or changes-requested summary that contradicts the validated structured findings
- **THEN** the controller ignores or rejects the supplied aggregate status and uses the derived obligation state without an incorrect transition

#### Scenario: Rework addresses one of several findings
- **WHEN** rework records successor manifest evidence for one `introduced` or `affected` finding while another current blocking `introduced` or `affected` finding remains unresolved
- **THEN** the first finding gains resolution lineage and the remaining finding keeps the review obligation outstanding
