# package-delivery-validation Specification

## Purpose
TBD - created by archiving change fix-v5-confirmed-defects. Update Purpose after archive.
## Requirements
### Requirement: Candidate validation uses candidate content
The package validator SHALL evaluate the source, workflow definitions, product catalog, and public assets belonging to the candidate root supplied by the caller.

#### Scenario: Candidate workflow is invalid
- **WHEN** a copied candidate contains an invalid workflow while the invoking checkout remains valid
- **THEN** validation of that candidate fails

#### Scenario: Candidate is valid
- **WHEN** a complete candidate is validated from a different filesystem path
- **THEN** validation succeeds without using already imported modules from the invoking checkout

### Requirement: Verification evidence reflects an executed command
The installation smoke procedure SHALL record passing test evidence only after the documented verification command has executed successfully.

#### Scenario: Verification succeeds
- **WHEN** the documented verification command exits successfully
- **THEN** the smoke procedure records `passed: true` with that command

#### Scenario: Verification fails
- **WHEN** the documented verification command exits unsuccessfully
- **THEN** the smoke procedure does not record passing evidence

### Requirement: Public skill guidance matches the current product
The packaged `follow-dev-flow` Skill and agent metadata SHALL describe compatibility model `0.4.0` and one exact set of one to eight user-prepared local Git worktrees. Guidance SHALL explain official workflow selection; repeatable repository selection; active leases over canonical roots and worktree-specific Git administrative directories; one task and one current action for one Codex executor; structured contracts; the closed `dev-flow-assurance-policy/0.4.0` profile matrix and risk triggers; the immutable preflight ownership origin and roll-forward manifests; contract-revision interval anchors and exact drift adoption; ambient-drift handling; canonical assurance plans and obligations; structured causal review findings, `triage-required`, and impact-gap planning reentry; absolute recorded-attempt and total-action budgets; optional-driver fallback; explicit decisions; and Delivery Dossier completion. It SHALL explain that distinct linked worktrees sharing a Git common directory can support separate active tasks while one repository set rejects duplicate common-directory members. It SHALL keep branch/worktree creation and removal, Git publication, parallel Agent execution, and external CI/PR/release effects outside controller authority.

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

Candidate validation SHALL prove that every official workflow embeds the exact closed `dev-flow-assurance-policy/0.4.0`; uses only the trigger IDs `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`, `cross-repository-contract`, `installer`, and `protocol`; and normalizes every non-source-confirmed, degraded, partial, stale, unavailable, unconfirmed, or unknown impact result to conservative every-member, declared-or-applicable-integration, and independent-review assurance plus profile- or criterion-required documentation and manual evidence. It SHALL reject custom policies that remove a base-profile obligation, weaken a risk or unknown result, raise an allowance or product maximum, or introduce a free-form trigger. It SHALL validate canonical grouping as at most one repository check per required member, one integration check per distinct evidence contract over the sorted required boundaries, and at most one documentation, manual-evidence, and independent-review obligation per plan.

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

Candidate validation SHALL require plugin manifest, Python package metadata, and lock metadata to equal the single `RELEASE_VERSION` source. It SHALL independently require exact `MODEL_VERSION` `0.4.0` in workflow and assurance-policy documents, schema identifiers, Hook and Skill protocol guidance, installed evidence, and persisted-model documentation. Unsupported generation-coded or component-specific identities SHALL be rejected from executable current assets. Runtime action validation SHALL require the complete `0.4.0` schema family for driver results, snapshots, task change manifests, assurance plans, verification coverage, independent review, review findings, action bindings, projections, records, and Dossiers. Any supplied missing, mixed, or non-`0.4.0` model identity SHALL fail closed during initial application and replay without conversion or partial recording. Discovery and admission tests SHALL prove that the `0.4.0` model runtime never enumerates, discovers, reads, replays, migrates, translates, repairs, or deletes retained `0.2.0` namespace bytes.

The candidate SHALL include a standard-library release-bump command that validates semantic versions, updates only the release authority and derived manifest/package/lock metadata, leaves `MODEL_VERSION` and all protocol-bearing files unchanged, and fails closed on missing, duplicate, or inconsistent version fields.

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
- **WHEN** a caller supplies a `0.2.0` or otherwise non-`0.4.0` workflow, policy, task, record, snapshot, artifact, action value, or binding to a current input boundary
- **THEN** the `0.4.0` model runtime rejects the value as unsupported without compatibility parsing, replay, migration, translation, repair, fallback, or partial mutation

