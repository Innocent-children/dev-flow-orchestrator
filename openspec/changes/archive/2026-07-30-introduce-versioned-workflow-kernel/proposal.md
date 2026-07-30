## Why

Dev Flow already provides durable state, evidence-bound approvals, deterministic
Git safety, and recovery, but the workflow definition is repeated
across controller constants, transition guards, CLI handlers, hooks, and skill
documentation. Adding or changing a workflow node therefore requires coordinated
edits in many places, while Codex repeatedly receives workflow data that is not
needed for the current action.

This change introduces a single versioned workflow definition and a constrained
execution contract so that nodes can be added or composed without weakening the
existing deterministic kernel. It also creates compact, typed Codex integration
surfaces and deterministic repository-level fan-out/fan-in for multi-project
implementation.

The current implementation successor is workflow generation V4:
`full@4` and `lite@4`. Workflow generation and task persistence schema are
independent version axes, so V4 tasks still use task schema v3. The already
reserved `full@3` and `lite@3` bundle and handler identities remain immutable
historical package content. Their reservation crossed the identity boundary,
but it did not establish an independent review, reproducible handoff,
publication, installation, activation, or pin eligibility; those external
facts remain unproven and MUST NOT be inferred from the ledger.

## What Changes

- Add package-owned, versioned workflow bundles whose graph, handler contracts,
  playbooks, and schemas are canonically hashed by an exact portable byte
  contract, validated for this release on macOS, and pinned by each activated
  schema-v3 task.
- Introduce `full@4` and `lite@4` as safety successors while retaining task
  schema v3, and preserve every V3 reservation, bundle, and transitive handler
  identity without substitution or deletion.
- Add a validated workflow catalog and sealed registries for commands, guards,
  reducers, gates, and node executors.
- Route all workflow movement through one transition engine while retaining the
  existing task lock, revision CAS, approval intent, evidence, durable outbox,
  mutation quarantine, and recovery mechanisms.
- Separate task lifecycle, node-instance lifecycle, and executor runtime handles
  so deterministic nodes, Codex workers, external tools, barriers, and human
  gates can share one workflow contract.
- Add compact `agent-v1` task projections and mutation receipts that return only
  the current node, legal next actions, required sections, and artifact
  references.
- Add a thin typed MCP adapter, with the existing JSON CLI retained as a
  standalone compatibility and recovery surface.
- Extend lifecycle hooks for subagent and compaction context while keeping hooks
  advisory and fail-open.
- Add deterministic multi-repository map/join scheduling. Repository workers may
  edit only their assigned worktrees when the host proves worker isolation;
  short-lived manager capabilities keep the manager as the sole authorized
  agent-plane controller writer, with a serial fallback when isolation is
  unavailable.
- Preserve schema-v1 and schema-v2 task behavior through immutable legacy
  workflow adapters. Existing active tasks are never migrated in place.
- Treat any discovered task pinned to reserved but never activated
  `full@3`/`lite@3` as a fail-closed historical task: preserve its exact state,
  journals, receipts, scopes, worktrees, bundle, and handlers; permit bounded
  inspection and only identity-complete target-bound safety controls; never
  advance it with V4 semantics or start another protected effect.
- Make the complete transitive recovery implementation part of handler and
  bundle identity. `ABANDONED` requires controller-owned, target-bound live
  evidence, while `COMPENSATED` requires both the pinned workflow gate and a
  host-owned opaque one-shot approval for the exact compensation invocation.
- Define absence of that trusted host authority as a supported fail-closed
  recovery boundary: the current attempt returns scope-blocking `UNRESOLVED`
  plus a bounded operator-intervention packet, stops and asks the user to
  inspect or operate, and never automatically redispatches, compensates, or
  unblocks. A user, model, worker, or caller assertion is not proof. A later
  authenticated original runtime, verifiable stored receipt, or future trusted
  host authority may support a fresh attempt; trusted `ABANDONED` and
  `COMPENSATED` success are optional capabilities and are not claimed by this
  macOS release. The complete packet has an enforceable 4,096-byte
  semantic-JSON limit; overflow or corrupt durable input fails closed with an
  exact inspection locator and no partial/truncated safety projection.
