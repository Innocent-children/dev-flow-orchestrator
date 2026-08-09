## 1. Restore trustworthy test authority — DFO-AUDIT-017

- [x] 1.1 `[DFO-AUDIT-017 | test-environment-isolation / parent and combination
  scenarios | tests/test_cli.py]` Preserve the demonstrated hostile-parent
  regression and cover `DEV_FLOW_DATA_DIR`, `PLUGIN_DATA`, `CODEX_HOME`, all three
  pairs, and all three together. Evidence: old fixture sees external running state;
  repaired fixture reports only isolated state and all subtests pass.
- [x] 1.2 `[DFO-AUDIT-017 | external authority evidence remains untouched |
  tests/test_cli.py]` Put running Web state, sentinel, PID/status, and task bytes in
  external temporary roots; assert child root containment, absent child running
  state, no external disclosure, and byte-for-byte preservation. Evidence: focused
  authority-matrix command and before/after byte assertions.
- [x] 1.3 `[DFO-AUDIT-017 | subprocess tests own every mutable authority |
  tests/support.py, tests/test_cli.py, tests/test_install_script.py,
  tests/test_uninstall_script.py, tests/test_multi_repository_controller.py]` Apply
  the minimal-allowlist helper and explicit `relative_to(TemporaryDirectory)`
  assertions to CLI, multi-repository CLI, and POSIX lifecycle fixtures. Scrub
  `XDG_DATA_HOME`, `GIT_DIR`, `GIT_WORK_TREE`, and `GIT_INDEX_FILE`, then revalidate
  the final environment after all overrides. Evidence: complete CLI and POSIX
  lifecycle suites plus hostile redirect sentinels.
- [x] 1.4 `[DFO-AUDIT-017 | subprocess tests own every mutable authority |
  tests/test_managed_runtime.py, tests/test_installed_journeys.py,
  tests/test_web_server.py, tests/test_mcp_runtime.py]` Isolate managed-runtime,
  installed-journey, Web, and MCP subprocess fixtures without changing production
  precedence. Use child-side production data/runtime resolver probes and prove the
  returned roots are temporary. Evidence: focused fixture suites under hostile
  parent authorities.
- [x] 1.5 `[DFO-AUDIT-017 | Windows fixture prepared |
  tests/test_windows_lifecycle.py, tests/test_native_windows_runtime.py]` Isolate
  data, runtime, home/profile, source, marketplace, temp, fake Codex, and PATH roots;
  scrub Git redirects before fixture setup and validate final overrides; run
  host-neutral/static checks only on this host. Evidence: static suite plus
  `NOT RUN — native Windows host unavailable` for native dynamic behavior.
- [x] 1.6 `[DFO-AUDIT-017 | traceability | openspec/changes/
  audit-critical-safety-remediation/{TRACEABILITY.md,traceability.json}]` Restore the
  non-weakened OpenSpec traceability closure required by candidate validation and
  map every requirement/scenario to its test obligation. Evidence: installer target
  no longer fails for missing traceability and package validation reaches its real
  checks.
- [x] 1.7 `[DFO-AUDIT-017 | trustworthy baseline | tests/test_*.py]` Run the focused
  matrix, complete CLI, then full unittest discovery before safety implementation.
  Evidence: exact commands, return codes, counts, and durations recorded.

## 2. Contain capture-to-commit authority — DFO-AUDIT-001

- [x] 2.1 `[DFO-AUDIT-001 | containment protocol / S-to-S' mismatch |
  tests/test_capture_commit_authority.py]` Add deterministic faults after `S` and
  before `S'` for apply, revise, decision, disposition, cancel, finalize, one member,
  and a non-first multi-repository member. Evidence: no receipt, byte-stable state,
  unchanged revision/node/status, no new `DONE`, and safe continuation after reread.
- [x] 2.2 `[DFO-AUDIT-001 | residual pre-replace interval |
  tests/test_capture_commit_authority.py]` Inject after matching `S'` and before
  replace. Evidence: commit may exist but the response never derives currentness
  from `S`/`S'`, reports committed plus false/unknown, and forbids blind retry.
- [x] 2.3 `[DFO-AUDIT-001 | post-write freshness |
  tests/test_capture_commit_authority.py, tests/test_controller_contracts.py,
  tests/test_mcp_runtime.py, tests/test_cli.py]` Inject drift after replace/before
  observation and inject observation failure. Evidence: committed revision retained,
  freshness false or unknown, `dossier.current` not true, `blind_retry=false`, and
  read-after-write guidance across Controller/MCP/CLI contracts.
- [x] 2.4 `[DFO-AUDIT-001 | canonical lock order |
  tests/test_capture_commit_authority.py, tests/test_native_windows_runtime.py]`
  Test membership → canonical sorted repositories → task, canonical lock keys,
  opposite input order, two-process contention, revision CAS, reverse release, lock
  acquisition/capture/cancellation/write failures, and bounded no-deadlock joins.
  Evidence: host concurrency suite; native Windows cases remain a separate gate.
