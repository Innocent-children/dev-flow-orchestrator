# Dev Flow Orchestrator Roadmap

[Simplified Chinese](ROADMAP_CN.md)

## Product direction

Dev Flow Orchestrator provides one local Controller authority for resumable,
verifiable development across an exact set of one to eight user-prepared Git
worktrees. It is a personal multi-repository controller with one task, one
current action, and one Codex executor. Partial assurance reuse remains bounded
to current, provably disjoint task-owned slices. Autonomous Git management,
parallel execution, remote operation, external CI, and delivery automation stay
outside the product boundary.

Delivery proceeds in small compatible steps. Added complexity must answer a
concrete current requirement; speculative platform, orchestration, or ecosystem
work remains deferred.

## Release 0.5.0: MCP interface migration

Release `0.5.0` moved the primary Codex integration to one local STDIO MCP
server. Release `0.6.0` added the formal bundled `dev-flow` Skill. The persisted
model and task-data namespace remain exactly `0.4.0`, so existing 0.4.x tasks
resume without state or byte migration.

The stable product surface remains one `dev-flow` MCP server with five read and
six mutation tools, the existing CLI, and the local read-only Web UI. The Skill
provides activation and routing; the Controller retains all transition,
repository, binding, assurance, review, and Delivery Dossier authority.

## Release 0.6.8 delivery: hardened versioned release artifacts

Installed delivery is moving from a permanently retained source checkout to an
exact-version GitHub Release asset set:

- one closed platform-neutral archive containing the complete sealed plugin,
  one pure-Python wheel, hash-locked requirements, the generating `uv.lock`,
  versioned lifecycle helpers, and an embedded manifest;
- one closed `release-index.json` binding the repository, version, source
  commit/tree publication assertions, archive, and raw manifest digest;
- version-matched `install.sh` and `install.ps1` bootstraps embedding identical
  standard-library Phase A verification;
- managed releases selected only by one active record, with stable
  `dev-flow`, `dev-flow-mcp`, and `dev-flow-uninstall` dispatchers;
- one installation-wide lifecycle lock, monotonic generation and digest CAS,
  bounded transaction journals, and only `committed`, `rolled_back`, or
  `partial` terminal outcomes;
- exact-version healthy or drift repair, target-version upgrade, automatic
  immediate-previous rollback for failed activation, interrupted recovery,
  bounded predecessor migration, and source-independent uninstall.

Phase A verifies the pinned index before parsing and validates the archive,
portable paths, tar headers, hard limits, safe extraction, raw manifest,
complete inventory, and static topology before artifact code executes or
product state changes. Phase B uses the supplied wheel and hash-required
wheel-only dependencies, builds a candidate, and completes staged health before
provisional plugin and marketplace activation.

The Phase A to Phase B boundary accepts only closed destination options, rejects
abbreviations and duplicates, derives the Phase B artifact root from the
versioned lifecycle location, and repeats complete live-inventory verification
before candidate work. Native Windows lock admission shares the bounded timeout
and cancellation semantics used by POSIX. Promotion keeps uploads in a
journaled Draft Release until authenticated official-API re-download and full
component verification succeed.

The lifecycle preserves `.codex-plugin/plugin.json`, `.mcp.json`, the bundled
`skills/dev-flow/**`, `dev-flow-mcp --stdio`, the Controller model, MCP tools and
schemas, plugin ID, personal-marketplace mode, task data, unrelated Codex state,
unknown content, and every legacy checkout.

SHA-256 proves agreement with bytes pinned by the bootstrap, index, and
manifest. It is not an independent signature or a claim that GitHub release
publication can never be compromised. Source commit and tree values are release
builder assertions; end-user installation does not reconstruct provenance from
a checkout.

## Completion evidence

The release-artifact change is complete only after all four final assets are
built and re-downloaded from their exact official version-specific locators and
all applicable repository checks pass. The bounded final-artifact journey must
run once on native macOS and once on native Windows 10 22H2 x64 or Windows 11
x64, covering fresh install,
healthy and drift repair, successful upgrade, failed-activation rollback,
interrupted recovery, startup, predecessor migration, uninstall, and task-data
preservation.

Supported Python 3.10–3.14 receives lightweight wheel-only install and
import/MCP smoke coverage rather than a repeated full lifecycle matrix.
Concurrency evidence covers only upgrade versus upgrade and upgrade versus
uninstall. A release candidate uses a real Codex host for exact plugin
read-back, bundled Skill discovery, STDIO MCP startup, and uninstall.

Full unittest discovery is part of repository evidence but does not replace
installed lifecycle evidence. Current-host macOS tests, deterministic
fake-Codex integration, and static PowerShell inspection do not establish
native Windows, real Codex, or final
promotion evidence. Those gates remain unverified until they run in their
required environments and their failures, skips, retained paths, degradations,
and platform limitations are recorded. Windows Server is not a supported
client-evidence substitute.

## Later product work

Potential later work is evaluated independently and is not implied by the
current release:

- richer read-only cockpit views for timelines, artifacts, approvals, and
  why-next explanations;
- additional local MCP host support after executor behavior and approval
  semantics are verified;
- better operator diagnostics for catalog and receipt mismatches;
- platform expansion backed by native installation and lifecycle evidence;
- selective workflow or guidance improvements driven by observed task failures.

## Explicit non-goals

The roadmap does not authorize Dev Flow to:

- create, switch, repair, or delete user branches/worktrees;
- commit, push, open pull requests, publish releases, or trigger external CI;
- coordinate parallel agents or repository executors;
- expose generic shell, raw Store, arbitrary filesystem, or remote MCP tools;
- treat MCP annotations as enforcement or automatically grant mutation
  approval;
- change model `0.4.0` identity merely to evolve installation or transport;
- add independent signing, Sigstore, transparency logs, offline fresh install,
  third-party mirrors, automatic update channels, or background updates;
- add public arbitrary-history rollback, unbounded release retention, general
  Unicode artifact members, migration of every historical installer, or a
  dispatcher-protocol migration framework.

Any future proposal that changes these boundaries must state the concrete user
value, authority model, failure recovery, compatibility impact, and evidence
cost in a separate OpenSpec change before implementation.
