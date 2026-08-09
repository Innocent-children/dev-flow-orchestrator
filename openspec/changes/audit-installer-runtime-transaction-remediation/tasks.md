## 0. Current-head confirmation

- [x] 0.1 `[DFO-AUDIT-006 | REPRODUCTION.md]` On Phase 1 baseline, inject harmless
  source drift at runtime build, marketplace write, plugin add, health, launcher
  generation, and success receipt boundaries. Record 6/6 rc=0 stale-identity
  activations without changing repository files.
- [x] 0.2 `[DFO-AUDIT-007 | REPRODUCTION.md]` Exercise each current injectable A→B
  boundary: candidate staging, runtime build/promotion, launcher/marketplace writes,
  plugin remove/add, and health. Record active-receipt replace and final CLI smoke as
  `ABSENT-NOT-INJECTABLE` with their nearest current boundaries. Capture false
  restoration, unreported mixed state, uncertain external effects, and missing
  partial authority.
- [x] 0.3 `[DFO-AUDIT-008 | REPRODUCTION.md]` Build a real locked temporary runtime;
  verify missing/corrupt/schema receipt startup and package, RECORD, metadata,
  dependency, Python, launcher, and active-release repair behavior.
- [x] 0.4 `[DFO-AUDIT-009 | REPRODUCTION.md]` Inspect tracked, untracked, and ignored
  source state after fresh install and repair, count bytecode, and distinguish the
  Phase 0 source-retention behavior from the still-open pollution defect.
- [x] 0.5 `[DFO-AUDIT-010 | REPRODUCTION.md]` Put unknown file, directory, symlink,
  FIFO, socket, metadata, and late-created content at all safe POSIX runtime levels;
  confirm recursive loss while source/task/unrelated marketplace remain isolated.
- [x] 0.6 `[platform boundary | REPRODUCTION.md]` Run only host-neutral/static
  PowerShell evidence. Record `NOT RUN — native Windows host unavailable` for native
  destructive lifecycle.

## 1. Seal one immutable candidate — DFO-AUDIT-006

- [ ] 1.1 Implement verified commit/tree export into transaction staging. Validate
  canonical path/type/mode/blob/file/symlink inventory, traversal rejection, and
  stable candidate manifest digest.
- [ ] 1.2 Build the release-specific plugin tree and wheel only from the sealed
  export. Remove later activation reads from authoritative source.
- [ ] 1.3 Bind candidate/release IDs through runtime, marketplace member,
  candidate-specific Codex activation descriptor, launchers, health, ownership
  records, and active record. Treat fixed plugin ID/version/enabled fields as
  insufficient; feature-detect exact host read-back before external mutation and
  fail closed or truthful partial when exact identity cannot be observed.
- [ ] 1.4 Modify the personal marketplace transaction to point to the sealed plugin
  release while preserving unrelated members and public installation mode. Serialize
  lifecycle writers with a version/generation authority; publish using atomic
  exchange/replacement-with-backup or no-clobber creation; retain displaced,
  candidate, and current versions; and report uncoordinated races without claiming
  portable file CAS across non-participating writers.
- [ ] 1.5 Add deterministic source-drift tests at runtime build, marketplace write,
  plugin add, health, launcher generation, and final receipt boundaries. Assert the
  sealed candidate remains exact or the transaction fails closed with no stale
  success identity.
- [ ] 1.6 Cover executable files, symlinks, package metadata, traversal/duplicate
  rejection, and source changes before versus after sealing.
- [ ] 1.7 Probe source-path and MCP-environment read-back with the sealed candidate in
  a disposable isolated CODEX_HOME/marketplace/data/runtime authority before real
  profile mutation. Cover empty profile, missing fields, mismatch, duplicates, and
  cleanup containment.

## 2. Preserve authoritative source — DFO-AUDIT-009

- [ ] 2.1 Route all unavoidable source Python commands through `-B` plus scoped
  `PYTHONDONTWRITEBYTECODE=1`; execute build, validation, and health from sealed
  staging wherever possible.
- [ ] 2.2 Record operation-start and planned clone/fast-forward authority, then
  capture a post-selection source baseline. Compare final HEAD/tree/index plus
  NUL-delimited tracked, untracked, and ignored porcelain to that baseline after
  success, failure, and rollback. Preserve allowed pre-existing ignored content
  byte-for-byte; never clean it.
- [ ] 2.3 Add fresh-install, repair, failed-install, and failed-rollback assertions
  for empty new ignored state, no `__pycache__`, no `.pyc`, and no build/dist/egg-info
  residue.
- [ ] 2.4 Cover source, runtime, artifact, marketplace, and launcher authorities with
  spaces, Unicode, and apostrophes.
