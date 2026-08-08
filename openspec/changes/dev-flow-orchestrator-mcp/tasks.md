# Tasks: Introduce an MCP-first runtime

## 0. Change controls and baseline

- [x] 0.1 Pin the implementation baseline to the reviewed authoritative `main`
  commit and record its current `RELEASE_VERSION`, `MODEL_VERSION`, workflow catalog,
  package manifest, Python range, and installed lifecycle assets.
- [ ] 0.2 Run the complete pre-change test suite on macOS and the focused native
  Windows suite; preserve the command, environment, and results as baseline evidence.
- [x] 0.3 Run `openspec validate dev-flow-orchestrator-mcp --strict` and resolve all
  proposal/spec structural issues before production code changes.
- [x] 0.4 Create a traceability table from every Requirement/Scenario in this change
  to one or more tests; fail package validation when a stable MCP tool or lifecycle
  requirement lacks coverage.
- [x] 0.5 Confirm that no concurrent OpenSpec change modifies the same plugin manifest,
  installer authority, Hook removal, Python floor, or release-version authority.

## 1. Version and product authorities

- [x] 1.1 Set the target release authority to `0.5.0` using the existing release-bump
  mechanism.
- [x] 1.2 Keep `MODEL_VERSION` exactly `0.4.0` and add tests proving the release bump
  does not modify model schemas, namespaces, workflow documents, policy documents,
  bindings, records, findings, or Dossier identities.
- [x] 1.3 Add constants for `dev-flow-mcp/1.0.0`,
  `dev-flow-mcp-result/1.0.0`, `dev-flow-mcp-action/1.0.0`, and
  `dev-flow-mcp-guidance/1.0.0` outside the persisted-model identity.
- [x] 1.4 Raise the supported Python metadata and public runtime boundary to
  `>=3.10,<3.15`; update classifiers and all platform matrices.
- [x] 1.5 Add the official MCP Python SDK v2 with an upper major bound and update the
  exact dependency lock.
- [x] 1.6 Add validation that Controller, Engine, Store, GitClient, workflow, delivery,
  review, snapshot, and model modules do not import the MCP SDK or its transitive
  framework packages.

## 2. Shared runtime paths and ownership

- [x] 2.1 Extract data-directory resolution from CLI/Hook-specific code into a neutral
  module with documented precedence for explicit argument, environment override,
  plugin-compatible root, and existing `CODEX_HOME` default.
- [x] 2.2 Preserve the exact current `0.4.0` data namespace and repository/data
  disjointness checks.
- [x] 2.3 Add a managed-runtime path resolver outside both the verified source checkout
  and task-data root for POSIX and Windows.
- [x] 2.4 Define and validate a runtime receipt containing release version, source
  commit, Python executable/version/architecture, dependency-lock digest, MCP launcher
  identity, and activation timestamp.
- [x] 2.5 Add tests for paths with spaces, valid Unicode, apostrophes, different drives,
  symlinks/reparse points within the supported boundary, and absent-yet-creatable
  runtime/data roots.
- [x] 2.6 Add tests proving no MCP result, normal stderr diagnostic, or installation
  receipt presented to the model exposes the Controller data-root path.

## 3. MCP package skeleton and lifecycle

- [x] 3.1 Add `src/dev_flow_orchestrator/mcp/` with `server`, `runtime`, `application`,
  `schemas`, `tools`, `guidance`, `results`, `concurrency`, and `logging` modules.
- [x] 3.2 Construct one `MCPServer` with stable server name, release version, bounded
  initialization instructions, tools capability, and no Resources, Prompts, sampling,
  elicitation, task augmentation, or remote transports.
- [x] 3.3 Add `scripts/dev_flow_mcp.py` and native POSIX/Windows launchers supporting
  `--stdio`, `--data-dir`, and bounded logging configuration only.
- [x] 3.4 Reject HTTP/SSE/host/port/token/OAuth options with an explicit unsupported
  runtime error and no listening socket.
- [x] 3.5 Ensure stdout remains protocol-only from import through shutdown; route all
  diagnostics to stderr.
- [x] 3.6 Add clean startup, initialize, EOF, disconnect, cancellation, shutdown, and
  restart behavior.
- [x] 3.7 Add a startup self-check for supported Python, compatible MCP SDK major,
  current release/model/interface identities, data namespace availability, and tool
  catalog/guidance digests.
