# Dev Flow Orchestrator Product Roadmap

## Current product: 0.3.0 task-scoped adaptive assurance

The current product delivers task-owned change capsules, membership leases,
index-exact Git evidence, a closed six-profile assurance policy, deterministic
obligation dispatch, absolute attempt budgets, slice-aware evidence reuse,
structured causal review, and explainable Dossier finalization. This replaces
the previous fixed-loop model: focused source-confirmed changes run only the
derived checks, while closed risk triggers and unknown impact expand assurance
conservatively. Historical 0.2 state remains outside the 0.3 namespace and is
not a runtime compatibility surface.

[简体中文](ROADMAP_CN.md)

**Status:** living feature roadmap

**Planning model:** capability horizons sequenced by dependency and advanced by
outcome evidence

**Last reviewed:** 2026-08-03

## North-star product vision

Dev Flow Orchestrator should become the local-first delivery control plane for
AI-assisted software development. A developer starts with a requirement, issue,
or specification; the product turns it into a durable and explainable delivery
plan, coordinates Codex and the surrounding development toolchain, and ends
with a change that is ready to merge, release, or hand off.

The product should own the durable coordination model:

- the delivery contract and acceptance criteria;
- the task graph and current execution state;
- the repository and workspace plan;
- human decisions, approvals, and exceptions;
- artifacts, evidence, provenance, and freshness;
- the final delivery dossier.

Codex writes and reviews code. Git owns source history. OpenSpec,
codebase-memory, CI, issue trackers, and Git hosts provide specialized
capabilities. Dev Flow Orchestrator coordinates them so that intent, work,
decisions, and evidence survive sessions and converge on one delivery outcome.

### End-state journey

```text
Requirement / Issue / Spec
  → delivery contract and acceptance criteria
  → impact analysis and task decomposition
  → repository, workspace, and execution plan
  → human decisions and parallel Codex work
  → verification, independent review, and integration
  → delivery dossier, PR handoff, or release handoff
```

In that end state, developers focus on decisions that require judgment: scope,
design, risk, exceptions, and final approval. The orchestrator carries the full
delivery context forward and advances routine coordination work.

## Current product: 0.3.0 complete personal delivery

Stage 1 is delivered in 0.3.0. A developer can carry a feature, bug fix,
investigation, refactor, or fast change from structured intent to a current
Delivery Dossier through one resumable local task. The shipped product
provides:

- `lite`, `feature`, `bugfix`, `investigation`, `refactor`, and `full`
  workflows, plus pinned absolute-path `dev-flow-workflow/0.3.0` definitions;
- a versioned delivery contract, append-only revisions, decisions, criterion
  waivers, and exact review-assurance waivers;
- typed artifacts with contract binding, producer, safe repository snapshot,
  input lineage, governing resources, digests, and derived freshness;
- one exact canonical set of one to eight user-prepared local Git
  worktrees, with aggregate snapshot, scoped resource, verification, review,
  freshness, and Dossier evidence;
- optional OpenSpec, codebase-memory, and independent-review stages with
  explicit degraded or unavailable results;
- finite verification and review rework with successful or incomplete dossier
  finalization;
- one controller authority shared by the CLI, Hook, and Skills, backed by
  locks, revision CAS, deterministic replay, and atomic replacement.

The current support boundary is one task, one immutable repository set, one
current action, and one Codex executor. Every set cardinality uses
`dev-flow-agent/0.3.0`, aggregate repository-set snapshots, repository-scoped
resources, structured member/integration verification, and Delivery Dossier
0.3.0. The core neither manages branches/worktrees nor
publishes Git changes, coordinates parallel agents, operates external
CI/PR/release systems. Its partial assurance reuse selectively preserves current evidence for unchanged,
provably disjoint task-owned slices.

## Independent product dimensions

The capability model treats every dimension as independently selectable.
Workflow depth, repository topology, execution topology, and workspace strategy
combine through one explicit supported-capability matrix. Git branches and
workflow branches remain distinct concepts.