#### Scenario: Retained prior-namespace bytes exist
- **WHEN** retained `0.2.0` namespace bytes are present beside the installed `0.4.0` data namespace
- **THEN** discovery, admission, replay, and package validation leave those bytes unchanged and never enumerate, discover, read, migrate, translate, repair, or delete them

#### Scenario: Patch release is prepared
- **WHEN** an operator runs the release-bump command with a valid patch version and no compatibility-model change is declared
- **THEN** only the release authority, plugin manifest, Python package metadata, and lock metadata change, while schemas, namespaces, workflow documents, identities, Skills, and protocol documentation remain byte-for-byte unchanged

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
- **WHEN** installed task admission encounters a model `0.4.0` namespace entry whose immutable membership or controller-confirmed terminal state cannot be validated
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

### Requirement: Candidate and installed validation prove the local read-only Web UI
The candidate package SHALL require the local Web UI server module, read-model module, CLI bootstrap, HTML, CSS, and JavaScript assets and SHALL include them in release-metadata validation, installed asset inventory, and immutable installed-snapshot digests. It SHALL prove that plugin manifest, Python package metadata, lock file, runtime release authority, startup receipt, HTTP views, page display, and installed evidence identify the same `dev-flow-orchestrator` `RELEASE_VERSION`, while task views retain `MODEL_VERSION` and the model `PRODUCT_IDENTITY`. It SHALL reject an independent Web UI version, package, plugin, marketplace entry, application or MCP declaration, data namespace, persisted schema authority, release gate, third-party runtime import, Node runtime or build requirement, remote browser resource, telemetry endpoint, write capability, or non-loopback server claim.

Focused validation SHALL cover the physically non-mutating inspection store, CLI contract, server lifecycle, token authority, exact Host, Origin and fetch-metadata checks, absent CORS authority, fixed routes and assets, method denial, traversal denial, response bounds and security headers, deterministic inventory filtering and pagination, corrupt-entry isolation, stored detail with zero Git calls, explicit live detail using one aggregate observation, global live-capture exclusion and `429`, capture cancellation, snapshot-unavailable and stale-view behavior, why-next, recovery brief, timeline projection, disclosure minimization, output encoding, responsive browser states, and the complete no-mutation boundary. Candidate tests SHALL prove that Web UI observation and invalid requests do not create or acquire controller locks, create data directories, normalize permissions, or change task bytes, records, revisions, timestamps, repository `HEAD`, index or worktree identities, installed assets, marketplace state, or prior-version bytes.

The installed `dev-flow-installed-evidence/0.4.0` suite SHALL contain one `local-read-only-web-ui` journey from the immutable installed candidate. It SHALL create representative active and terminal tasks, start the installed server on an ephemeral loopback port, verify the startup receipt and asset digests, fetch the bootstrap, metadata, authenticated inventory, stored detail, and explicit live detail with the standard-library HTTP client, exercise missing and incorrect authority, hostile Host, Origin and fetch metadata, unsafe methods, invalid task IDs and traversal, missing-member diagnostics, concurrent live capture, capture termination, task refresh after an external controller mutation, and clean foreground shutdown. It SHALL record before-and-after directory, lock, mode, task, repository, installed-snapshot, and prior-namespace identities proving that the Web UI itself made no change.

Installed browser evidence SHALL render empty, multi-task, selected active, blocked or unavailable, terminal, timeline, recovery, diagnostic, and adversarial-text states at desktop and narrow viewport widths. It SHALL verify keyboard access, visible focus, safe text rendering, security-policy compliance, absence of external requests and console errors, and the visible read-only and current-product identities. If the release environment cannot observe a real browser, installed evidence SHALL mark browser rendering `manual-unverified`; HTTP success alone SHALL NOT be reported as complete Web UI release evidence.

Public documentation validation SHALL require the English source and complete Simplified Chinese counterpart for `README`, `ROADMAP`, `ARCHITECTURE`, `CONTRIBUTING`, and `INSTALL`. It SHALL verify matching commands, routes, release/model version boundaries, loopback and access model, read-only authority, task views, runtime-dependency boundary, support status, language-switch links, and installed validation limits. The roadmap SHALL mark only the delivered local read-only cockpit slice and SHALL keep the remaining interactive-workbench capabilities at their actual planned status.

