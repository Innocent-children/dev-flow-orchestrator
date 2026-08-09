## Purpose

Replace package release gates that treat Skills and Hooks as current model-facing
authority with equally strict MCP protocol, tool, guidance, installation, compatibility,
and installed-journey evidence while preserving every current workflow, assurance,
repository, model-version, and boundary guarantee.

## RENAMED Requirements

- FROM: `### Requirement: Public skill guidance matches the current product`
- TO: `### Requirement: Public MCP guidance matches the current product`

## MODIFIED Requirements

### Requirement: Public MCP guidance matches the current product

The packaged server instructions, stable tool descriptions, generated input and
output schemas, action-guidance catalog, plugin metadata, and public operator
documentation SHALL describe compatibility model `0.4.0` and one exact set of one to
eight user-prepared local Git worktrees. Together they SHALL explain:

- official workflow selection;
- exact repository-set admission and active member leases;
- one task, one current action, and one Codex executor;
- structured delivery contracts and contract revision;
- immutable preflight ownership origin and roll-forward task-change claims;
- ambient drift and exact ownership adoption;
- task-scoped assurance plans, current obligations, closed risk triggers, evidence
  reuse, and absolute recorded-attempt and total-action budgets;
- optional OpenSpec, codebase-memory, and independent-review driver provenance and
  fallback;
- structured causal findings, `triage-required`, impact-gap planning reentry,
  decisions, waivers, dispositions, and Delivery Dossier completion;
- repository-mismatch stop and explicit cancellation authority;
- the non-goals of branch/worktree management, Git publication, parallel executors,
  and external CI/PR/release effects;
- the loss of the old PreToolUse guard and the bounded MCP/local-shell trust model.

The MCP interface SHALL direct the executor to run only the current projected action
and, within assurance, only the current obligation and smallest declared check. It
SHALL NOT authorize undeclared retries, reuse stale or intersecting evidence, convert
an adjacent observation into a blocking causal finding, claim ambient drift without
complete ownership claims, or present a non-required dimension as completed
assurance. Only source-confirmed impact MAY support focused assurance; degraded,
partial, stale, unavailable, unconfirmed, inconsistent, or unknown impact SHALL use
the conservative policy.

After the executor confirms that immutable repository membership cannot satisfy the
accepted contract, current guidance SHALL require it to stop, identify the exact
active task, and obtain explicit user authority for cancellation unless that
specific authority is already present. Cancellation SHALL use
`dev_flow_cancel_task` only at a declared stage, and completion SHALL be reported
only after Controller authority states `done: true`, `status: CANCELLED`, and
`current_node: cancelled`. Failure or unavailability SHALL preserve active state and
leases.

Normal guidance SHALL NOT tell Codex to invoke `$follow-dev-flow`, read packaged Skill
or Hook files, construct a Controller locator, call the CLI through a shell, or read
Controller state directly. A CLI recovery document MAY describe the retained
operator CLI but SHALL distinguish it from normal MCP execution.

#### Scenario: Packaged MCP metadata is inspected

- **WHEN** package validation reads initialization instructions, tool metadata, schemas, guidance, plugin configuration, and public documentation
- **THEN** stale version, schema, workflow, namespace, ownership, assurance, finding, budget, topology, executor, approval, or cancellation guidance causes validation to fail

#### Scenario: Multi-repository start guidance is inspected

- **WHEN** package validation examines `dev_flow_start_task`
- **THEN** its schema and guidance require one to eight exact roots, canonical exact-set semantics, active member leases, user-prepared worktrees, and one executor

#### Scenario: Focused obligation is projected

- **WHEN** a current plan requires one focused repository check and no integration or review obligation
- **THEN** action guidance requests only that obligation and preserves explainable not-required decisions

#### Scenario: Adjacent review observation is found

- **WHEN** independent review reports a pre-existing, out-of-scope, or non-blocking unknown-causal observation
- **THEN** guidance records it truthfully and does not request task rework or expand the contract

#### Scenario: Blocking review causality is unknown

- **WHEN** review reports a current blocking finding whose causal relation is unknown or disputed
- **THEN** guidance preserves `triage-required`, follows only projected bounded causal refresh, and claims neither approval nor direct source rework without governed relation or authorized disposition

#### Scenario: Review identifies an impact gap

- **WHEN** source evidence proves an affected relation outside the current plan closure
- **THEN** guidance follows plan invalidation and impact/planning reentry under the same contract and requests contract revision only when accepted scope or criteria change

#### Scenario: Repository mismatch lacks cancellation authority

- **WHEN** immutable membership cannot satisfy the accepted requirement and no explicit cancellation authority exists
- **THEN** guidance stops the executor and reports that the task and leases remain active

#### Scenario: Repository mismatch cancellation is authorized

- **WHEN** exact cancellation authority exists and the current stage declares cancellation
- **THEN** guidance invokes the MCP cancellation tool and reports completion only from terminal Controller output

#### Scenario: Legacy source-reading guidance remains

- **WHEN** any installed model-facing asset instructs normal execution through Skills, Hooks, shell CLI locators, or plugin-source inspection
- **THEN** package validation fails

