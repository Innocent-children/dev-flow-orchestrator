## 0. Current-head reproduction evidence

- [x] 0.1 `[DFO-AUDIT-006 | REPRODUCTION.md]` Inject source drift at runtime
  build, marketplace write, plugin add, health, launcher generation, and success
  receipt boundaries; record 6/6 stale-identity success results.
- [x] 0.2 `[DFO-AUDIT-007 | REPRODUCTION.md]` Exercise current injectable A→B
  boundaries and record false restoration, uncertain Codex effects, mixed state,
  and rollback failure without truthful partial evidence.
- [x] 0.3 `[DFO-AUDIT-008 | REPRODUCTION.md]` Exercise missing/corrupt/schema
  receipt startup and package, metadata, RECORD, dependency, Python, launcher, and
  release-path repair behavior.
- [x] 0.4 `[DFO-AUDIT-009 | REPRODUCTION.md]` Record fresh-install and repair
  ignored bytecode while preserving Phase 0 source-retention evidence.
- [x] 0.5 `[DFO-AUDIT-010 | REPRODUCTION.md]` Record recursive deletion of
  unknown active/inactive/root/venv/package/special/concurrent runtime content.
- [x] 0.6 `[platform | REPRODUCTION.md]` Record host-neutral PowerShell evidence
  and `NOT RUN — native Windows host unavailable` for native lifecycle execution.

## 1. Preserve authoritative source — DFO-AUDIT-009

- [x] 1.1 Apply `-B` and command-scoped `PYTHONDONTWRITEBYTECODE=1` to every
  source-side Python command in POSIX and PowerShell lifecycle scripts.
- [x] 1.2 Route package validation, runtime build, health, and launcher generation
  to sealed staging wherever possible; direct all build output outside source.
- [x] 1.3 Capture selected-baseline and final HEAD plus complete tracked,
  untracked, and ignored Git inventories after successful and failed install,
  repair, and upgrade. Do not clean or delete source content.
- [x] 1.4 Add permanent fresh, repair, and failure tests proving no new
  `__pycache__`, `.pyc`, build, dist, or egg-info content; cover spaces, Unicode,
  apostrophes, and a byte-identical pre-existing ignored sentinel.

## 2. Contain runtime removal and add exact ownership — DFO-AUDIT-010

- [x] 2.1 Remove every recursive deletion of a managed runtime root or release
  root from shell, PowerShell, and shared helpers before enabling new removal.
- [x] 2.2 Generate one versioned ownership manifest for each new release with
  `release_id`, declared root, relative path, entry type, regular-file digest,
  executable/mode, and symlink target as applicable.
- [x] 2.3 Implement no-follow per-entry `lstat`, optional same-filesystem
  quarantine, exact `unlink`, and deepest-first non-recursive `rmdir`.
- [x] 2.4 Retain and report unknown, changed, concurrently created, symlink,
  reparse, FIFO, socket, and special entries; preserve external link targets,
  source, task data, and unrelated marketplace members.
- [x] 2.5 Retain a legacy runtime with no conforming exact manifest, return partial,
  print its path and inspection guidance, and do not adopt current contents.
- [x] 2.6 Add permanent tests for extras at runtime root, active/inactive release,
  venv, site-packages, bin/scripts, and metadata; changed owned files; links;
  special entries; concurrent creation; legacy runtime; external sentinels; and
  absence of whole-tree recursive deletion.

## 3. Build one sealed release — DFO-AUDIT-006

- [x] 3.1 Export the verified Git commit/tree into installer-owned temporary
  staging and safely reject absolute, traversal, duplicate, inconsistent, and
  unsupported archive entries while preserving executable and symlink semantics.
- [x] 3.2 Run package validation and wheel/runtime/plugin release construction
  from staging. Promote a release-specific plugin path and bind plugin, runtime,
  launchers, health, ownership, and receipt to one `release_id`.
- [x] 3.3 Point the Dev Flow marketplace member and `codex plugin add` at the
  sealed plugin release rather than the authoritative checkout.
- [x] 3.4 Record verified commit/tree, release path, release-manifest digest, and
  wheel digest in receipt v2.
- [x] 3.5 Add source-drift injection before and after runtime build, marketplace
  write, plugin add, health, launcher generation, and success receipt publication;
  prove drift never enters the sealed release or produces stale attribution.

