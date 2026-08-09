## Why

On Phase 1 baseline `ae92935f0427c0e67dbebfbaab1c624630c358f1`, the
installer still verifies a mutable source checkout and later reads that checkout
again while building the runtime, writing marketplace state, activating the
plugin, running health checks, generating launchers, and reporting success. The
same lifecycle has no durable transaction commit point or immutable previous
release. Managed-runtime receipts do not attest installed package or dependency
content and are not consulted at startup. Install and repair also create ignored
bytecode in the authoritative checkout, while uninstall shallowly validates a
runtime and recursively deletes its entire root, including unknown content.

These are one lifecycle authority problem rather than five independent script
bugs. DFO-AUDIT-006 through DFO-AUDIT-010 require one release identity to bind
the verified Git tree, staged plugin artifact, wheel, runtime, launchers,
marketplace entry, Codex activation, health evidence, active installation record,
rollback,
and uninstall ownership.

Current-head reproduction is recorded in `REPRODUCTION.md`. DFO-AUDIT-006,
DFO-AUDIT-007, DFO-AUDIT-008, and DFO-AUDIT-010 are `REPRODUCED`.
DFO-AUDIT-009 is `PARTIALLY_CHANGED_BY_PHASE_0`: install and repair still
pollute source, but Phase 0 now preserves source on default uninstall instead of
letting that pollution drive destructive source handling.

## What Changes

- Derive a sealed candidate from the verified Git object tree, not from later
  reads of the mutable checkout. Preserve Git executable and symlink semantics,
  build the wheel and plugin release from that candidate, and bind every
  consumer to one content identity. Distinguish same-version activations with a
  sealed-source/activation-ID descriptor and prove host read-back first in a
  disposable isolated profile.
- Introduce a durable install/upgrade/repair transaction with a unique ID,
  explicit unresolved-to-sealed candidate binding, previous authority classified
  as `none`, `conforming`, or `legacy-observed`, explicit lifecycle states, a final
  active-record commit point, and compensating semantics for Codex operations that
  cannot participate in a filesystem transaction. Pre-commit health resolves the
  promoted candidate through a sealed journal-bound descriptor while ordinary
  startup continues to trust only the committed active record.
- Serialize install, upgrade, repair, and uninstall for one supported personal
  Codex profile with one stable profile lifecycle lock. Acquire it before previous
  classification or journal inspection and hold it through a durable terminal
  record, so resolved roots need no multi-lock protocol and one transaction never
  compensates another transaction's state.
- Restore a conforming previous release only from its sealed artifact. Declare
  rollback complete only after that release's activation and health are
  revalidated. A failed transition from `legacy-observed` authority remains
  truthful partial after any external effect; otherwise persist and return a
  truthful partial result with observed active identity and exact recovery
  guidance.
- Replace the current location-oriented runtime receipt with a versioned content
  attestation covering source tree, candidate artifact, wheel/distribution,
  installed files and metadata, exact dependencies, Python, launchers, active
  release, transaction, platform, and creation identity.
- Put a verifier outside the candidate runtime on the conforming launcher path.
  When that launcher invokes the verifier, missing, malformed, incompatible, or
  mismatched attestation fails closed before importing candidate code. Installer
  and repair validate launcher bytes independently; the startup claim treats an
  unmodified conforming launcher as its bootstrap precondition. Repair rebuilds
  into staging on every mismatch and reuses only a fully attested runtime.
- Run every unavoidable authoritative-source Python invocation with `-B` and a
  scoped `PYTHONDONTWRITEBYTECODE=1`; prefer executing build and health from the
  sealed staging artifact. Compare tracked, untracked, and ignored checkout
  state before and after every lifecycle outcome.
- Add an acyclic exact-ownership manifest/active-record envelope and containment
  removal protocol. Uninstall removes only matching record-set entries and empty
  owned directories; unknown, changed, concurrent, symlink, reparse, and special
  entries are preserved and reported. Whole runtime/release tree deletion is
  forbidden.
- Preserve legacy runtimes without an exact manifest. They may be replaced by a
  newly staged attested release during repair, but they are never silently
  adopted or recursively removed.

## Capabilities

### New Capabilities

- `immutable-install-candidate`: verified Git-tree derivation, candidate content
  identity, shared release binding, and authoritative-source immutability.
- `installer-runtime-transaction`: durable lifecycle state, commit point,
  conforming immutable-previous recovery, legacy-observed transition semantics,
  compensation, rollback verification, and truthful partial recovery.
- `runtime-startup-attestation`: versioned receipt content, startup verification,
  repair reuse/rebuild policy, and verifier trust boundary.
- `exact-runtime-ownership`: versioned per-entry ownership, contained removal,
  unknown-content preservation, and legacy-runtime handling.

### Modified Capabilities

- `authoritative-plugin-installation`: the personal marketplace keeps unrelated
  entries but points Dev Flow at the sealed candidate plugin artifact rather than
  the mutable authoritative checkout.
- `authoritative-plugin-installation`: Windows uninstall retains source under the
  full Phase 0 containment Requirement, eliminating the canonical default-deletion
  clause even when this change is composed directly against the current main spec.

## Scope and Compatibility

This change specifies DFO-AUDIT-006 through DFO-AUDIT-010 only. It does not
implement them in this phase. It does not change the public install commands,
plugin ID, personal-marketplace mode, bundled MCP mode, Controller task model,
or task-data namespace. The internal local marketplace target changes from the
authoritative checkout to a release-specific sealed plugin artifact.

DFO-AUDIT-002 remains `CONTAINED — destructive source removal disabled`.
Neither a new runtime ownership manifest nor a candidate manifest authorizes
source deletion. Default, keep-source, and any hypothetical explicit
source-removal path continue to retain source; re-enabling source removal needs a
separate specification and acceptance decision. This change includes the complete
modified Windows uninstall Requirement, so its target specification does not depend
on Phase 0 and Phase 1 archive order.

Out of scope are DFO-AUDIT-003 through DFO-AUDIT-005, DFO-AUDIT-011 through
DFO-AUDIT-024, Windows CLI/Web product expansion, standalone registration,
public-document semantic validation, and MCP schema, cancellation, or framing.
No existing runtime is migrated, deleted, or adopted merely because this
specification exists.

## Platform Evidence Boundary

POSIX implementation may later be exercised end to end in fully isolated
temporary fixtures. This host permits only parser, static, host-neutral receipt,
and non-native PowerShell simulations. Native Windows destructive lifecycle
evidence is `NOT RUN — native Windows host unavailable`; no later completion
claim may infer native Windows success from POSIX or static results.