### Requirement: Candidate validation proves supported repository topology

The candidate package SHALL expose authoritative current capability definitions for
repository topology, active leases, task-change ownership, assurance planning,
finding governance, absolute budgets, MCP runtime, MCP tools, action guidance,
managed installation, and task-data preservation. Validation SHALL exercise the
actual candidate root rather than already imported invoking-checkout modules.

Validation SHALL cover:

- core Controller, Store, Git, workflow, delivery, review, and replay behavior;
- strict JSON CLI recovery behavior and local read-only Web UI behavior;
- MCP initialization, instructions, `tools/list`, every stable `tools/call`, output
  schemas, annotations, cancellation, errors, shutdown, and restart;
- official and custom workflow validation;
- one-member and larger exact repository sets, secondary-member discovery,
  pre-existing dirty baselines, staged/unstaged/untracked task changes, ambient drift,
  governing resources, selective evidence reuse, findings, dispositions, exhaustion,
  and aggregate Dossier generation;
- macOS and Windows installed launchers and lifecycle entry points;
- managed-runtime ownership, exact dependency lock, plugin packaging, duplicate
  bundled/standalone registration detection, and public documentation;
- strict release/model identity separation and retained prior-namespace isolation.

Every official workflow SHALL continue to embed the exact closed
`dev-flow-assurance-policy/0.4.0`. Validation SHALL prove the exact supported trigger
IDs `security`, `authorization`, `persistence-replay`, `path-safety`, `concurrency`,
`cross-repository-contract`, `installer`, and `protocol`, and SHALL reject an
additional free-form trigger. A custom policy MAY strengthen a base profile, require
review, reduce allowances, or reduce ceilings; it SHALL NOT remove a base obligation,
weaken unknown-impact or risk-trigger expansion, or raise a product maximum.

Only current source-confirmed impact SHALL permit focused obligations. Every missing,
stale, degraded, partial, unavailable, unconfirmed, inconsistent, or otherwise
unknown result SHALL expand to the current conservative every-member, declared-or-
applicable integration, independent-review, documentation, and manual-evidence rules
for the selected profile and criteria. Canonical grouping SHALL remain at most one
repository check per required member, one integration check per distinct evidence
contract over sorted required boundaries, and at most one documentation,
manual-evidence, and independent-review obligation per plan.

With `V` required non-review obligations, `R` required independent-review
obligations, `A = 2` for every profile except `full`, `A = 3` for `full`, and `U`
equal to the sum of `max(allowance - 1, 0)` for source-rework-capable obligations in
the initial conservative reservation set, validation SHALL prove these exact
ceilings:

| Profile | `verification_ceiling` | `review_ceiling` | `rework_ceiling` |
| --- | --- | --- | --- |
| `lite`, `investigation` | `min(A × V, V + 1)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(1, U)` |
| `feature`, `bugfix`, `refactor` | `min(A × V, V + 2)` | `0` when `R = 0`, otherwise `min(A × R, R + 1)` | `min(2, U)` |
| `full` | `min(A × V, V + 4)` | `min(A × R, R + 2)` | `min(4, U)` |

Validation SHALL prove `rework_ceiling = 0` when `U = 0`, the exact value below a
profile cap, and the cap when `U` meets or exceeds it. One review result SHALL group
all current blocking causal findings into one finding-bound source-rework obligation
against the governing review obligation's next unused retry unit. Materialization
SHALL create no free authority; execution SHALL consume exactly one reserved retry,
one rework unit, and one total-action unit as currently defined. Restart and
same-contract replacement SHALL preserve the original reservation set, `U`, ceilings,
and consumption. Only a new contract digest SHALL derive a new bounded plan.

The total-action ceiling SHALL remain the exact sum of reachable fixed mutations,
all three class ceilings, exact product-bounded reserve for every reachable unique
waiver, finding disposition, persisted-reuse decision, and prerequisite-refresh
subject, and one non-cancelled Dossier finalization, and SHALL remain at most 256 per
effective contract. Read-only reuse derivation SHALL consume no authority; persisted
governance or reuse SHALL consume exactly the currently declared unit classes.