| Dimension | 0.3.0 current selection | Later horizon choices |
|---|---|---|
| Workflow depth | six official personal workflows and pinned `dev-flow-workflow/0.3.0` custom definitions | reusable workflow packages and further delivery families |
| Control flow | one current action with finite verification/review failure routes | general named outcomes, optional stages, fan-out, and join |
| Task topology | one task | parent-child graphs, initiatives, and batches |
| Repository topology | one exact canonical set of 1–8 local worktrees | monorepo component scopes, repository roles, and dependency topology |
| Workspace strategy | the supplied current worktree | existing or managed branch/worktree strategies with ownership |
| Execution topology | one Codex executor | role-separated and parallel executors |
| Collaboration mode | local personal delivery | verifiable handoff and shared team coordination |
| Assurance level | criterion coverage, focused per-member and repository-set integration verification, optional independent review, and explicit waivers | external CI and release gates plus dependency-aware partial reuse |

One authoritative capability matrix should drive runtime validation, workflow
selection, UI availability, test coverage, packaging, and documentation. The
matrix defines every supported combination and product restriction explicitly.

## Capability destination map

| Capability area | 0.3.0 product | Destination | User value |
|---|---|---|---|
| Intent and scope | Versioned contract, stable criteria, revisions, decisions, and waivers | Policy-backed approvals and delegated scope authority | Every implementation and proof is traceable to accepted intent |
| Workflow portfolio | Six official personal workflows plus pinned `dev-flow-workflow/0.3.0` custom definitions | Reusable workflow packages and additional risk/domain families | Users select delivery rigor suited to the work |
| Execution model | One task, one current action, one executor | Dependency graphs, claims, leases, fan-out, join, and operator intervention | Complex work can be divided, recovered, and recombined |
| Repositories and workspaces | One exact set of 1–8 supplied current worktrees with immutable membership and aggregate recovery | Component scopes, roles, dependencies, and branch/worktree strategies with ownership | Large changes progress with explicit scope and isolation |
| Decisions and authority | Contract-bound criterion and review-assurance waivers with actor labels | Authenticated roles, quorum, approvals, and exact effect authorization | Judgment remains attributable and narrowly scoped |
| Assurance and evidence | Typed lineage, freshness, criterion coverage, bounded review/verification, and Delivery Dossier | Continuous assurance across CI, integration, and release artifacts | “Done” is backed by current proof or an explicit exception |
| Product experience | CLI, Hook pickup, one-action projection, and full task view | Searchable cockpit, timeline, artifact explorer, approval inbox, and why-next explanation | Users understand progress and blockers through supported views |
| Collaboration and ecosystem | Local personal tasks with declarative optional drivers | Verifiable handoff, team roles, policy packs, trusted registry, and scoped connectors | Proven delivery methods become reusable across teams |

## Feature horizons at a glance

The sequence follows product dependencies. Current support is Horizon 1, the
shipped 0.3.0 capability. Horizons 2–7 are planned product directions.

| Horizon | Status | User outcome | Depends on |
|---|---|---|---|
| 1. Complete personal delivery | Delivered in 0.3.0 | Take a real change from intent to an evidence-backed Delivery Dossier | Dev Flow 0.3.0 local controller and ledger |
| 2. Interactive workflow workbench | Planned | Manage many tasks, decisions, and reusable workflows from one cockpit | Horizon 1 artifacts and outcomes |
| 3. Isolated workspace orchestration | Planned | Run independent tasks through explicit in-place, branch, or worktree strategies | Horizon 2 authority model and a recoverable effect protocol |
| 4. Project-scale task and multi-agent orchestration | Planned | Decompose an initiative and coordinate parallel Codex executors | Horizons 2 and 3 |
| 5. Extended multi-repository delivery and continuous assurance | Planned | Add dependency-aware reuse and external quality systems to the shipped exact-set core | Horizons 1–4 |
| 6. Team delivery network | Planned | Hand off, assign, approve, audit, and optionally share task state | Stable task, artifact, identity, and permission protocols |
| 7. Open ecosystem and adaptive orchestration | Planned | Publish trusted delivery capabilities and receive explainable recommendations | Mature workflows, evidence, and team operating model |

## Horizon 1 — Complete personal delivery (delivered in 0.3.0)

### Delivered outcome