- [x] 3.8 Add protocol tests using the official client/stdio harness and an
  MCP-Inspector-compatible test command.

## 4. Transport schemas and result contracts

- [x] 4.1 Define closed input models for all eleven stable tools with explicit required
  fields, enums, count/byte limits, and `additionalProperties: false` semantics.
- [x] 4.2 Reuse current domain validators for contract, payload, binding, decision,
  finding disposition, and repository semantics instead of duplicating or weakening
  them in Pydantic/SDK models.
- [x] 4.3 Define the common structured success/error envelope and per-tool output
  schemas.
- [x] 4.4 Return one concise text content item in addition to structured content; add
  tests preventing full JSON duplication in text.
- [x] 4.5 Map every `DevFlowError` to `isError: true` with unchanged domain code,
  bounded details, and deterministic recovery kind where applicable.
- [x] 4.6 Map malformed protocol/unknown tool/transport-schema failures to SDK/MCP
  protocol errors without calling the Controller.
- [x] 4.7 Map unexpected exceptions to redacted `INTERNAL_ERROR` results with request
  IDs and stderr-only tracebacks.
- [x] 4.8 Add uncertain-completion recovery for disconnect/cancellation after a
  mutation may have committed; prohibit automatic mutation retries.
- [x] 4.9 Test duplicate keys, unsupported schema versions, NaN/Infinity, invalid UTF-8,
  first-excess limits, unknown fields, and nested invalid domain values.

## 5. Bounded Controller inspection APIs

- [x] 5.1 Add or formalize a bounded Controller server-info/product view that exposes no
  source/data paths.
- [x] 5.2 Add or formalize a paginated task-summary inventory view that isolates corrupt
  entries and does not perform full live Git capture.
- [x] 5.3 Add or formalize a stored single-task summary view with immutable repository
  membership, effective contract summary, current node, outstanding governance
  summary, and terminal Dossier summary.
- [x] 5.4 Add an MCP compact current-action projection derived from the authoritative
  `dev-flow-agent/0.4.0` projection without persisting a new model object.
- [x] 5.5 Maintain an explicit field-use manifest proving that every field required by
  current action guidance, payload construction, binding, driver, obligation, review
  contract, and governing resource is retained.
- [x] 5.6 Fail with `MCP_RESULT_LIMIT` rather than truncating a binding or omitting
  required action context.
- [x] 5.7 Add tests proving the new Controller methods are MCP-independent and remain
  callable by CLI/Web tests without importing the SDK.

## 6. Read-only MCP tools

- [x] 6.1 Implement `dev_flow_server_info` with release/model/interface identity,
  workflow IDs, transport, Python range, catalog digests, and bounded health.
- [x] 6.2 Implement `dev_flow_list_tasks` with status/workflow/terminal filters, opaque
  cursor, default limit 20, maximum 100, stable ordering, and inventory diagnostics.
- [x] 6.3 Implement `dev_flow_find_tasks_for_path` using the existing canonical path,
  active-task, lease-conflict, corrupt-entry, multi-member, and terminal exclusion
  semantics.
- [x] 6.4 Implement `dev_flow_get_task` using only the bounded stored view.
- [x] 6.5 Implement `dev_flow_get_next_action` using complete repository-set capture,
  exact current binding, compact current-action projection, and current guidance.
- [x] 6.6 Mark all read tools read-only, non-destructive, idempotent, closed-world, and
  task-augmentation-forbidden.
- [x] 6.7 Add read-tool tests for one/multiple/no task, secondary-member discovery,
  terminal exclusion, corrupt inventory isolation, overlapping invalid inventory,
  Windows equivalent path spelling, stale workspace, and result bounds.

## 7. Mutation MCP tools

- [x] 7.1 Implement `dev_flow_start_task` by calling `Controller.start` directly with
  immutable repository array, workflow, requirement, optional task ID, and optional
  accepted contract.
- [x] 7.2 Ensure start does not silently combine creation with a second live projection
  mutation or report rollback when a later read fails.
- [x] 7.3 Implement `dev_flow_apply_action` with exact task ID, action ID, payload, and
  unmodified current binding; do not infer any value from server memory.
- [x] 7.4 Implement `dev_flow_revise_contract` with current ownership claims, reason,
  actor label, and existing Controller revision/snapshot authority.