- [ ] 2.5 Keep default and keep-source uninstall source retention enabled. Do not add
  a source-removal interface or interpret runtime ownership as source ownership.
- [ ] 2.6 Apply the complete modified Windows uninstall Requirement carried by this
  change directly to the canonical main spec in validation. Assert the composed
  result contains source retention for default, keep-source, and unsupported
  explicit removal and contains no surviving default source-deletion SHALL,
  independent of active-change archive order.

## 3. Implement the durable lifecycle transaction — DFO-AUDIT-007

- [ ] 3.1 Implement one stable process-independent lifecycle lock per supported
  personal Codex profile. Acquire it before previous/journal observation, hold it
  through the terminal record and completion observation, and treat every resolved
  source/runtime/launcher/marketplace authority plus marketplace generation as
  subordinate to that lock. Do not add per-root locks. Contention waits by one
  bounded policy or returns pre-journal, pre-mutation busy.
- [ ] 3.2 Add a versioned transaction journal with unique ID, previous authority
  class, explicit unresolved prepared fields, component snapshots, state sequence,
  and atomic/fsynced transitions. Bind immutable selected-source/candidate/wheel/lock
  identities once at `staged`; use the committed active record as terminal authority
  for recovery from a matching stale pre-commit journal.
- [ ] 3.3 Detect unfinished transactions only after the profile lifecycle lock is
  held and before a new install/upgrade/repair/uninstall. Resume
  only proven idempotent work; otherwise observe and compensate or report partial.
- [ ] 3.4 Stage and promote candidate plugin/runtime assets before Codex mutation,
  retaining exact previous artifacts until commit and verified cleanup eligibility.
- [ ] 3.5 Implement exact launcher compare-and-replace and lifecycle-coordinated
  marketplace generation checks with platform-proven exchange/backup, previous/
  candidate/displaced digests, member-only compensation, and per-component recovery
  state. Add pre/post observations and truthful partial evidence for uncoordinated
  marketplace writers; do not claim an unavailable portable file CAS.
- [ ] 3.6 Before destructive Codex mutation, require host read-back channels for the
  candidate-specific sealed locator and bundled activation descriptor, proven by the
  isolated capability probe. After every remove/add return, query actual logical and
  candidate-specific plugin/MCP state; ambiguous identity remains unknown/partial
  and is never removed by assumption.
- [ ] 3.7 Run candidate identity, bundled registration, installed MCP health, and
  applicable CLI/MCP smoke before the final atomic active-record replace. Bind a
  sealed activation descriptor in the `activated` journal and make pre-commit health
  execute the exact promoted B runtime through that descriptor; assert a
  release-specific runtime marker for same-version A/B. Make active-record replace
  the only commit point and perform no mutation after it. Report any read-only
  post-commit launcher/marketplace/Codex drift as committed freshness
  `false`/`unknown` with blind retry forbidden.
- [ ] 3.8 For a conforming previous release, restore from its sealed plugin/runtime/
  launchers/marketplace/active record. Re-run previous identity, MCP registration,
  attestation, health, and applicable smoke before emitting `rolled-back` or
  “restored”. For `legacy-observed` previous authority, retain the legacy runtime and
  return truthful partial after any external-effect failure without an immutable
  restoration claim.
- [ ] 3.9 Persist truthful `partial` when compensation is incomplete or uncertain,
  including observed active release, per-component status, retained paths, exact
  sealed recovery actions, and blind-retry safety.
- [ ] 3.10 Add failure injection at candidate staging, runtime build, runtime promote,
  applicable launcher write, marketplace write, plugin remove, plugin add, health,
  active receipt replace, and final CLI/MCP smoke.
- [ ] 3.11 For every boundary, assert exact A is healthy or durable partial exists;
  B is never called restored A; mixed state is fully declared. Repeat with rollback
  failure and fresh-install previous=`none`, with source retained.
- [ ] 3.12 Add real multi-process install/install, repair/install,
  install/uninstall, and repair/uninstall contention tests for POSIX and the
  PowerShell contract adapter. Assert only one operation classifies previous state
  or creates a journal, the other waits or returns pre-mutation busy, canonical
  single-lock authority covers all resolved roots, crash recovery resolves the first
  journal, and no transaction compensates another transaction's entries.

## 4. Add runtime receipt and startup attestation — DFO-AUDIT-008

- [ ] 4.1 Define a closed canonical receipt schema binding transaction/release/
  candidate/activation, source commit/tree, candidate manifest, wheel, distribution
  metadata, installed RECORD inventory, exact dependencies/lock, Python, verifier,
  launchers, active identity, ownership manifest, platform, and creation Python.
  Record only expected descriptor/journal paths and schemas plus `activation_id`;
  prohibit descriptor or journal digests in the upstream receipt.