A developer takes a feature, bug fix, investigation, refactor, or fast change
from an initial contract through a reviewable and verified terminal result. The
orchestrator preserves the delivery process across sessions, assurance
findings, bounded repair cycles, and accepted scope revisions.

### Delivered capabilities

- Structured and minimal starts produce a bounded delivery contract with
  stable acceptance IDs.
- Repeated `--repo` binds one to eight exact canonical, user-prepared Git
  worktree roots as immutable task membership; the Hook resumes from any
  unambiguous member.
- Six official workflows provide fast, planning-led, investigation, refactor,
  and high-assurance personal delivery paths.
- Typed artifacts retain producer, contract, source snapshot, governing
  repository-scoped resources, input lineage, digest, and freshness.
- OpenSpec, codebase-memory, and independent review have declared available,
  degraded, and unavailable behavior while the controller remains tool-agnostic.
- Verification and review persist all attempts, consume finite rework budgets,
  and route exhausted work to an incomplete dossier.
- `dev-flow-workflow/0.3.0` definitions declare cancellation for a strict majority of normal
  nonterminal stages; delivery finalizers are never cancellable.
- Contract revisions create a new-contract revision source and reenter declared
  planning; decisions and exact waivers remain attributable and replayable.
- Repository-set verification exactly covers criteria, every member, and one
  integration result; any member drift invalidates aggregate assurance without
  partial proof reuse.
- Successful and incomplete Delivery Dossiers summarize current coverage,
  assurance, documentation, risks, decisions, provenance, and handoff, with
  canonical member diagnostics in Delivery Dossier 0.3.0.

### Delivery evidence

- Focused 0.3.0 journeys cover every official workflow, success and exhaustion,
  optional-driver available/degraded paths, cancellation, decisions, and
  contract-revision recovery.
- Restart and stale-binding paths preserve exactly one current action and
  reject evidence bound to outdated inputs or aggregate snapshots.
- Missing or moved members block repository-dependent progress without partial
  evidence until the exact persisted root is restored; stored-ledger inspection
  remains available.
- Acceptance coverage distinguishes proven, explicitly waived, and unverified
  criteria; self-review never becomes independent approval.
- Installed snapshot identity and real Hook/Skill pickup remain explicit
  release-evidence fields whenever those conditions require host observation.

## Horizon 2 — Interactive workflow workbench (planned)

### What becomes possible

A developer can manage several long-running tasks, see why each task is
waiting, make durable decisions, and compose project-specific delivery methods
as persistent product configuration.

### Key capabilities

- Add a local task cockpit through stable CLI/JSON views, then a TUI or local
  UI, showing search, filters, priority, tags, repository, owner, health,
  blockers, updated time, and next action.
- Provide task timelines, artifact and evidence explorers, recovery briefs,
  decision cards, approval inboxes, and why-next explanations.
- Add project profiles and task templates for default workflow, risk tier,
  assurance policy, tool capabilities, repository scope, and retention.
- Support named action outcomes such as approved, changes-requested, failed,
  waived, and blocked.
- Add conditional routing, optional stages, bounded retry and rework loops,
  pause, resume, block, retry, waive, approve, reject, and operator
  intervention.
- Bind every approval or waiver to the exact task, action instance, revision,
  artifact digest, actor, role, and scope.
- Provide `workflow validate`, `workflow explain`, and `workflow simulate`
  before task creation, including normal paths, alternate outcomes, required
  capabilities, permissions, artifacts, and exit conditions.
- Add reusable stage templates, typed inputs and outputs, subflows, assurance
  profiles, and a visual workflow and evidence graph.
- Support task clone, derivation, archive, export, and explicit retention while
  preserving active evidence.

### Milestone proof

- A user can operate several active and terminal tasks through explicit task
  identity and selection.
- `review → rework → re-review` is replayable and shows every attempt.
- An approval for an old plan, diff, or action instance always fails closed.
- Rework-budget exhaustion, unavailable approvers, waiver, abandonment, and
  operator takeover all have deterministic outcomes.
- At least three official workflow families reuse the same stage and artifact
  contracts.