#### Scenario: Candidate Web UI assets are inspected
- **WHEN** candidate validation scans required files, runtime imports, browser assets, manifests, metadata, lock data, version literals, network references, and capability declarations
- **THEN** every required asset is present under the single 0.4.0 plugin, runtime dependencies remain standard-library-only, browser assets require no build or remote resource, and every independent version, package, namespace, write, remote, app, or MCP claim fails validation

#### Scenario: Installed authorized journey succeeds
- **WHEN** the installed server receives an exact-host same-origin request with its process token for representative task inventory and detail
- **THEN** the installed views match controller state and current projection summaries, report the installed `RELEASE_VERSION` with the current model identity, and record no task or repository mutation

#### Scenario: Installed hostile requests are denied
- **WHEN** the installed server receives missing or incorrect authority, a hostile Host or Origin, an unsafe method, an invalid task ID, a traversal target, or a non-allowlisted route
- **THEN** each request fails with the specified bounded response, exposes no protected task data, invokes no mutation, and leaves all before-and-after identities unchanged

#### Scenario: Installed repository is unavailable
- **WHEN** an installed journey opens a valid task whose member cannot be captured
- **THEN** inventory remains available, selected detail reports the bounded unavailable diagnostic, and neither task membership nor repository state is repaired, substituted, hidden, or changed

#### Scenario: Browser renders adversarial task text
- **WHEN** installed browser evidence displays task and diagnostic text containing markup, script, style, URL, and path syntax
- **THEN** the text remains inert, no external request or executable DOM is created, browser security policy remains effective, and the task is unchanged

#### Scenario: Browser observation is unavailable
- **WHEN** installed HTTP validation passes but no real browser observation is available
- **THEN** the release evidence reports browser rendering as `manual-unverified` and does not claim complete Web UI validation

#### Scenario: Bilingual Web UI guidance drifts
- **WHEN** a public English or Simplified Chinese document omits or changes the Web UI command, version, loopback, read-only, support-status, validation-limit, or language-switch contract relative to its counterpart
- **THEN** candidate documentation validation fails

### Requirement: Focused validation covers the native Windows runtime without duplicating the full product matrix

The candidate SHALL include a focused Windows CI job that imports the runtime and executes the platform path, storage, process, snapshot, and core-controller tests required by `native-windows-runtime`. The job MAY use GitHub's maintained Windows runner as implementation test infrastructure without adding Windows Server to the public support claim.

The existing macOS focused job SHALL remain the complete product regression gate. Windows validation SHALL NOT duplicate every workflow, assurance profile, installed journey, documentation assertion, Python version, and boundary maximum solely for platform parity.

#### Scenario: Windows runtime candidate passes

- **WHEN** Windows import, path, lock, state replacement, bounded process, representative snapshot, and core-journey tests pass and the existing macOS focused job passes
- **THEN** the candidate satisfies this change's automated platform gate

#### Scenario: Windows imports POSIX-only storage

- **WHEN** importing the candidate on Windows attempts to import `fcntl` or execute another unavailable POSIX-only primitive
- **THEN** the Windows job fails before the candidate can be accepted

#### Scenario: Core platform change alters persisted authority

- **WHEN** the candidate changes current persisted field sets, Schema identifiers, `MODEL_VERSION`, workflow definitions, or replay rules without a separately declared compatibility-model change
- **THEN** candidate validation fails this change's scope gate

### Requirement: Client smoke evidence remains proportional to the delivered runtime slice

Before downstream Hook and installer work treats the runtime as available, validation SHALL record one native Windows 11 x64 client smoke covering the core controller lifecycle. A Windows 10 22H2 x64 smoke SHOULD be recorded when that host is available.

The evidence SHALL identify the OS build, Python version, Git version, repository path characteristics, commands or test entry point, and outcome. It is not required to certify Windows Server, ARM64, WSL, network storage, every supported Python version, or extreme filesystem behavior.

#### Scenario: Windows 11 client smoke succeeds

- **WHEN** the scoped core lifecycle completes on a native Windows 11 x64 client using an ordinary local repository
- **THEN** the evidence is sufficient for subsequent Hook and lifecycle changes to depend on this runtime

#### Scenario: A smoke defect is found

- **WHEN** the supported client smoke exposes a reproducible path, lock, process, or snapshot defect
- **THEN** the defect is fixed with one targeted regression test before the runtime is treated as ready

### Requirement: Candidate validation includes Windows product-integration assets proportionally

