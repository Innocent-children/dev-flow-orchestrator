# V4 delivery milestones

This plan splits the remaining V4 work into reviewable checkpoints without
turning a partial checkpoint into a release, weakening a safety assertion, or
claiming evidence that does not exist. OpenSpec live JSON remains authoritative
for task counts and status; milestone names are sequencing labels only.

## Rules shared by every milestone

- A milestone does not mark an OpenSpec task complete. A task is checked only
  after its implementation and required evidence are independently verified.
- The exact V3 reservation prefix, V3 bundles and handler implementations, and
  `workflows/release-provenance/first-introduction.json` remain immutable
  history.
- The incomplete V3 external steps in 12.6 through 12.12 remain factual
  non-completions. They are not recreated, inferred, or inherited by V4.
- `full@4` and `lite@4` production activation remains disabled until the exact
  profile-specific closure and separately authorized activation gate pass.
- Milestone completion alone never authorizes a canonical reseal, ledger
  append, installation, publication, handoff, CI run, or activation. M0, M1,
  and M2 prohibit all of those operations. V4-RC may perform only its exact
  ordered step and only after the step's separate OpenSpec and external
  authorization gates pass.
- Safety-critical failures in lock order, CAS, proof, nonce, journal or
  reconciliation state, quarantine, or zero-redispatch remain blockers. A
  milestone never relaxes those contracts to reduce schedule.
- On this macOS delivery, lack of trusted Codex-host abandonment evidence or a
  host-owned one-shot compensation approval is a supported fail-closed product
  boundary. The required closure is a bounded operator-intervention packet,
  scope-blocking `UNRESOLVED`, and a stop for user inspection or operation;
  trusted-host `ABANDONED` and `COMPENSATED` success are optional and are not
  claimed.
- Validation and release evidence for this change are macOS-only. Run only the
  smallest test selection directly covering changed behavior; discovery,
  full-suite, and broad unrelated aggregation are prohibited. No result from
  this change may be extrapolated to Windows or Linux.

## V4-M0: Safety Contract Preview

V4-M0 is the selected next milestone. It is an internal, reviewable contract
candidate and is not an installable or activatable release.

### Scope

V4-M0 implements only OpenSpec tasks 13.5 and 13.6:

- validate an immutable, exact V3 reservation-object prefix;
- validate monotonic introduction epochs and one contiguous append batch;
- sort only within an append batch and never globally reorder history;
- hash the canonical complete reservation objects, including graph, bundle,
  handler-contract, and handler-implementation identities;
- preserve the exact historical `first-introduction.json` bytes and fixed
  SHA-256;
- derive introduced workflow and handler keys from the complete provenance
  chain, never from the smaller ledger-handler union;
- validate exact package-recomputed ledger suffixes, predecessor and result
  ledger digests, cumulative identity-set digests, Git/base bindings, and epoch
  continuity;
- validate both `official-release` and the factual V3
  `reserved-unexposed` predecessor without fabricating a V3 review or handoff.

The implementation may change only the release provenance/ledger validator,
its direct CLI validation surface, and direct tests. Existing unverified draft
code is audited before it is extended; it is not treated as a completed
contract.

### Exit evidence

V4-M0 is complete only when all of the following hold. Functional test and
code-review evidence binds one unchanged implementation candidate; the later
task-status and resume edits are progress-only planning changes and receive
their own post-update validation:

1. Tasks 13.5 and 13.6 are implemented with positive and negative tests for
   historical-manifest tampering, exact-prefix mutation, empty/duplicate/
   unordered batches, one-shot iterable input, incomplete introduced-key
   deltas, package/suffix mismatch, epoch discontinuity, result-ledger and
   cumulative-set mismatch, and both predecessor kinds.
2. The targeted release-ledger/provenance suite passes.
3. On macOS, the smallest directly relevant syntax and test selections pass
   after the M0 code and tests are complete; no full suite is run.
4. An independent read-only code/specification review reports no unresolved
   actionable finding, and the primary agent independently verifies the result.
5. Only after that functional evidence passes, tasks 13.5 and 13.6 alone are
   marked complete and `RESUME.md` records the next exact stop.
6. Post-update strict OpenSpec validation and `git diff --check` pass, and a
   read-only diff review proves every post-evidence change is limited to the
   expected task-status and resume documentation. Any code, test, validator,
   package, or other implementation change restarts the affected M0 test and
   review evidence.