- [x] 7.5 Implement `dev_flow_record_decision` as a separate exact decision mutation.
- [x] 7.6 Implement `dev_flow_dispose_finding` with exact disposition and explicit
  actor authorization input required by the current Controller.
- [x] 7.7 Implement `dev_flow_cancel_task` only through current stage-declared
  cancellation semantics.
- [x] 7.8 Mark start/apply as non-read-only, non-idempotent, non-destructive hints and
  governance/cancel tools as non-read-only, non-idempotent, destructive hints; mark all
  closed-world and task-augmentation-forbidden.
- [x] 7.9 Add parity tests comparing each CLI and MCP mutation's canonical state,
  revision, records, bindings, domain errors, and atomic failure behavior.
- [x] 7.10 Add stale binding, revision conflict, unstable snapshot, missing member,
  invalid repository set, active lease, exhausted budget, invalid decision,
  unauthorized disposition, unavailable cancellation, and terminal-task tests.

## 8. Guidance catalog and context controls

- [x] 8.1 Implement the exact server initialization instruction with the complete
  discovery/get-next/execute/apply sequence in the first 512 characters.
- [x] 8.2 Keep total server instructions at or below 4 KiB UTF-8 and prohibit workflow
  manuals or examples that belong in current-action guidance.
- [x] 8.3 Create a versioned guidance catalog for every official current action kind,
  including preflight, impact, planning, implementation/rework/documentation,
  assurance, review, governance, finalization, and cancellation.
- [x] 8.4 Generate `dev-flow-mcp-guidance/1.0.0` from the current projection and only the
  applicable catalog entry.
- [x] 8.5 Include objective, must-read fields, allowed effects, required evidence,
  payload notes, driver rules, stale recovery, completion rule, and canonical guidance
  digest while staying at or below 8 KiB.
- [x] 8.6 Replace impact Skill guidance with current action guidance that keeps
  baseline/current codebase-memory projects separate and requires source confirmation.
- [x] 8.7 Replace follow Skill OpenSpec guidance with current machine-readable status,
  instruction, concrete path/digest, source-stage, and fallback rules.
- [x] 8.8 Replace review Skill guidance with a canonical package artifact and preserve
  review guidance snapshot/digest binding semantics.
- [x] 8.9 Add validation that every official/custom action template maps to one safe
  guidance entry or a closed generic fallback and that no guidance contradicts its
  payload schema or workflow authority.
- [x] 8.10 Add package tests rejecting instructions/guidance that tell the model to read
  MCP source, CLI source, Skills, Hooks, state files, or raw data directories.
- [x] 8.11 Enforce the 512-byte per-tool-description, 32-KiB tools-list, 128-KiB
  compact action, 512-KiB structured result, 256-KiB inventory/discovery page,
  4-KiB text summary and stderr-event, and other context budgets defined in design.

## 9. Concurrency, cancellation, and logging

- [x] 9.1 Add an in-process coordinator with four immediate-admission live/mutation
  slots and no request queue, without replacing Store/membership/CAS authority.
- [x] 9.2 Serialize same-task mutations and define bounded behavior when another live
  capture or mutation is in progress.
- [x] 9.3 Add cancellation checkpoints before capture, between bounded capture phases
  where supported, and before Controller commit.
- [x] 9.4 Ensure cancellation after commit never reports rollback; return read-after-write
  recovery.
- [x] 9.5 Add request IDs to all tool calls and stderr events.
- [x] 9.6 Redact data roots, environment values, contracts, bindings, repository file
  contents, and secrets from default logs.
- [x] 9.7 Add file-descriptor-level tests that fail on any non-protocol stdout byte and
  verify bounded stderr under expected and unexpected failures.

## 10. Plugin and standalone packaging

- [x] 10.1 Add root `.mcp.json` with exactly one `dev-flow` STDIO server invoking the
  installed `dev-flow-mcp --stdio` launcher.
- [x] 10.2 Update `.codex-plugin/plugin.json` to reference `./.mcp.json` through
  `mcpServers`, remove `skills`, and ensure no default/explicit Hook asset is packaged.
- [x] 10.3 Keep plugin identity, author, repository, license, release version, and
  interface capabilities synchronized with release authority.
- [x] 10.4 Add validation that all manifest paths are relative, inside the plugin root,
  and point to present candidate content.
