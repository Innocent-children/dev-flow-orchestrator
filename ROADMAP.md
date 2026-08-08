# Dev Flow Orchestrator Roadmap

[Simplified Chinese](ROADMAP_CN.md) · [简体中文](ROADMAP_CN.md)

## Product direction

Dev Flow Orchestrator provides one local Controller authority for resumable,
verifiable development across an exact set of one to eight user-prepared Git
worktrees. It is a personal multi-repository controller with one task, one
current action, and one Codex executor. Partial assurance reuse remains bounded
to current, provably disjoint task-owned slices. Autonomous Git management,
parallel execution, remote operation, external CI, and delivery automation stay
outside the current product boundary.

Delivery proceeds in small compatible steps. Added complexity must answer a
concrete current requirement; speculative platform, orchestration, or ecosystem
work remains deferred.

## Release 0.5.0: MCP interface migration

Release `0.5.0` moves the primary Codex integration from installed Skills and a
fail-open Hook to one local STDIO MCP server. The persisted model and task-data
namespace remain exactly `0.4.0`, so existing 0.4.x tasks resume without state or
byte migration.

### Current implementation

- one `dev-flow` server and exactly eleven typed Controller tools: five reads
  and six mutations;
- bounded discovery, stored task inspection, live current-action capture, start,
  apply, contract revision, decision, finding disposition, and cancellation;
- closed schemas, compact results, versioned current-action guidance, request
  IDs, redaction, same-task mutation serialization, bounded admission, and
  uncertain-completion recovery;
- protocol-only stdout, bounded stderr diagnostics, first-excess rejection, and
  fail-closed handling for malformed JSON/UTF-8, cancellation, and disconnects;
- an isolated managed runtime outside source and task data, with the official
  MCP SDK bounded to major 2, an exact resolved lock and identity-bound receipt,
  staged activation, and reuse only for an exact matching identity;
- bundled plugin mode and explicit standalone registration using the same PATH
  launcher, with duplicate-registration rejection;
- removal of current Skills, Hooks, Hook bootstrap, and the Hook-specific
  launcher;
- macOS installation, repair, rollback, and uninstall paths, plus native Windows 10
  22H2 x64 / Windows 11 x64 PowerShell preview paths;
- the unchanged CLI and the first read-only slice delivered as a local read-only
  Web UI over the same Controller. The broader interactive workbench and Web UI
  mutation or approval authority remain planned.

### Current local evidence

The current macOS source- and managed-launcher journey evidence exercises the
official MCP client over real STDIO and keeps protocol, guidance, Controller,
and persisted-model authority separate. It covers:

- initialization, bounded instructions, the exact eleven-tool catalog, all tool
  mappings, closed inputs and outputs, domain/protocol errors, result limits,
  request IDs, redaction, concurrency, cancellation boundaries, stdout purity,
  bounded stderr, and disconnect recovery without blind mutation replay;
- bounded guidance for preflight, impact, planning, implementation,
  investigation, documentation, rework, assurance/review, finalization,
  cancellation, and the closed generic fallback;
- exact-lock managed-runtime creation, installed-wheel smoke, receipt matching,
  safe reuse, staged activation, failed-build/activation rollback, duplicate
  registration rejection, and marker-scoped uninstall preservation;
- source-confirmed focused and closed-trigger routes for all six official
  workflows, with profile floors, obligation allowances and ceilings,
  not-required decisions, review rules, and terminal Delivery Dossiers;
- one-member and exact multi-member delivery, secondary-member discovery,
  restart/resume, and uncertain disconnect recovery;
- resume of a task created by the 0.4.2 CLI without migration, governing OpenSpec
  available/stale/unavailable paths, conservative codebase-memory degradation,
  causal review, bounded rework, waiver and disposition, impact-gap observation,
  exact restoration, re-planning and implementation re-execution, contract
  revision with exact adopted drift, corrupt-inventory admission failure, and
  concurrent admission from distinct linked worktrees;
- activation and idempotent repair in a fully isolated Codex 0.146.0 profile,
  exactly one enabled bundled `dev-flow` STDIO registration, default
  installed-data discovery of an existing `0.4.0` task, and the full workflow
  journey through the managed PATH launcher; marker-scoped uninstall then
  removed the plugin, registration, launchers, and runtime while preserving the
  source and byte-identical current/prior-version task namespaces;
- focused domain regressions for partial assurance reuse, exhaustion, and
  successful or incomplete Dossier finalization.

This macOS and current-host evidence is not native Windows evidence, and the
isolated profile does not establish that a different external Codex installation
has enabled the server. Release evidence is complete only when strict OpenSpec
validation, package validation, full unittest discovery, lifecycle checks, and
every claimed native platform result are current. A Windows Server runner,
static PowerShell checks, WSL/Wine, or skipped tests do not satisfy the Windows
10/11 client gate.

## Near-term hardening

1. Before any future official MCP SDK upgrade, retain the bounded supported
   major, update the exact lock deliberately, and rerun protocol, managed-runtime,
   installed-journey, lifecycle, and package compatibility evidence.
2. Complete the fresh-install, repair, fast-forward-upgrade, failed-build,
   failed-activation, duplicate-registration, task-resume,
   installed-MCP-workflow, and safe-uninstall matrix for both preview Windows
   client versions on native hosts.

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
- treat MCP annotations as enforcement or automatically grant mutation approval;
- change model `0.4.0` identity merely to evolve the transport interface.

Any future proposal that changes these boundaries must state the concrete user
value, authority model, failure recovery, compatibility impact, and evidence
cost before implementation.