- CLI, Hook, Skill, TUI, and any local UI show the same projection for the
  same revision and submit commands through the same controller.

## Horizon 3 — Isolated workspace orchestration (planned)

### What becomes possible

Multiple tasks can work safely in the same repository using different
workspace strategies, while the product can explain ownership, conflicts,
recovery, and every authorized Git effect.

### Key capabilities

- Let a task independently select in-place, an existing branch, an existing
  worktree, an explicitly authorized managed branch, or an explicitly
  authorized isolated worktree.
- Record workspace identity, owner, lease, repository, base ref, pinned
  baseline, intended change scope, creation receipt, and current health.
- Detect branch and worktree name collisions, overlapping paths, base drift,
  dirty user work, and conflicting task claims before work starts.
- Separate workspace planning from execution so users can preview exact
  changes and required permissions.
- Introduce a recoverable effect lifecycle:
  `intent → authorize → execute → receipt → reconcile`.
- Bind each Git permission to one operation and target. Merge, push, deletion,
  and cleanup each require their own authorization.
- Provide integration preview, change-set comparison, conflict reporting,
  abandonment, and exact-scope cleanup for resources owned by the task.
- Support attach-only and fully read-only operation as first-class choices.
- Require explicit authorization for stash, reset, clean, commit, push, merge,
  force-push, and deletion; deletion and cleanup are confined to task-owned
  resources.

### Milestone proof

- Every official workflow passes installed journeys for each claimed
  repository-topology and workspace-strategy combination.
- Crash after resource creation, lease expiry, name collision, base movement,
  user edits, dirty worktrees, and partial Git effects all have deterministic
  diagnosis and recovery.
- Ownership receipts limit every task's overwrite, adoption, and cleanup scope
  to its own resources.
- Concurrent tasks with separate worktrees preserve isolated task state and
  workspace leases.
- Permission receipts bind each authorization to one Git effect operation and
  target.

## Horizon 4 — Project-scale task and multi-agent orchestration (planned)

### What becomes possible

A large single-project requirement can be decomposed into dependent work
packages, assigned to parallel Codex workers, recovered independently, and
joined into one evidence-backed result.

### Key capabilities

- Introduce initiatives, parent and child tasks, milestones, explicit
  dependencies, batches, critical paths, and aggregate completion rules.
- Let Codex propose a task graph from the delivery contract and impact report;
  human confirmation authorizes each scope expansion and created work item.
- Expose a bounded runnable-action set at the project level while each claimed
  worker receives exactly one action.
- Add claim, lease, heartbeat, idempotent completion key, reassignment, retry,
  cancellation propagation, and operator takeover.
- Support sequential work, fan-out, fan-in, partial retry, optional children,
  integration barriers, and failure isolation.
- Give each worker a minimal context bundle containing its accepted scope,
  baseline, dependencies, artifacts, workspace, expected outputs, and join
  contract.
- Enforce concurrency budgets, workspace and repository leases, component
  ownership, and configurable resource limits.
- Provide a portfolio view of initiatives, runnable work, worker lanes,
  blocked dependencies, critical path, evidence gaps, and integration
  readiness.
- Keep author and independent reviewer roles separable and attributable.

### Milestone proof

- Each action instance has at most one concurrent owner.
- Worker failure and lease expiry recover with exactly-once completion
  accounting and durable accepted artifacts.
- Portfolio views retain completed siblings after a child failure, and retry
  schedules the outstanding work.
- Parent completion requires the exact mandatory child set and join evidence.
- Installed journeys cover sequential decomposition, fan-out/fan-in, partial
  failure, reassignment, cancellation, and operator takeover.
- Parallel execution demonstrates reduced lead time while preserving workspace
  isolation and a stable or lower unresolved-conflict rate.

## Horizon 5 — Extended multi-repository delivery and continuous assurance (planned)

### What becomes possible

Building on the shipped exact-set local core, one delivery plan can add
repository roles and dependency order, safely preserve independently reusable
proof, and return trustworthy evidence to Issue, PR, CI, and release systems.

### Key capabilities

- Enrich the existing exact repository set with roles, component scopes,
  ownership, dependencies, and integration order.