- [x] 10.5 Document bundled mode and direct standalone registration using the same PATH
  launcher.
- [x] 10.6 Add duplicate detection for an enabled standalone Dev Flow registration plus
  enabled bundled mode; report deterministic recovery and do not claim healthy
  activation.
- [x] 10.7 Ensure the installer never creates both registration modes or silently edits
  unrelated MCP/plugin policy.
- [x] 10.8 Add plugin-scoped approval examples while preserving user authority over
  approvals and never granting blanket mutation approval automatically.

## 11. Managed runtime installation and uninstallation

- [x] 11.1 Extend candidate package validation to verify the MCP source, dependency lock,
  launchers, `.mcp.json`, manifest, guidance catalog, tests, and runtime bootstrap
  before any candidate code executes.
- [x] 11.2 Extend macOS and Windows installers to locate supported 64-bit CPython
  3.10–3.14 and fail before activation on unsupported versions/architecture.
- [x] 11.3 Build a temporary isolated MCP runtime outside source and task data using the
  exact lock; bind it to verified source commit and release.
- [x] 11.4 Run import, initialize, instructions, tool catalog, one read call, and one
  isolated mutation smoke before activating the runtime.
- [x] 11.5 Switch runtime/launcher/plugin activation atomically enough that a failed
  upgrade leaves the previous valid runtime and plugin usable.
- [x] 11.6 Verify bundled server visibility and health after plugin activation; treat
  initialization/catalog failure as installation failure with explicit recovery.
- [x] 11.7 Preserve existing authoritative `main`, clean attached checkout,
  fast-forward-only, origin, ignored-collision, marketplace isolation, and plugin
  activation rules.
- [x] 11.8 Extend uninstallers to remove only marker-validated MCP runtime, launchers,
  and Dev Flow registration while preserving task data and unrelated MCP/plugin
  configuration.
- [x] 11.9 Add keep-source behavior and fail-closed source/runtime deletion when identity
  or cleanliness is uncertain.
- [x] 11.10 Add rollback tests proving the previous runtime remains available after a
  failed runtime build or plugin activation.

## 12. Remove legacy installed authority

- [x] 12.1 Remove `skills/follow-dev-flow`, `skills/analyze-change-impact`, and
  `skills/review-dev-flow-change` from the release package after MCP installed journeys
  pass.
- [x] 12.2 Remove `hooks/hooks.json`, Hook bootstrap, package Hook adapter, Hook-specific
  launcher paths, and Hook trust instructions from release assets.
- [x] 12.3 Remove or rewrite tests that assert Hook injection, Controller locator text,
  `/hooks` trust, command matching, or PreToolUse data-directory denial.
- [x] 12.4 Preserve relevant domain discovery and path-guard test coverage at the
  Controller/path layer even though Hook behavior is removed.
- [x] 12.5 Add package validation that fails if legacy Skills/Hooks or source-reading
  instructions reappear in current executable assets.
- [x] 12.6 Ensure retained archive OpenSpec files and historical documentation remain
  historical evidence and are not treated as current package authority.

## 13. Installed workflow journeys

Task 13.10 is a harness precondition and SHALL be enabled before executing 13.2–13.9;
the numbered list preserves historical references rather than execution order.

- [x] 13.1 Build an installed MCP journey harness that connects over the real launcher
  and never imports source test helpers into the server process.
- [x] 13.2 Run one-member and multi-repository `lite` journeys through discovery, start,
  next, apply, assurance, and Dossier.
- [x] 13.3 Run focused and closed-trigger installed journeys for all six official
  workflows, including both `lite` paths, preserving exact profile floors,
  allowances, ceilings, not-required decisions, and final Dossiers.
- [x] 13.4 Resume an active task from a non-first repository member after server restart.
- [x] 13.5 Resume a task created by a 0.4.x CLI/plugin installation with the new MCP
  server and finalize without state migration.
- [x] 13.6 Exercise OpenSpec available, stale, unavailable, source-producing, and
  governing-resource paths through action guidance.
- [x] 13.7 Exercise codebase-memory current/baseline separation and conservative degraded
  fallback.
- [x] 13.8 Exercise independent review approval, unavailable self-review, introduced/
  affected finding rework, unknown-causality triage, impact-gap re-planning, and
  authorized disposition.