- [x] 2.5 `[DFO-AUDIT-001 | unified implementation |
  src/dev_flow_orchestrator/controller.py, src/dev_flow_orchestrator/store.py]`
  Implement `capture S → pure derive → revalidate S' → replace → observe live` and
  route apply, revise, decision, disposition, cancel, and finalize through it.
  Decision records participate in the same authority protocol while retaining their
  existing `snapshot: null` shape and replay identity. Evidence: all named mutation
  tests, unchanged decision persistence/replay, and unchanged revision-conflict
  behavior.
- [x] 2.6 `[DFO-AUDIT-001 | tri-state response and terminal freshness |
  src/dev_flow_orchestrator/model.py, engine.py, MCP/CLI contracts]` Add the
  versioned response-only freshness object, committed state, blind-retry prohibition,
  read-after-write recovery, live true/false/unknown projection, and stored-only
  null currentness without adding persisted snapshot or freshness fields. Evidence:
  schema/contract, decision-shape/replay, and post-terminal drift tests.
- [x] 2.7 `[DFO-AUDIT-001 | focused verification | Controller/Store/Delivery/
  concurrency suites]` Run all focused and directly affected tests and record the
  disposition only as `CONTAINED — pre-write revalidation plus post-write live
  freshness`.

## 3. Contain destructive source removal — DFO-AUDIT-002

- [x] 3.1 `[DFO-AUDIT-002 | safe uninstall containment / all source modes |
  tests/test_uninstall_script.py]` Add POSIX default, keep-source, and explicit
  remove-source tests that inject race, ignored, tracked, local-commit, and symlink
  work. Evidence: source/user work/task data preserved; unrelated marketplace bytes
  unchanged; no complete-removal claim.
- [x] 3.2 `[DFO-AUDIT-002 | observable partial outcome |
  tests/test_uninstall_script.py, tests/test_windows_lifecycle.py,
  tests/test_windows_product_support.py]` Assert exact retained path,
  exact-ownership-missing/destructive-disabled reason, partial outcome, per-component
  results, and inspection/backup/manual-ownership guidance on POSIX and host-neutral
  PowerShell. Evidence: text/structured output assertions and non-complete outcome.
- [x] 3.3 `[DFO-AUDIT-002 | destructive deletion disabled |
  scripts/uninstall.sh, scripts/uninstall.ps1]` Remove every reachable recursive
  source-root deletion path for default and explicit source removal while preserving
  separately reported plugin/launcher/runtime/marketplace steps. Do not describe
  runtime removal as exact-owned or independently safe; DFO-AUDIT-010 remains open.
  Evidence: dynamic POSIX race tests and host-neutral PowerShell control-flow/static
  assertions.
- [x] 3.4 `[DFO-AUDIT-002 | truthful public guidance | INSTALL.md, INSTALL_CN.md]`
  Update English source guidance first and fully synchronize Simplified Chinese.
  Evidence: retained-path, partial outcome, task-data, and manual inspection language
  agrees with both scripts.
- [x] 3.5 `[DFO-AUDIT-002 | focused verification | installer/uninstaller and
  host-neutral lifecycle suites]` Run all directly affected safety tests and record
  only `CONTAINED — destructive source removal disabled`.

## 4. Windows native verification gate

- [ ] 4.1 `[DFO-AUDIT-001 | native Windows locking |
  tests/test_native_windows_runtime.py]` On a supported native Windows host, verify
  lock order/no reverse acquisition, canonical multi-repository ordering, concurrent
  mutation no-deadlock, failure release, and freshness true/false/unknown.
  Current-host evidence: `NOT RUN — native Windows host unavailable`.
- [ ] 4.2 `[DFO-AUDIT-002/017 | native PowerShell lifecycle |
  tests/test_windows_lifecycle.py]` On a supported native Windows host, verify source
  retention, retained path, exact-ownership reason, partial outcome, manual recovery,
  temporary mutation targets, isolated `DEV_FLOW_RUNTIME_HOME`, `LOCALAPPDATA`,
  `USERPROFILE`, `CODEX_HOME`, and external sentinel stability. Current-host evidence:
  `NOT RUN — native Windows host unavailable`.

## 5. Adversarial and complete verification

- [x] 5.1 Re-run all three finding-specific groups with hostile parent authorities;
  do not clear the invoking shell to manufacture a pass.
- [x] 5.2 Run all related Controller, Store, Delivery, concurrency, installer, and
  uninstaller suites followed by complete unittest discovery.
- [x] 5.3 Run `uv run python -B -I -S scripts/validate_package.py`, treating its pass
  only as supplementary because DFO-AUDIT-018 remains open.
- [x] 5.4 Run strict OpenSpec validation, independent OpenSpec review, and
  `git diff --check`.
- [x] 5.5 Confirm no lifecycle residue, no real Codex profile/marketplace/task-data
  changes, and no remote write.

## 6. Deferred deletion enablement gate

- [ ] 6.1 In a later explicitly authorized DFO-AUDIT-006–010 phase, design and
  implement the versioned installation ownership manifest, same-filesystem
  quarantine, per-entry deletion, rollback, and native Windows reparse-point
  evidence before re-enabling source removal. This remains outside the current
  containment implementation and SHALL stay unchecked.