- Support monorepo component scopes as well as true multi-repository change
  sets.
- Model each repository's workspace strategy as an independent choice alongside
  workflow depth and the strategies selected by other repositories.
- Perform cross-repository impact analysis, dependency-aware planning,
  parallelizable implementation, per-repository verification, integration
  validation, and unified finalization.
- Extend dependency-aware reuse across imported CI and release evidence while
  retaining the current controller's slice-intersection and integration-closure
  invalidation rules.
- Add an assurance graph mapping every acceptance criterion to plans, code
  changes, focused tests, review findings, CI checks, integration results,
  documentation, and release artifacts.
- Track evidence provenance and freshness. Code, dependency, baseline, or
  configuration changes precisely invalidate their dependent evidence.
- Provide explicit connectors for OpenSpec, codebase-memory, issue trackers, Git
  hosts, CI systems, and artifact stores.
- Import external context and evidence; where a connector can mutate external
  state, require scoped authorization and a persisted receipt.
- Produce repository-level and aggregate PR-ready or release-ready dossiers,
  including dependency order, contract-conformance results, unresolved items, and
  handoff instructions.

### Milestone proof

- Real API/consumer, library/application, and coordinated rollout journeys cover
  chain, fan-out/fan-in, and partial-failure topologies.
- Role and dependency admission extends the shipped exact-set preflight without
  weakening canonical membership or missing-member recovery.
- Recovery preserves independently accepted per-repository proof and schedules
  precisely the dependency-invalidated units.
- Completion requires all mandatory per-repository evidence and global
  integration evidence.
- Code or dependency changes invalidate linked proof before execution
  continues.
- External timeout, permission denial, duplicate receipt, partial success, and
  offline recovery all produce safe resumable states.
- The validation matrix explicitly covers workflow depth, repository topology,
  workspace strategy, and execution topology as independent dimensions.

## Horizon 6 — Team delivery network (planned)

### What becomes possible

Development work can move between people, machines, and roles with its accepted
scope, decisions, artifacts, workflow identity, evidence, and current action
intact.

### Key capabilities

- Start with local, redacted, integrity-checked handoff bundles that another
  trusted installation can inspect and import.
- Add requester, implementer, reviewer, approver, operator, and workflow-owner
  roles.
- Support assignment, claim, review and approval queues, comments, mentions,
  notifications, decision deadlines, and explicit escalation.
- Publish project and organization policy packs for workflow selection,
  assurance levels, required reviewers, permissions, retention, and allowed
  connectors.
- Attribute actions, approvals, waivers, interventions, and external effects
  to an authenticated actor and exact revision.
- Provide team views for work awaiting implementation, review, approval,
  integration, handoff, or recovery.
- Add an opt-in shared task hub when identity, authorization, concurrency,
  privacy, offline operation, data ownership, availability, support, and
  deletion models have complete shipped contracts.
- For shared operation, provide authentication, RBAC, encryption, project and
  organization boundaries, event ordering, offline conflict handling, audit
  export, and retention controls.
- Keep every interface, including integrations and team UI, on the same
  controller authority and receipt model.

### Milestone proof

- Export and import preserve the requirement, projection, workflow identity,
  artifact digests, decisions, and pending action exactly.
- Redaction marks every removed required field and sets bundle completeness
  accordingly.
- Authorization policy confines protected artifact reads, work claims,
  approvals, waivers, and connector invocations to permitted actors.
- Concurrent approvals, duplicate requests, expired leases, offline changes,
  and service recovery preserve deterministic task history.
- A team can audit who decided, implemented, reviewed, approved, waived, and
  intervened in a delivery.
- Shared coordination is optional; personal local workflows retain their
  full supported capability.

## Horizon 7 — Open ecosystem and explainable adaptive orchestration (planned)

### What becomes possible

Teams can publish trusted development methods as reusable products, and the
orchestrator can recommend an explainable delivery strategy for complex work
within the explicitly accepted scope, assurance level, and authority.

### Key capabilities

- Provide an authoring studio for workflow, artifact, assurance, policy, and
  connector packages, with visual composition, validation, simulation,
  conformance fixtures, and contract/capability previews.