- [x] 13.9 Exercise transport disconnect/uncertainty recovery without blind mutation
  replay.
- [x] 13.10 Instrument journeys to fail if the executor reads `skills/`, `hooks/`, MCP
  adapter source, CLI source, raw Store files, or the Controller data root.
- [x] 13.11 Exercise contract revision carry-forward with exact adopted-drift claims,
  corrupt-inventory admission failure, and concurrent admission from distinct linked
  worktrees without bypassing membership authority.

## 14. Package and boundary validation

- [x] 14.1 Update package validation to inspect candidate content rather than imported
  invoking-checkout modules for every MCP asset and identity.
- [x] 14.2 Validate exact stable tool names, input/output schemas, annotations,
  task-support setting, instructions, guidance digests, and context budgets.
- [x] 14.3 Validate all official workflows/actions against the MCP guidance coverage
  manifest.
- [x] 14.4 Validate current model schemas remain exactly `0.4.0` and reject any attempt
  to treat MCP interface versions as persisted model versions.
- [x] 14.5 Validate lock metadata equals package metadata and that the managed runtime
  receipt equals verified source/release/lock/Python identity.
- [x] 14.6 Validate no remote transport, generic command, raw state, branch/worktree,
  publication, CI/PR/release, or parallel-executor tool is exposed.
- [x] 14.7 Validate first-excess behavior for all new MCP metadata, result, inventory,
  and guidance bounds without truncation or partial mutation.
- [x] 14.8 Run the existing workflow, controller, store-integrity, adaptive-assurance,
  multi-repository, Web UI, release-bump, package, and platform suites to prove no
  core regression.

## 15. Documentation and architecture

- [x] 15.1 Rewrite README and README_CN around MCP discovery, start/resume, current
  action, apply, governance, and Dossier inspection.
- [x] 15.2 Rewrite INSTALL and INSTALL_CN with Python 3.10+, bundled/standalone mode,
  duplicate registration, MCP health verification, approvals, runtime ownership,
  uninstall, preserved data, and rollback.
- [x] 15.3 Update ARCHITECTURE and ARCHITECTURE_CN diagrams to show MCP/CLI/Web adapters
  over the Controller and remove current Skill/Hook authority.
- [x] 15.4 Update CONTRIBUTING documents with SDK isolation, protocol tests, stdout
  discipline, context budgets, schema compatibility, and tool-addition rules.
- [x] 15.5 Update promotion/release docs and roadmap to describe 0.5.0 as an interface
  migration with unchanged model 0.4.0.
- [x] 15.6 Document the explicit residual boundary from removing the fail-open Hook
  guard and avoid describing MCP annotations as enforcement.
- [x] 15.7 Document that other MCP hosts may connect at protocol level but are outside
  the first complete delivery support claim unless they provide the required local
  repository executor behavior.

## 16. Final release evidence

- [x] 16.1 Run strict OpenSpec validation and reconcile every changed current spec.
- [ ] 16.2 Run complete source tests on every supported Python version/host matrix and
  focused unsupported-version refusal tests.
- [x] 16.3 Run package validation against a copied candidate from outside the invoking
  checkout.
- [x] 16.4 Run fresh install, idempotent repair, fast-forward upgrade, failed runtime
  build, failed plugin activation, duplicate registration, rollback, and uninstall on
  macOS.
- [ ] 16.5 Run the corresponding focused native Windows x64 lifecycle matrix without
  POSIX compatibility tooling.
- [x] 16.6 Run the complete installed MCP workflow journey suite from the activated
  artifact.
- [x] 16.7 Capture `codex mcp list` or equivalent plugin-scoped health evidence showing
  one enabled Dev Flow server and the expected catalog.
- [x] 16.8 Confirm existing current task data and retained prior-version namespace bytes
  are unchanged by install, server startup, discovery, and uninstall.
- [x] 16.9 Confirm the release package contains no current Skills or Hooks and normal
  executor transcripts contain no package-source reads.
- [ ] 16.10 Publish the Delivery Dossier for this change only after all MCP, platform,
  package, compatibility, documentation, and rollback evidence is current.
- [x] 16.11 Regenerate the non-authoritative consolidated OpenSpec reading snapshot,
  readable traceability table, and `CHECKSUMS.sha256` after the final authoritative
  proposal, design, tasks, specs, baseline, and validation report are stable.