Installed evidence SHALL run both source-confirmed focused and closed-trigger
journeys for each of `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and
`full`. These journeys SHALL prove profile floors, review rules, per-obligation
allowances, class formulas, not-required reasons, optional-driver behavior, and
Dossier results from the installed MCP artifact. Additional installed journeys SHALL
prove contract-revision carry-forward with exact adopted drift, blocking unknown
causality, affected impact-gap reentry, corrupt current-inventory admission failure,
concurrent admission of distinct linked worktrees, and resume of a task created by a
`0.4.x` release.

Boundary validation SHALL exercise both the exact maximum and first excess value for
all current product bounds, including 4,096 snapshot paths per repository, 12,288
Git index stage entries per repository, 2 MiB Git index output per capture, 128
ownership claims per source action, 4,096 current roll-forward manifest entries, 128
impact entries, 64 plan obligations, 64 findings per review, 64 evidence items per
assurance execution, 256 actions per effective contract, the shared 64 KiB action
payload, and shared 8 KiB text field. Exact maxima SHALL remain admissible when every
other rule holds. First-excess values SHALL fail atomically without truncation or
partial mutation, except the current impact-overflow rule that records bounded
overflow and selects unknown/conservative assurance.

Candidate validation SHALL require plugin manifest, Python package metadata, lock
metadata, MCP server identity, and managed-runtime receipt to agree with the single
`RELEASE_VERSION`. It SHALL independently require exact `MODEL_VERSION` `0.4.0` in
workflows, policy, schemas, task records, MCP projections of domain identity,
installed evidence, and persisted-model documentation. Supplied missing, mixed, or
non-current model values SHALL fail closed with no compatibility conversion. Current
runtime discovery, admission, replay, MCP, CLI, and package validation SHALL never
enumerate, read, migrate, translate, repair, or delete retained `0.2.0` namespace
bytes.

The release-bump command SHALL continue to update only release authority and derived
plugin/package/lock/MCP release metadata when no compatibility-model change is
declared. It SHALL leave `MODEL_VERSION`, all `0.4.0` schemas, namespaces, workflows,
policy, and protocol-bearing model documentation unchanged.

#### Scenario: Runtime and capability definition drift

- **WHEN** any Controller, CLI, MCP tool, workflow, guidance, Web view, Dossier, installed journey, or documentation asset describes behavior inconsistent with current product authority
- **THEN** candidate validation fails

#### Scenario: Unsupported later-stage capability is claimed

- **WHEN** assets claim automatic branch/worktree creation, parallel repository executors, per-repository partial approval, remote MCP state, or external CI/PR/release orchestration
- **THEN** candidate validation fails

#### Scenario: Installed exact-set MCP journey succeeds

- **WHEN** the installed candidate runs a task over two prepared worktrees, resumes from the second member, verifies current aggregate evidence, and finalizes through MCP
- **THEN** the Dossier identifies both members and the journey never requires CLI invocation or plugin-source reading

#### Scenario: Installed one-member MCP journey succeeds

- **WHEN** the installed candidate completes a one-member task
- **THEN** snapshot, projection, verification, resources, and Dossier use the same repository-set schemas as the larger journey

#### Scenario: Embedded current-product schema is missing

- **WHEN** an MCP action submits a manifest, plan, verification, review, finding, driver, decision, payload, or binding without its exact current schema
- **THEN** validation fails without a partial mutation

#### Scenario: Retained prior-namespace bytes exist

- **WHEN** retained `0.2.0` bytes are beside the current namespace
- **THEN** installed MCP discovery, admission, replay, and package validation leave them unchanged and unread

#### Scenario: Patch release is prepared

- **WHEN** the release-bump command receives a valid patch release with no model change
- **THEN** only release-authority and derived release metadata change while model-bearing files remain byte-for-byte unchanged

### Requirement: Candidate validation proves the MCP interface and context boundary

The candidate SHALL include protocol tests against the real MCP server process and
SDK client transport. Tests SHALL cover initialize negotiation, bounded instructions,
`tools/list`, all eleven tool calls, structured output validation, concise text
content, unknown tool, malformed JSON-RPC, invalid parameters, current domain errors,
unexpected adapter errors, cancellation before commit, uncertain completion recovery,
EOF, restart, stdout purity, stderr redaction, and no listening socket.

For every stable tool, tests SHALL assert exact name, input schema, output schema,
annotations, task-support declaration, result envelope, size budget, and Controller
mapping. CLI/MCP parity tests SHALL start from equivalent isolated state and prove the
same successful task state or exact current domain error for every mapped operation.
They SHALL not compare unstable request IDs or presentation-only text as domain
authority.

Context tests SHALL enforce server instructions at most 4 KiB with a self-contained
first 512 characters, tool descriptions at most 512 bytes each, serialized
`tools/list` at most 32 KiB, action guidance at most 8 KiB, text summaries at most 4
KiB, and bounded pagination. A required exact action that cannot fit SHALL produce
`MCP_RESULT_LIMIT`; truncation of bindings, payload schemas, current obligation,
review contract, or governing-resource identity SHALL fail validation.

Installed journey instrumentation SHALL prove that normal tasks do not read legacy
Skills, Hooks, CLI source, MCP adapter source, launchers, or raw task-state files to
discover how the product works. It SHALL distinguish legitimate reading of the
user's repository and governing OpenSpec artifacts from package-source reading.

#### Scenario: One stable tool lacks a protocol test

- **WHEN** a catalog tool is not covered by success, failure, schema, annotation, and Controller parity evidence
- **THEN** candidate validation fails

#### Scenario: MCP stdout is polluted

- **WHEN** startup, logging, warning, error, or shutdown writes a non-protocol byte to stdout
- **THEN** protocol validation fails

#### Scenario: Context metadata grows beyond its bound

- **WHEN** instructions, descriptions, catalog, guidance, summaries, or page output exceed their release limits
- **THEN** candidate validation fails before installation

#### Scenario: An installed journey reads plugin source for invocation guidance

- **WHEN** the executor opens package implementation or removed Skill/Hook content to determine normal sequencing or payload shape
- **THEN** the installed journey fails and the missing information must be supplied through the MCP interface