### Explicit stop boundary

After V4-M0 evidence is complete, stop. Do not begin recovery runtime, create
`full@4`/`lite@4` production bundles, append a real V4 epoch or ledger batch,
reseal a canonical candidate, or start any 14.x finalization step. If no other
task status changes, M0 moves the current live snapshot from 93/124 to 95/124;
future sessions must query live JSON rather than relying on that snapshot.

## V4-M1: Local Lite Preview

V4-M1 is a conditional developer preview considered only after V4-M0 review.
It is not automatically authorized by completing M0.

Its default scope is tasks 13.1 through 13.3:

- add package-owned `full@4` and `lite@4` candidate bundles while task schema
  remains v3 and all production profiles remain inactive;
- enumerate and identity-cover each V4 action's complete transitive execution
  and recovery closure, introducing new handler versions for every changed
  post-V3 semantic;
- implement the discovered-V3 fail-closed policy and expose bounded inspection
  without V4 substitution.

The preview may exercise catalog loading, validation, read-only inspection, and
action preview against isolated test data. It must not expose action apply,
dispatch, recovery, compensation, installation, or production task creation.
If a genuinely usable restricted `lite@4` profile is desired, a separate
OpenSpec scope decision must prove that its reachable graph is terminal-capable
and contains only fully closed operations. An action is not made unreachable
or reclassified merely to avoid its safety suite.

V4-M1 exits with focused bundle/catalog/V3 fail-closed tests, strict
validators, and independent review on macOS while activation remains off. It
then stops for an explicit decision to proceed or abandon the preview. A full
suite is neither required nor permitted.

## V4-M2: Inactive Runtime Closure

V4-M2 completes the remaining locally implementable runtime closure without
activating a production profile:

- tasks 13.1 through 13.3 when the optional M1 checkpoint was skipped or left
  any of them incomplete;
- tasks 5.13 and 5.15;
- tasks 7.12 and 8.8;
- tasks 13.4 and 13.7;

This milestone includes the complete effect/adapter matrix, the required
absence-of-host `UNRESOLVED` and operator-intervention behavior,
multi-repository activation-readiness validation, isolated CLI recovery, full
V4 safety coverage through the smallest directly relevant macOS selections,
and zero-redispatch proof. It MUST prove that the CLI asks the user to inspect
or operate and stops without automatic redispatch, compensation, replacement,
archive/unblock, or assertion-derived closure. Authenticated live `ABANDONED`
and dual-authority separately journaled `COMPENSATED` success MAY be exercised
only when a trusted host actually provides their authority; they are not M2
exit requirements or macOS release claims. Both V4 profiles remain inactive
throughout.
Completion of V4-M2 authorizes only a finalization review, not reseal, handoff,
installation, or activation.

## V4-RC: Frozen candidate and external evidence

V4-RC follows tasks 14.1 through 14.13 in order:

1. stabilize every identity-covered V4 input;
2. perform the one authorized successor-provenance freeze, cachebuster update,
   and exact append-batch reservation after the immutable V3 prefix;
3. freeze one canonical V4 candidate and its separate host-local snapshot;
4. run the smallest directly relevant macOS validation selections and
   independent pre-handoff review on that exact candidate;
5. create and independently verify the handoff;
6. obtain matching native macOS evidence;
7. make only progress/evidence-reference changes and prove the candidate
   unchanged;
8. run macOS-only CI selections, installation, and profile activation only
   under their separate explicit authorizations.

Any identity-covered change after the reservation restarts finalization with
new workflow and handler versions. V3 evidence never substitutes for V4
evidence.

### Independent cross-platform change

`complete-cross-platform-support` remains an independent change and is not a
release-order prerequisite for this macOS-only V4 candidate. Its existing task
state is neither modified nor inherited here. Completing this change makes no
Windows or Linux support, validation, handoff, installation, or activation
claim, and neither change copies, moves, auto-checks, or silently satisfies the
other's tasks.

## Decision points

- After M0: decide whether provenance/ledger stability is sufficient to fund
  the local preview.
- After M1: decide whether the developer-only preview provides enough value to
  fund the full recovery closure.
- After M2: decide whether to incur finalization and external-evidence cost.
- Before CI, installation, publication, handoff, or activation: obtain the
  exact external authorization required by OpenSpec; milestone completion is
  not that authorization.