- Extend release provenance without rewriting history: the existing
  `first-introduction.json` remains immutable, later introductions use chained
  successor/introduction-epoch provenance, and ledger reservations are
  append-batches whose prior prefix is byte-for-byte immutable rather than a
  globally re-sorted set.
- Preserve the standard-library-only controller runtime and validate this V4
  delivery on macOS only. Windows and Linux remain outside this change's
  release evidence and support claims.

## Delivery Strategy

The remaining work is divided into non-release milestones documented in
`MILESTONES.md`. V4-M0 completes only the release-ledger successor and
introduction-epoch provenance contracts in tasks 13.5 and 13.6, validates them
as one internal candidate, and then stops. V4-M1 is a conditional, inactive
local preview for V4 bundle/catalog identity and V3 fail-closed inspection.
V4-M2 completes the full local recovery and activation-readiness closure while
all V4 profiles remain inactive. For this macOS delivery, that closure requires
the safe operator-intervention behavior when trusted host authority is absent;
it does not require or claim a trusted-host `ABANDONED` or `COMPENSATED`
success path. V4-RC alone performs the ordered final freeze and macOS evidence
sequence. The independent
`complete-cross-platform-support` change remains separate and is not a
release-order prerequisite for this macOS-only V4 delivery.

These labels do not satisfy OpenSpec tasks or establish a release fact. In
particular, V4-M0 and V4-M1 do not reserve, install, publish, hand off, activate,
or make a workflow pin-eligible, and they do not weaken any lock, CAS, proof,
nonce, quarantine, reconciliation, compensation, or zero-redispatch
requirement.

## Capabilities

### New Capabilities

- `versioned-workflow-bundles`: Defines immutable workflow graphs, bundle
  identity, compatibility, validation, and task pinning.
- `pluggable-workflow-execution`: Defines node types, sealed handler registries,
  transition execution, reducer boundaries, and node lifecycle behavior.
- `compact-agent-protocol`: Defines typed, bounded task projections, receipts,
  context locators, and artifact-reference behavior for Codex clients.
- `codex-runtime-adapters`: Defines the CLI, MCP, hook, Skill, subagent, and
  optional headless executor boundaries without transferring state authority
  away from the controller.
- `multi-repository-orchestration`: Defines deterministic repository fan-out,
  worker ownership, dependency barriers, result collection, and serialized state
  commits.

### Cross-change coordination

This change declares no modified capability owned by another active change.
The independent `complete-cross-platform-support` change is not modified,
completed, or used as a release-order prerequisite here. This change's own
`codex-runtime-adapters` and package-verification Requirements specify the
macOS delivery behavior. Archiving either change MUST NOT copy, move, or
silently satisfy the other change's tasks.

## Impact

- Controller runtime: workflow constants, guards, reducers, gate handling,
  command registration, task schemas, and response projections.
- Plugin integration: manifest, bundled MCP configuration, hooks, Skill
  instructions, node playbooks, and package inventory.
- State compatibility: new tasks use a version-pinned workflow reference while
  schema-v1 and schema-v2 tasks continue through frozen legacy adapters; v3
  remains the task schema for V4; `full@4`/`lite@4` creation stays disabled per
  profile until complete equivalence and recovery readiness is proven, and
  reserved inactive V3 identities remain resolvable but fail closed.
- Tests and validation: graph validators, golden transition vectors, shadow
  equivalence tests, response-size budgets, multi-repository scheduling tests,
  package and candidate validation, append-epoch/provenance validation, and the
  active change's ordered V4 candidate, handoff, native macOS, review, and
  focused CI evidence. Full suites are prohibited. Completed V3 reservation and
  local freeze steps are historical facts only; unfinished external V3
  evidence is not inherited by V4.
- Runtime dependencies: no third-party dependency is added to controller or hook
  runtime code. Optional SDK or Agents Runtime integrations remain separate
  adapters and are not required for normal plugin operation.