The candidate package SHALL require the Windows Hook command, `.cmd` Python launcher, PowerShell installer, PowerShell uninstaller, and focused Windows integration tests as current-product assets. It SHALL validate that every packaged command Hook retains its existing `command` and provides a non-empty `commandWindows`, that public bootstraps select the correct launcher, and that no Windows-specific product identity, Schema, namespace, workflow, package, or Web UI version is introduced.

Host-neutral validation SHALL inspect all static assets. Host-executed validation SHALL run POSIX lifecycle behavior on macOS and Windows launcher, Hook, lifecycle, Web UI, and installed-smoke behavior on Windows. The existing macOS focused job SHALL remain the broad product regression gate; Windows automation SHALL NOT duplicate every shared workflow, assurance profile, installed journey, Python minor, and boundary maximum.

#### Scenario: Complete Windows integration candidate is inspected

- **WHEN** package validation scans Hook configuration, launchers, lifecycle scripts, tests, manifests, runtime imports, and public documents
- **THEN** all required assets are present, paired host commands are valid, and all surfaces identify the same whole product

#### Scenario: Windows Hook override is missing

- **WHEN** one packaged command Hook lacks `commandWindows` or points to a missing launcher or handler
- **THEN** candidate validation fails before installation

#### Scenario: Platform test scope expands into a duplicated product matrix

- **WHEN** the candidate requires Windows to rerun every platform-neutral workflow and assurance permutation without a Windows-specific failure hypothesis
- **THEN** review reduces the matrix to platform adapters, one vertical installed journey, and one multi-repository smoke while preserving the main product suite

### Requirement: Installed Windows evidence proves the complete user path

The installed evidence SHALL contain one native Windows vertical journey from the immutable installed plugin snapshot. It SHALL cover verified source selection, personal marketplace registration, plugin activation, real Hook bootstrap execution, one representative Controller task through current assurance and Delivery Dossier completion, local read-only Web UI inspection, plugin removal, marketplace cleanup, and preserved task data.

A second shorter journey SHALL prove an exact two-repository task can be discovered and resumed from the non-first member and can obtain one current aggregate repository-set observation. Optional external drivers MAY report their existing available, degraded, or unavailable states and SHALL NOT become separate Windows installation requirements.

#### Scenario: Installed Windows vertical journey succeeds

- **WHEN** the candidate is installed on a supported Windows x64 client or equivalent installed test environment and its representative task completes
- **THEN** Hook, Controller, workflow, assurance, Dossier, Web UI, and lifecycle outputs all bind the same installed product snapshot

#### Scenario: Multi-repository recovery succeeds

- **WHEN** the installed Hook starts from the second member of an active two-repository task
- **THEN** it restores that task and the Controller derives the current aggregate evidence without substituting membership

#### Scenario: Uninstall follows the journey

- **WHEN** the installed journey invokes the Windows uninstaller after plugin use
- **THEN** plugin and marketplace installation assets are removed as authorized while Controller task data remains present

### Requirement: Public Windows support claims match tested consumer-client evidence

Before documentation labels native Windows support as delivered, release evidence SHALL include one complete Windows 11 x64 client install-to-uninstall journey. A Windows 10 22H2 x64 smoke SHALL cover installation, Hook launch, task resume, Web UI startup, and uninstallation before that client version is included in the public support claim. Evidence SHALL identify OS build, PowerShell, Python, Git, and Codex versions and the actual result.

GitHub-hosted Windows Server automation MAY satisfy continuous implementation checks but SHALL NOT by itself establish Windows Server support or replace consumer-client evidence. Every reproducible supported-client defect found during release validation SHALL receive one targeted regression test.

English and Simplified Chinese README, INSTALL, ARCHITECTURE, ROADMAP, and CONTRIBUTING documents SHALL agree on supported Windows clients, x64 and Python requirements, PowerShell commands, Hook trust, ordinary local repository scope, unsupported environments, Web UI behavior, validation limits, and no historical or cross-operating-system migration promise.

#### Scenario: Windows 11 client evidence passes

- **WHEN** the complete installed journey passes on a documented Windows 11 x64 client
- **THEN** the release may claim native Windows support within the stated boundary

#### Scenario: Only hosted Server automation exists

- **WHEN** CI passes on `windows-latest` but no supported consumer-client journey has been recorded
- **THEN** the candidate remains an implementation preview and public documentation does not claim completed client support

#### Scenario: Bilingual support guidance drifts

- **WHEN** English or Simplified Chinese guidance disagrees on a Windows command, supported host, Hook trust step, unsupported path, Web UI behavior, or validation limit
- **THEN** candidate documentation validation fails