- Publish versioned workflow packs, capability manifests, project profiles,
  policy packs, and connector contracts.
- Add a trusted registry with signatures, provenance, permission previews,
  version/capability negotiation, pinning, revocation, health status, and
  reproducible installation.
- Define separate capability classes for data-only extensions, read-only
  drivers, and connectors that can produce external effects.
- Run third-party executable connectors outside the core controller through an
  isolated connector protocol with scoped requests and attributable responses.
- Scope connector access to declared repositories, network destinations,
  secrets, artifact types, operations, and retention rules.
- Recommend workflows, assurance profiles, task graphs, repository scopes,
  workspace strategies, concurrency budgets, reviewers, and integration gates
  from the requirement, impact surface, and local project policy.
- Identify likely blockers, missing evidence, stale decisions, rework risk,
  integration risk, and critical-path changes.
- Learn reusable project conventions from local, opt-in, accepted decisions
  and successful templates; local opted-in evidence is the learning source.
- Make every recommendation explainable, editable, rejectable, versioned, and
  replayable.
- Require native evidence and maintainers for launchers, locking, path safety,
  Hook behavior, installation, effects, and end-to-end journeys before adding
  a platform to native support.

### Milestone proof

- Contract, capability, and least-privilege checks gate every extension installation
  and invocation.
- Revocation takes effect when it is known locally or signed validity expires;
  temporary connector outages preserve task progress.
- A third-party connector is confined to its declared resources and leaves an
  attributable receipt for every effect.
- Workflow authors can build, simulate, publish, upgrade, diagnose, and revoke
  a package through package schemas and tooling.
- Explicit acceptance precedes every recommendation-driven permission grant,
  work creation, assurance change, or scope change.
- Controlled dogfood measures reductions in rework and delivery lead time
  alongside automation volume.

## Cross-cutting delivery foundations

Every feature horizon advances through the following enabling lanes. Each
horizon advances and verifies every applicable lane and records applicability
evidence across the full set.

| Foundation lane | Required product capability | Release evidence |
|---|---|---|
| Reproducible release | Validate the exact tracked candidate, identify every installed snapshot, and reproduce package, Skill, manifest, and documentation evidence | Every published version reproduces package, Skill, manifest, workflow identity, and bilingual documentation validation from its tracked tree |
| Identity and version authority | Separate release, state-format, workflow-language, selected-workflow, capability, connector, artifact, and agent-protocol identities; classify active tasks before a version change | Version-change simulation classifies every active task and verifies the owned identity domain for each decision |
| Diagnosis and data lifecycle | Provide `version`, `doctor`, exhaustive health inventory, stable error catalog, bounded support export, retention, archive, import, and exact-scope removal | A read-only health view inventories every task entry, installed snapshot, capability condition, and available recovery or removal action |
| Safety and recoverable effects | Bound inputs and locks; persist intent, authorization, receipts, retries, and reconciliation for external effects | Installed effect journeys prove scoped authority, idempotent receipt handling, interruption recovery, and exact resource ownership |
| Security and privacy | Default to local storage, least privilege, redaction, explicit data egress, secret isolation, actor attribution, and revocation | Handoff and connector journeys prove redaction, explicit egress, secret isolation, actor attribution, and revocation |
| Installed quality evidence | Map changed surfaces to the smallest focused tests, validate installed journeys, keep review evidence snapshot-bound, and publish validation evidence and support status for every claimed combination | Focused contracts and installed end-to-end journeys cover every claimed combination and bind review evidence to the exact snapshot |
| Platform and documentation evidence | Publish platform and interpreter claims backed by native evidence; keep installation, recovery, removal, and English/Chinese product documentation aligned | Every platform claim carries native installation, Hook, locking, path-safety, recovery, removal, and documentation-parity evidence |

## Product guardrails

Ambitious capability growth must preserve the properties that make delegation
trustworthy:

1. **The controller is the sole transition writer.** CLI, Hook, Skills,
   UIs, agents, and connectors all submit commands to the same authority.
   Terminal graph membership defines completion, and the Hook is advisory and
   passes control through on internal errors.