- [ ] 4.2 Install a bounded verifier outside candidate runtime and invoke it with
  isolated no-bytecode host Python before importing candidate code. Keep ordinary
  committed-active startup and lifecycle-lock/journal-bound `precommit-health` as
  closed, non-interchangeable authority modes.
- [ ] 4.3 When a conforming launcher invokes the verifier, make missing, malformed,
  incompatible, oversized, unknown-field, active release, presented launcher,
  verifier, Python, package, metadata, RECORD, dependency, and ownership mismatches
  fail startup closed with repair guidance.
- [ ] 4.4 Permit `reused=true` only after complete attestation. On any mismatch,
  stage a new release and activate through the transaction; never mutate or bless
  the suspect runtime in place.
- [ ] 4.5 Preserve legacy runtime paths during repair and record them separately;
  do not adopt their current inventory.
- [ ] 4.6 Add startup tests for missing/malformed/schema receipt, wrong active
  release, wrong Python, launcher tamper, package bytes, RECORD/metadata, dependency
  missing/extra/version drift, ordinary-startup rejection of transaction descriptors,
  and clean-runtime reuse.
- [ ] 4.7 Add repair tests proving every mismatch rebuilds and clean complete
  attestation alone reuses.
- [ ] 4.8 Document and test the trust boundary: the unmodified conforming launcher is
  the bootstrap precondition; installer/repair detect launcher replacement, while a
  replacement that bypasses the verifier is outside the startup guarantee.

## 5. Enforce exact runtime ownership — DFO-AUDIT-010

- [ ] 5.1 Define the versioned canonical ownership record set as the acyclic sequence
  candidate manifest → ownership body → runtime receipt → activation descriptor →
  terminal journal → committed active-record envelope. Exclude ownership-body self
  bytes and downstream digests; define active `self_digest` over canonical bytes
  with that field omitted.
- [ ] 5.2 Represent launchers/runtime/plugin/metadata/parents in the ownership body;
  represent the body file, receipt, activation descriptor, terminal journal, and
  active pointer in the downstream committed envelope; retain the bound journal
  unchanged until uninstall; represent marketplace as one logical member, never the
  shared file.
- [ ] 5.3 Replace runtime/release whole-tree recursion with no-follow per-entry
  revalidation, optional same-filesystem quarantine, individual unlink, and
  deepest-first empty owned-directory removal.
- [ ] 5.4 Preserve and report every unknown, changed, concurrent, symlink, reparse,
  FIFO, socket, special, or unverifiable entry. Preserve external symlink targets,
  task data, and unrelated marketplace bytes.
- [ ] 5.5 For legacy/missing/mismatched manifest or receipt, retain the runtime and
  report manual inspection. Do not silently adopt by enumerating current contents.
- [ ] 5.6 Add POSIX dynamic cases for extra file/dir/symlink at runtime root, active
  and inactive release, venv, site-packages, bin, and metadata; add safe special-file
  and concurrent-creation cases.
- [ ] 5.7 Assert known-owned entries follow manifest policy, runtime/release roots are
  never recursively deleted, retained paths and partial outcome are exact, and task
  data/unrelated marketplace remain byte-identical.

## 6. Platform parity and safety gates

- [ ] 6.1 Keep POSIX and PowerShell state, receipt, attestation, ownership, unknown
  preservation, legacy preservation, and source-retention semantics equivalent.
- [ ] 6.2 Run POSIX end-to-end transaction, rollback, startup, repair, ownership, and
  concurrent-removal matrices using hermetic subprocess authorities and external
  sentinels.
- [ ] 6.3 Add PowerShell parser/static, host-neutral receipt/manifest contract, and
  TemporaryDirectory non-native simulation checks without invoking native
  destructive lifecycle on a non-Windows host.
- [ ] 6.4 On a supported isolated Windows host, run native install/repair/rollback/
  startup/uninstall matrices and verify every mutation authority and external
  sentinel. Until then record `NOT RUN — native Windows host unavailable` and do not
  claim all-platform completion.

## 7. Verification and governance

- [ ] 7.1 Maintain Requirement → Scenario → Test → Evidence mapping in
  `TRACEABILITY.md` as tests are implemented; do not mark planned tests as run.
- [ ] 7.2 Run finding-focused tests, complete installer/uninstaller/managed-runtime
  suites, full unittest discovery, package validation as applicable, strict OpenSpec
  validation, and diff checks with exact commands/counts/return codes.
- [ ] 7.3 Run an independent implementation review against the frozen change,
  transaction artifacts, production diff, and actual verification evidence.
- [ ] 7.4 Report finding outcome separately for POSIX and Windows. Do not use
  “fully transactional”, “tamper-proof”, “globally atomic”, or “all platforms”
  without matching evidence.