## 4. Verify receipt v2 at startup and repair — DFO-AUDIT-008

- [x] 4.1 Extend the existing receipt to v2 with release/source/wheel,
  Dev Flow installed files and metadata, exact dependencies and metadata/RECORD,
  Python executable, runtime path, launcher digest, and ownership-manifest digest.
- [x] 4.2 Implement one standard-library verifier shared by POSIX and PowerShell
  launchers and run it with bytecode disabled before importing Dev Flow.
- [x] 4.3 Fail startup with repair guidance for missing, malformed, incompatible,
  wrong-release, wrong-Python, package, METADATA/RECORD, dependency, launcher, or
  ownership mismatch. Keep startup read-only.
- [x] 4.4 Permit `reused=true` only after complete verification. Rebuild every
  mismatch from the sealed release into staging and never patch or adopt a suspect
  runtime in place.
- [x] 4.5 Add permanent startup and repair tests for every receipt/content mismatch,
  clean reuse, independent launcher-tamper detection, and a tampered runtime rebuilt
  with `reused=false` and no surviving marker.

## 5. Implement bounded rollback — DFO-AUDIT-007

- [x] 5.1 Add the bounded transaction record with optional `transaction_id`,
  operation, previous/candidate release, current step, actual plugin/marketplace/
  launcher/runtime state, and terminal committed/rolled_back/partial outcome.
- [x] 5.2 For a source-based previous install, export and verify a runnable sealed
  previous release before source fast-forward or external mutation; fail early when
  that release cannot be produced.
- [x] 5.3 Fully stage candidate and retain previous assets before changing runtime
  selection, marketplace, launchers, or Codex state. Preserve unrelated marketplace
  members and restore only the Dev Flow member when safe.
- [x] 5.4 Observe actual plugin and MCP state after every successful or failed Codex
  remove/add command instead of inferring side effects from its return code.
- [x] 5.5 On late failure, restore plugin, marketplace member, launchers, and runtime
  selection from the sealed previous release, then run previous MCP health and
  applicable CLI smoke before reporting `rolled_back`.
- [x] 5.6 Persist non-zero `partial` with current component states, retained paths,
  known release IDs, and `blind_retry_safe=false` whenever restoration is unsafe or
  unverified. Never call candidate B restored previous A.
- [x] 5.7 Publish the terminal committed transaction record as the final success
  mutation; perform only output and read-only checks afterward.
- [x] 5.8 Add deterministic failure injection for candidate staging, runtime build,
  runtime promotion, marketplace write, MCP launcher write, CLI launcher write,
  plugin remove, plugin add, health, final CLI/MCP smoke, and rollback failure.

## 6. Isolation and platform parity

- [x] 6.1 Place HOME, CODEX_HOME, data, runtime, LOCALAPPDATA, USERPROFILE, source,
  marketplace, PATH, fake Codex, and Git remote beneath a `TemporaryDirectory` in
  every lifecycle test and assert every mutation target is contained there.
- [x] 6.2 Keep POSIX and PowerShell source, release, receipt, rollback, ownership,
  legacy-retention, and source-retention semantics aligned.
- [x] 6.3 Run only parser, static, host-neutral, and safe PowerShell simulations on
  this host. Record native Windows as
  `NOT RUN — native Windows host unavailable`.

## 7. Verification and focused review

- [x] 7.1 Run the DFO-AUDIT-009 source-cleanliness focused tests.
- [x] 7.2 Run the DFO-AUDIT-010 ownership/uninstall focused tests.
- [x] 7.3 Run the DFO-AUDIT-006 sealed-release/source-drift focused tests.
- [x] 7.4 Run the DFO-AUDIT-008 receipt/startup/repair focused tests.
- [x] 7.5 Run the DFO-AUDIT-007 rollback/failure-injection focused tests.
- [x] 7.6 Run complete installer, uninstaller, managed-runtime, installed-journey,
  PowerShell host-neutral/static, and unittest discovery suites with exact commands,
  return codes, and counts.
- [x] 7.7 Run package validation, strict OpenSpec validation, and `git diff --check`.
- [x] 7.8 Perform one focused implementation review limited to DFO-AUDIT-006 through
  DFO-AUDIT-010, new deletion risk, source retention, rollback correctness, and test
  false positives. Record non-blocking enhancements for later without expanding this
  change.