2. **One claimed worker receives one clear current action.** Current 0.3.0 has
   one Codex and one task-wide action even for multiple repositories. A future
   project graph may expose a bounded runnable set, with ownership explicit for
   every action.
3. **Artifacts and evidence carry lineage.** Proof names its inputs, baseline,
   producer, time, schema, and digest; changed inputs invalidate affected
   proof.
4. **Human authority is explicit and narrow.** Approval, waiver, and effect
   permission bind to an exact task, action, revision, actor, scope, and
   target.
5. **Effects are planned, authorized, receipted, and recoverable.** A host
   permission prompt requests host execution access; a controller-recorded
   workflow approval supplies workflow authority.
6. **User work changes through explicit, scoped authorization.** Stash, reset,
   clean, commit, push, force-push, and cleanup each require authorization;
   cleanup is confined to task-owned resources.
7. **Workflow depth, task topology, repository topology, workspace strategy,
   and collaboration mode remain independent product dimensions.**
8. **Task state resides outside target repositories.** Local-first operation
   and private data are the default; sharing and network access are opt-in and
   scoped.
9. **Extensions are declarative, versioned, and permissioned.** The core
   runtime is implemented entirely with the Python standard library and
   consumes extension capabilities through declarative contracts. Data packages
   carry a data-only privilege profile. Repository, secret, and mutation access
   each require an explicit capability declaration and authorization.
   Executable and networked connector logic runs outside the core controller
   behind an enforced capability boundary and isolated connector protocol.
10. **Data evolution follows shipped reality.** Transformations, recovery, and
    deprecation serve real persisted data and identified releases.

## Product measures

Measures come from installed acceptance evidence and opt-in local reports.

| Measure | Desired outcome |
|---|---|
| Evidence-complete delivery rate | Every accepted criterion has fresh proof or an explicit waiver at completion |
| Time to first safe action | A requirement reaches a risk-appropriate, authorized next action with minimal setup |
| Resume reliability | Interrupted personal, child, workspace, and multi-repository tasks resume at the same valid intent |
| Rework convergence | Failed verification and review findings close through bounded repair within the persistent task |
| Human decision latency | Approval and exception queues make waiting visible and shorten decision wait cycles |
| Parallel delivery effectiveness | Multi-agent work reduces lead time while preserving single ownership, workspace isolation, and stable or declining unresolved-integration risk |
| Multi-repository integration success | Partial work resumes safely and the exact change set reaches verified integration |
| Handoff fidelity | Imported work preserves scope, decisions, artifacts, evidence, and pending actions |
| Workflow reuse | Official and project workflow packs replace repeated prompt assembly while preserving fit and assurance |
| Stale-proof prevention | Changed inputs invalidate affected evidence before completion or delivery |

## Roadmap governance

- Keep the current and next horizon detailed; promote later outcome and
  capability contracts into detailed planning when their entry evidence is
  ready.
- Promote a feature through an OpenSpec change that defines personas, the
  installed user journey, independent product dimensions, authority, data and
  effect lifecycle, failure and recovery, privacy, and measurable proof.
- Use real dogfood and external user evidence to prioritize within a horizon.
  Available evidence determines sequencing while the north-star product
  direction remains stable.
- Maintain the cross-cutting foundations as release gates for every affected
  feature.
- Keep `ROADMAP.md` and `ROADMAP_CN.md` semantically aligned.
- Keep the roadmap centered on shipped capability and product
  commitments; record completed implementation detail in release records.

## Definition of done for a roadmap capability

A capability is complete when all of the following hold:

1. its promised user outcome works in an installed plugin;
2. every supported combination in the capability matrix has explicit
   acceptance evidence;
3. interruption, concurrency, permission denial, partial effects, retry,
   recovery, cancellation, and operator intervention relevant to the
   capability are handled;
4. authority, state ownership, artifact lineage, workspace ownership, effects,
   privacy, and dependency direction are explicit;
5. the smallest focused contract tests and installed end-to-end journeys pass;
6. diagnosis, version evolution, recovery limits, retention, removal,
   packaging, and bilingual documentation are updated where affected; and
7. an independent read-only review confirms that implementation, evidence, and
   the roadmap outcome agree.
