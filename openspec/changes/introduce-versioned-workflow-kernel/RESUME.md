# V4 source activation — all supported profiles enabled

Recorded on `2026-07-30`. Query live OpenSpec JSON for the current count.
The package source now enables all supported V4 creation profiles:

- `lite@4` + `single-repository`;
- `full@4` + `single-repository`;
- `full@4` + `multi-repository`.

The production `start` path was exercised for all three profiles and created
task-schema-v3 state pinned to the exact selected V4 bundle. Existing
schema-v1/schema-v2 tasks remain on their frozen legacy adapters and are not
migrated.

Activation required separating the immutable reserved-V3 predecessor evidence
from the live package activation manifest. The exact historical bytes now live
at `workflows/release-provenance/reserved-v3-activation.json` with unchanged
SHA-256
`ab7e025864038fdae1016117aa955dc01838b54c9e039b4de48e2fe6656eb710`.
The active live manifest is
`a5c19e78f7533a371ef0a71ad789c360710bf748f649232d4b32a913b0951a1a`.
The V3 prefix, V4 introduction epoch, bundle identities, handler identities,
and result ledger remain unchanged.

- Plugin version/cachebuster:
  `0.3.0+codex.20260729234414`.
- Active-source canonical candidate:
  `a545159ca8d4423ff078ac0d695dc8d3da51f92e8cfcb26e0d13e622bab90fc9`
  over 237 paths.
- Active-source host-local snapshot:
  `d04ace7b6649f4677df45dedf84cd77e2f44f3e32f75d0178559edcc5590f38f`
  over 368 paths.

Smallest directly relevant macOS validation passed:

- the live activation inventory, exact production `start` selection for all
  three profiles, activation closure, immutable V3 identities, and packaged
  successor provenance;
- the exact `full@4` two-repository happy path and bounded V4 `UNRESOLVED`
  operator-intervention path;
- package inventory, runtime dependency audit, syntax parsing of the seven
  directly touched Python files, all three bundled Skill validators, and the
  plugin manifest validator.

No discovery/full suite or broad unrelated aggregation ran. No Windows or
Linux validation ran or is claimed. The transient failures during validation
were a mistyped unittest class selector and the host Python's missing PyYAML;
the correct method passed, and the official validators passed using the
existing external validator environment without installing a dependency.
There is no remaining product or architecture failure.

The previously frozen 236-path handoff remains valid evidence for its exact
inactive candidate, but it does not have the same canonical digest as this
source-activation change. The main agent reviewed the exact 14-path delta
(13 modified, one added) against the extracted handoff candidate. No new
independent post-activation handoff review, publication CI, or host
installation was performed.

Live OpenSpec remains at 114/117. Tasks 14.11 through 14.13 stay open:
publication CI was not authorized or run, installation is explicitly left for
the user, and host pickup/pin eligibility cannot be recorded before that
manual installation. The source is ready for that manual step; after
installation, start a new task so the host loads the new cachebuster and
selects V4. Do not mark an existing legacy task as V4.

---

# V4-RC macOS finalization — 14.1 through 14.10 complete

Recorded on `2026-07-29`. Query live OpenSpec JSON for the current count.
Tasks 14.1 through 14.10 are complete. Tasks 14.11 through 14.13 remain
separately authorized publication, installation, and activation work; stop
here for the user's manual decision.

- Frozen canonical candidate:
  `07e27a834e6636e343a280f8561f74ad1801a0bdc530fe59701f620cd74d65ce`
  over 236 paths.
- Frozen host-local snapshot:
  `24f573d36bdde521c2ea659c30992d560f0ae104b8b9fc6a45633713c5375de6`
  over 367 paths.
- Successor epoch:
  `6d92f8453d1fc76bebcc832abe114ffa3cc75af7bf39cb776a4efa89ca9824ac`;
  immutable V3 prefix:
  `89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062`;
  V4 append batch:
  `95a81948c3940c283e7fab219badb23055741fd84002e969236ccd9f7a12153a`;
  result ledger:
  `f759e338e44df43ef34aa8b0735b21d44442c5102fb5685754cf546443fd6a02`.
- Independent candidate review and independent handoff/native-evidence review
  both returned `APPROVE` with no remaining findings. The initial review found
  one provenance-directory mismatch; the artifact moved to the normative
  `workflows/release-provenance/introduction-epochs/` location without
  changing epoch or ledger bytes, and the corrected candidate was re-frozen.
- Deterministic handoff archive:
  `a34790fe1e3ba7d60c4cf91f8225a675b4afb962e351a80ddcd081b4da0f24f5`;
  external archive manifest:
  `05da9efaf38f01d9a465e92950a16877d523a5add9297582c5ecfc7b73d70de0`;
  release handoff:
  `5ab117a7924d408729e880fd0dc1052345f6d8f8be67f0f8247d7e21a374dd0e`.
- Native macOS evidence:
  `802eed7b737260e789c905aeac470aace95914cda5ac60f493295a720f3d4d70`.
  From the exact handoff it selected the packaged POSIX MCP profile, completed
  initialize/tool-list with the exact six tools, and completed packaged
  `PreCompact`, silent `PostCompact`, and restoring
  `SessionStart(source=compact)`. The deterministic archive's 0600 launcher
  mode was restored to 0700 only in the extracted copy; all 236 candidate
  payloads and the canonical digest remained unchanged.
- On the exact corrected candidate, three high-value V4 test methods
  (full@4 two-repository flow, bounded UNRESOLVED response, handler closure)
  and two successor-path methods passed. Package/provenance validation,
  runtime-import audit, three official Skill validators, the official plugin
  validator, syntax parsing of the three path-correction Python files,
  strict OpenSpec, and `git diff --check` also passed.
- No discovery/full suite or broad unrelated aggregation ran. No Windows or
  Linux validation ran or is claimed. No plugin installation, publication,
  CI, V4 activation, or pin eligibility occurred. The native fixture started
  a schema-v2 fallback task, which does not activate V4.

External evidence is under `/private/tmp/dev-flow-v4-finalization/`, indexed
by `evidence-index.json`. Finalization through 14.10 is complete. Stop for the
user to decide the separately authorized manual installation and activation
steps.

---

# V4-RC macOS finalization — 14.1 complete

Recorded on `2026-07-29`. OpenSpec 14.1 is complete; query live OpenSpec JSON
for the current count rather than copying this checkpoint.

- V4 executor identities now bind their exact audited semantic dependency
  closure plus the structured executor manifest that declares the roots.
- Package validation follows catalog bundle files, runtime implementation
  sets, release ledger, and provenance paths into the canonical inventory.
- The macOS full@4 budget fixture records the 512-byte inline-summary and
  4,096-byte operator-intervention contracts.
- English/Chinese documentation states the macOS-only support boundary,
  inactive full@4/lite@4 creation behavior, 22-command surface, and manual V4
  recovery boundary.
- Exact handler, package, provenance, V4 identity, budget, runtime-import,
  strict OpenSpec, and diff checks passed. No discovery/full suite or
  Windows/Linux validation ran.

No cachebuster, real V4 successor epoch, ledger append, candidate freeze,
handoff, installation, publication, CI, or activation had occurred when this
checkpoint was written. Resume at 14.2 and stop after 14.10; installation and
activation belong to the user.

---

# V4-M2 macOS closure — manual intervention boundary complete

Recorded on `2026-07-29` after implementing and independently reviewing the
user-selected hostless recovery boundary. Live OpenSpec apply progress is now
`104/117`, with `13` finalization/external-evidence tasks open. Future sessions
MUST query live JSON rather than hard-code this snapshot.

Tasks 5.13, 5.15, 7.12, 8.8, 13.4, and 13.7 are complete for the current
macOS-only product scope. When the host cannot prove V4 `ABANDONED` or consume
the exact host-owned one-shot `COMPENSATED` authority, the CLI now:

- persists and idempotently replays only scope-blocking `UNRESOLVED`;
- returns the exact `dev-flow-v4-operator-intervention/v1` projection and the
  three permitted fresh-attempt conditions;
- caps the complete semantic-JSON packet at 4,096 bytes without truncation;
  exact-boundary output passes, while overflow or corrupt durable input keeps
  the same target/control/index/scopes blocked and returns the stable read-only
  inspect locator;
- performs zero redispatch, compensation, replacement, archive/unblock, or
  assertion-derived closure, and requires Codex to stop and ask the user to
  inspect or operate.

The same-attempt lost-response path initially exposed one implementation
defect: four focused full/lite `ABANDONED`/`COMPENSATED` methods completed the
first safe stop but replay returned
`WORKFLOW_ACTION_RECONCILIATION_COMMIT_UNVERIFIED`; the complete-receipt
`ACCEPTED` method passed. The corrected path first proves there is no
authoritative task event, then read-only verifies the exact active attempt,
target, task/workflow binding, and target/control index entries before
returning the same blocked result. Unrelated index revision growth is allowed
without permitting target/control drift. A legacy V3 reconciliation unit
method was also attempted but stopped in fixture setup because the current
reserved-unexposed V3 policy intentionally forbids ordinary V3 evaluation; it
did not exercise this implementation, and the temporary test edit was
reverted. These are resolved diagnostic facts, not green evidence.

The exact inactive pre-finalization canonical candidate used for the final
focused selection was:

- canonical candidate SHA-256:
  `284426763dd23ccaa22502c6730a6fbb073e8170239f6b631ee39f4dec5d4c7b`;
- canonical path count: `235`;
- scoped recovery implementation/Skill review digest:
  `a4338bffebb53ba61135aadbcdf1096ad6e7802d139afa7a9ae087cb2f195a75`;
- scoped OpenSpec planning review digest:
  `80f1cc6ace7c43dc185315c7112a6e0139fb0517a8cdcbd7f68aaef4a0a8c64f`;
- OpenSpec apply-guidance snapshot digest:
  `dc997e9e62621329ae565a14d3508f848922f3cfeab723ef784fd5c9080f0c6a`.

The following exact macOS selections passed on that implementation candidate.
Each command selected only the named methods; no class/module discovery or
full/broad suite was run:

```sh
python3 -m unittest tests.test_v4_reconciliation_authority.V4OperatorInterventionResponseTests
# 4/4 passed

python3 -m unittest tests.test_v4_preview_bundles.V4PreviewBundleTests.test_each_v4_action_has_the_exact_versioned_closure tests.test_v4_preview_bundles.V4PreviewBundleTests.test_v4_candidates_keep_task_schema_v3_and_all_profiles_inactive
# 2/2 passed

python3 -m unittest tests.test_v4_runtime_handlers.V4RuntimeHandlerTests.test_exact_full_v4_bundle_resolves_executable_role_closure tests.test_workflow_handler_audit.WorkflowHandlerAuditTests.test_package_inventory_matches_catalog_contract_ids
# 2/2 passed

python3 -m unittest tests.test_workflow_legacy_golden.WorkflowLegacyGoldenTests.test_real_legacy_transition_execution_matches_every_pure_edge tests.test_transition_shadow.TransitionShadowTests.test_shadow_match_runs_on_copies_and_preserves_all_inputs
# 2/2 passed

python3 -m unittest tests.test_external_tools.ExternalToolContractTests.test_catalog_role_and_execution_grant_bind_exact_content
# 1/1 passed

python3 -m unittest tests.test_action_execution_journal.SemanticJsonAndCryptoTests.test_tamper_wrong_secret_identity_copy_and_restart
# 1/1 passed

python3 -m unittest tests.test_v4_orchestration_runtime.V4OrchestrationRuntimeTests.test_exact_full_v4_two_repository_happy_path
# 1/1 passed

python3 -m unittest tests.test_workflow_action_transaction.WorkflowActionTransactionTests.test_finalization_failure_matrix_recovers_without_dispatch tests.test_v4_runtime_evidence.V4RuntimeReservationEvidenceTests.test_release_requires_fresh_controller_evidence_and_exact_outbox
# 2/2 passed

python3 -m unittest tests.test_release_ledger.IntroductionEpochTests.test_reserved_unexposed_epoch_binds_complete_successor tests.test_release_ledger.IntroductionEpochTests.test_epoch_binding_tamper_matrix_is_rejected
# 2/2 passed using a synthetic @4 successor; no real V4 epoch/append was created

python3 -m unittest tests.test_v3_reserved_unexposed.ReservedUnexposedV3Tests.test_exact_reserved_identities_remain_inspectable_but_not_mutable tests.test_v3_reserved_unexposed.ReservedUnexposedV3Tests.test_recovery_resolution_allows_exact_idempotent_outbox_completion
# 2/2 passed

python3 -m unittest tests.test_v3_cli_action_recovery.V3CliActionRecoveryTests.test_full_abandonment_requires_operator_intervention
# 1/1 passed against isolated full@4

python3 -m unittest tests.test_v3_cli_action_recovery.V3CliActionRecoveryTests.test_lite_compensation_requires_operator_intervention
# 1/1 passed against isolated lite@4

python3 -m unittest tests.test_v3_cli_action_recovery.V3CliActionRecoveryTests.test_receipt_verified_restart_accepts_once_and_never_redispatches
# 1/1 passed against isolated full@4
```

AST parsing for the four directly changed Python/test files, the bundled
`follow-dev-flow` Skill validator, strict OpenSpec validation, fixed historical
anchors, and `git diff --check` passed. Independent stable-digest code and
planning re-reviews both returned `APPROVE` with no findings.

Trusted-host `ABANDONED`/`COMPENSATED` success remains optional and unclaimed.
No full test suite or native Windows/Linux validation ran, and no macOS result
is extrapolated to those platforms. V4 profiles remain inactive. No real V4
epoch, ledger append, cachebuster update, canonical freeze, handoff,
publication, installation, CI, or activation occurred in M2.

---

# Current macOS V4 product boundary — manual intervention is the required hostless closure

Recorded on `2026-07-29` after the user selected the safe product boundary for
a Codex host that cannot itself prove V4 `ABANDONED` or provide the opaque
one-shot authority required by `COMPENSATED`. This section supersedes the
future-looking statement below that such host absence is an architecture
blocker. It does not rewrite any V3 historical fact or authorize release work.

For tasks 5.13, 5.15, 7.12, 8.8, and 13.4, the required macOS
absence-of-host behavior is now:

- finish only the current reconciliation attempt as `UNRESOLVED`; keep the
  original execution, receipt, containment, index, affected scopes,
  dependencies, barriers, and finalization blocked;
- return a bounded packet with
  `schema: "dev-flow-v4-operator-intervention/v1"` inside the V4 CLI outer
  `schema: "dev-flow-v4-action-reconciliation-cli-result/v1"`. The packet carries
  `required: true`, `reason: "TRUSTED_HOST_AUTHORITY_UNAVAILABLE"`,
  `target_execution_id`, sorted unique `effect_ids`, normalized
  `affected_scopes`, the three stable `allowed_resume_conditions`
  `authenticated_original_runtime`, `verifiable_stored_receipt`, and
  `trusted_host_recovery_authority`, plus `automatic_redispatch: false`,
  `automatic_compensation: false`, `automatic_unblock: false`, and
  `caller_assertion_can_unblock: false`;
- measure the complete intervention semantic JSON against an exact 4,096-byte
  limit without truncation. Exact-boundary output passes; one-byte overflow
  returns `ACTION_RECOVERY_OPERATOR_INTERVENTION_TOO_LARGE` with the target,
  actual/limit counts, and `action-recovery-inspect` locator. A corrupt effect
  graph or scope returns `ACTION_RECOVERY_RESULT_INVALID`; both paths preserve
  the same `UNRESOLVED` records, blocked scopes, and zero invocations;
- stop and ask the user to inspect or operate. Do not automatically poll into
  a new attempt, redispatch, compensate, archive/unblock, create a replacement
  lease, or accept a user, model, worker, manager, or caller assertion alone as
  proof;
- permit only a fresh, separately authorized attempt if a later authenticated
  original runtime, verifiable stored receipt, or future trusted host recovery
  authority becomes available. The intervention packet is not itself evidence
  and cannot be replayed as authority.

This safe manual-intervention path is the required task closure for the current
macOS product. Authenticated live `ABANDONED` and host-one-shot-approved
`COMPENSATED` success remain optional future trusted-host capabilities and
MUST NOT be claimed as macOS release evidence. The five task checkboxes remain
open until this revised contract is implemented and its smallest directly
relevant evidence is reviewed; they no longer wait for the repository to
fabricate host authority it does not possess.

No V4 introduction epoch, ledger append, cachebuster update, canonical reseal,
handoff, installation, publication, CI run, or activation is authorized or
claimed by this product-boundary decision.

---

# macOS-only V4 scope decision — trusted-host recovery boundary still open

Recorded on `2026-07-29` after the user explicitly removed Windows and Linux
validation from this V4 delivery and reaffirmed that no full test suite may be
run. This section supersedes older future-looking cross-platform and full-suite
instructions below; historical statements about checks that actually occurred
remain factual and unchanged.

Live OpenSpec apply status after retiring the seven unperformed V3 external
steps as non-actionable historical facts is `98/117` with `19` actionable
tasks open. Future sessions MUST query live JSON rather than hard-code this
snapshot.

The future V4 contract is now:

- native validation, focused CI, installation, and host pickup are macOS-only
  through the packaged POSIX MCP profile;
- every test run is the smallest selection directly covering changed behavior;
  discovery, a full suite, and broad unrelated aggregation are prohibited;
- no macOS result may be extrapolated to Windows or Linux;
- `complete-cross-platform-support` remains an independent unchanged OpenSpec
  change and is no longer a release-order prerequisite for this V4 delivery;
- V3 tasks 12.1 through 12.5 remain immutable historical facts, while the
  unperformed former 12.6 through 12.12 steps remain explicitly recorded as
  retired non-completions rather than fabricated success.

One architecture blocker remains. The public isolated CLI has no trustworthy
Codex-host runtime observer or host-only one-shot approval source distinct from
the manager caller. The repository can expose an in-process composition
boundary, but it cannot derive genuine host facts from caller JSON, an
environment variable, an inherited file descriptor, `active=false`, or an
empty data-root. Until a host supplies that authority, V4 `ABANDONED` and
`COMPENSATED` stay fail-closed as `UNRESOLVED`; claimed effects are not
redispatched and quarantined scopes remain blocked. This is a product-scope
decision, not implementation work the user must personally write.

No V4 introduction epoch, ledger append, cachebuster update, canonical reseal,
handoff, installation, publication, CI run, or activation is authorized or
claimed by this scope update.

---

# V4-M2 runtime-closure checkpoint — functional paths green, release gates open

Recorded on `2026-07-29` after the user authorized V4 implementation while
retaining the project rules that prohibit full-suite runs and skip native
Windows/Linux validation.

OpenSpec remains `98/124` (`26` open). No V4-M2 task has been marked complete
at this checkpoint because the required broad failure matrices were not run.

Implemented local runtime behavior now includes:

- exact `full@4` and `lite@4` manager registry routing while repository
  orchestration remains restricted to `full@4`;
- executable twelve-role V4 handler closure on transaction, recovery, and
  reconciliation paths;
- zero-redispatch quarantine recovery with opaque `ACCEPTED`, blocking
  `UNRESOLVED`, and separately journaled compensation machinery;
- an experimental inherited stream-socket challenge adapter with a fresh random
  nonce, 30-second lifetime, exact task/revision/attempt/effect/index/journal/
  containment/scope or compensation request/target binding, and rejection of
  serialized pipe frames; this adapter is not connected to the public isolated
  CLI because a caller-controlled socket peer cannot prove independent
  host/controller provenance;
- a workflow-gated external-write bridge that consumes an opaque host grant
  immediately before the exact compensation provider invocation;
- exact V4 runtime settlement/replacement evidence and full-v4 two-repository
  orchestration through finalization readiness.

Main-agent focused results on the current implementation include:

- V4 reconciliation authority `16/16`;
- isolated full-v4 `ABANDONED`, full-v4 `COMPENSATED`, and lite-v4
  `ABANDONED` each passed on the reviewed challenge/response candidate, but
  those successes are not current release evidence because independent review
  rejected the caller-controlled peer provenance and the production fallback
  was disabled;
- V4 handler/runtime evidence `5/5`;
- exact full-v4 two-repository orchestration `1/1`;
- directly affected orchestration-adapter regression `2/2`;
- Python syntax, package validation on Darwin/Python 3.9.6, the immutable
  four-reservation ledger, strict OpenSpec validation, and
  `git diff --check`: passed.

The immutable history remains byte-for-byte anchored:

- first introduction:
  `72e301d16546001abb397e37600cf3a141ca2955e7052f5d7dabdbb96f02016a`;
- four-reservation ledger:
  `89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062`;
- activation:
  `ab7e025864038fdae1016117aa955dc01838b54c9e039b4de48e2fe6656eb710`.

Still unverified by explicit project policy:

- the complete Codex thread / Agents session / `codex exec` failure matrix;
- every recovery crash boundary in one broad run;
- OpenSpec 13.7 and 14.4 full-suite gates;
- OpenSpec 14.8 and 14.11 Windows/Linux or cross-platform evidence.

Independent review also found one architecture blocker: the public isolated
CLI has no trusted host launcher or host-only trust anchor distinct from the
manager caller. Until such a boundary exists, V4 `ABANDONED` and
`COMPENSATED` through that surface fail closed as `UNRESOLVED`; OpenSpec 5.13,
5.15, 7.12, 8.8, and 13.4 remain open.

Production V4 activation remains off. No V4 introduction epoch, ledger append,
cachebuster update, canonical reseal, handoff, installation, publication, CI,
or activation has occurred. Functional local evidence must not be presented as
a completed V4 release while those gates remain prohibited or unverified.

---

# V4-M1 implementation checkpoint — full-suite gate unverified

Recorded on `2026-07-29` after the user explicitly authorized the conditional
V4-M1 local preview and limited validation to macOS, smallest-scope tests only.

## Completed implementation tasks

- OpenSpec 13.1 through 13.3 are implemented and marked complete. Live apply
  progress after marking is `98/124`, with `26` tasks remaining.
- Package-owned `full@4` and `lite@4` preview bundles retain task schema v3.
  Production activation remains off; the unchanged historical activation file
  may omit these unreserved preview profiles, and runtime treats the omitted
  profiles as implicitly inactive.
- Every V4 action declares the canonical twelve-role transitive handler
  closure. Catalog validation, compiled action semantics, graph/bundle
  identity, and the pinned call-target resolver cover those declarations.
- Exact reserved-unexposed `full@3` and `lite@3` tasks allow bounded inspection
  and exact already-committed outbox completion only. Ordinary mutation is
  denied, V4 substitution is absent, and a claimed fixed V3 family with any
  schema, graph, or bundle identity mismatch fails before outbox delivery with
  `WORKFLOW_RESERVED_UNEXPOSED_IDENTITY_MISMATCH`.

## Frozen implementation evidence

- `scripts/dev_flow_parts/core.py`:
  `d0ad31d42f38837c7896fa4250e70441b931c9fde283c5e65d9bcd502e747171`;
- `scripts/dev_flow_parts/workflow_runtime.py`:
  `cdc52953b04951ee292f586448a8c6d443baaed42d14ad268f1f9be2446e0d1a`;
- `scripts/dev_flow_parts/workflow_catalog.py`:
  `4d5cab95b27a34385f2ccda4e8fb0bb736fb0db086d5bc38c146f3fe769820a1`;
- `scripts/dev_flow_parts/workflow_projection.py`:
  `81fd82360158b1ef9a56b7c0913418812787f591f8dec454ec14da06adab3d2b`;
- `scripts/dev_flow.py`:
  `89f3a46a06fe5da0f9ea8abf92a1f59db26eabf189ec887f6c3c8099bc91547e`;
- `tests/test_v3_reserved_unexposed.py`:
  `0254d7e50eff41416fc0f46ee84b0e58a184ea15f7135a33d6df4207639e804d`.

The final focused V4 bundle/closure/V3 fail-closed selection passed `21/21`.
Syntax checks, the four-reservation ledger validator, fixed
first-introduction validator, package validation on Darwin/Python 3.9.6,
strict OpenSpec validation, and `git diff --check` passed. The final
independent read-only review approved the hash-bound 13.1 through 13.3
candidate with no findings after independently reproducing the public-loader
schema/graph/bundle mismatch matrix.

The immutable historical anchors remain:

- first introduction:
  `72e301d16546001abb397e37600cf3a141ca2955e7052f5d7dabdbb96f02016a`;
- four-reservation ledger:
  `89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062`;
- activation:
  `ab7e025864038fdae1016117aa955dc01838b54c9e039b4de48e2fe6656eb710`.

Release provenance still contains only `first-introduction.json`; the ledger
still contains four V3/legacy reservations; activation still contains only
inactive V3 profiles. No real V4 epoch, ledger append, cachebuster update,
recovery runtime, apply, dispatch, compensation, handoff, installation,
publication, CI, or production activation was created or performed.

## Validation limitation and exact stop point

A full-suite run was started before the user's final prohibition and was
immediately interrupted when that instruction arrived. It produced no final
summary and is not evidence. `AGENTS.md` now prohibits every full test suite,
including when a milestone requests one, and requires that such a gate be
reported as unverified. Native Windows and Linux validation is also skipped;
macOS evidence must not be extrapolated to those platforms.

Therefore the 13.1 through 13.3 implementation tasks are complete, but the
`MILESTONES.md` V4-M1 full-suite exit gate remains explicitly unverified.
Stop here. Do not enter V4-M2, implement recovery runtime, or begin 13.4,
13.7, or any 14.x task without a new explicit user decision.

---

# V4-M0 completion checkpoint

Recorded on `2026-07-29` after completing the bounded Safety Contract Preview
for OpenSpec tasks 13.5 and 13.6.

## Completed scope

- `scripts/release_ledger.py` now validates the immutable exact V3 prefix,
  append-history epochs, batch-only UTF-8/numeric ordering, complete
  reservation-object digests, immutable first-introduction history, exact
  package/provenance identity deltas, package-recomputed suffixes, cumulative
  identity and result-ledger digests, and both predecessor kinds.
- The public validator and direct CLI/export surface reject discontinuous or
  forged successor evidence without authorizing exposure.
- `tests/test_release_ledger.py` covers the required positive/negative matrix,
  including the reviewed cross-epoch handler late-declaration attack.
- Only 13.5 and 13.6 were marked complete. No recovery runtime, V4 bundle,
  production profile, real epoch artifact, real ledger append, cachebuster,
  canonical reseal, handoff, installation, publication, CI, or activation was
  created or performed.

## Fixed candidate and evidence

- implementation SHA-256:
  `69894a67ba16b3d8de08a03d41fa10d7933fdf279c3ebd1ca19bbb763db8e224`;
- direct-test SHA-256:
  `f9f676b674950a54835c942d75114983acd470973588847929783fff60eef00b`;
- immutable anchors remained:
  `72e301d16546001abb397e37600cf3a141ca2955e7052f5d7dabdbb96f02016a`,
  `89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062`,
  and
  `ab7e025864038fdae1016117aa955dc01838b54c9e039b4de48e2fe6656eb710`;
- syntax validation passed;
- the release-ledger/provenance suite passed `31/31`;
- after the final structured-error serialization correction, the two directly
  affected tests passed `2/2`;
- independent read-only code/spec review approved the exact fixed candidate
  with no unresolved finding;
- post-progress strict OpenSpec validation and `git diff --check` passed, and
  live apply status was `95/124` with `29` tasks remaining.

The earlier full suite passed `873` tests with `6` conditional skips before the
review finding was corrected. A second full-suite run on the corrected
candidate was stopped when the user explicitly requested the smallest
practical test scope. It is not evidence for the corrected candidate and is
not represented as such.

## Exact stop and resume point

The post-progress strict OpenSpec and diff/hash checks passed. Stop here. Do
not enter V4-M1 automatically. The next action requires the user's separate
decision whether to begin the conditional V4-M1 local preview; until then,
13.1 through 13.4, 13.7, every 14.x task, and recovery runtime remain out of
scope.

---

# Superseded V4 milestone planning checkpoint

Recorded on `2026-07-29` after the user selected V4-M0 as the next bounded
milestone and requested that the future plan be written into OpenSpec before
any further implementation.

## Current authority

- The authoritative milestone plan is `MILESTONES.md`.
- OpenSpec proposal, design, and tasks now reference that plan.
- This planning session changes documentation only. It does not modify runtime
  code, tests, workflow bundles, activation, release artifacts, Git state, or
  controller data.
- No canonical reseal, V4 introduction epoch, ledger append, installation,
  publication, handoff, CI run, activation, staging, commit, or push is
  authorized or performed.
- The worktree remains intentionally dirty. Preserve every tracked and
  untracked change and the ignored root `pyproject.toml` and `uv.lock`.

## Live OpenSpec snapshot

Always query live JSON before work:

```sh
openspec status --change introduce-versioned-workflow-kernel --json
openspec instructions apply --change introduce-versioned-workflow-kernel --json
git status --short
```

At this documentation checkpoint the live apply snapshot is `93/124`, with 31
tasks remaining. That number is informational only. Planning artifacts are
complete, and strict validation passed before this checkpoint was written.

The remaining task groups are:

- local V4 closure still open: 5.13, 5.15, 7.12, and 8.8;
- factual unfinished V3 external history: 12.6 through 12.12;
- V4 safety-successor restart: 13.1 through 13.7;
- V4 finalization and external evidence: 14.1 through 14.13.

## Selected next milestone: V4-M0

V4-M0 is an internal Safety Contract Preview. It implements only:

- 13.5, the immutable-prefix, monotonic-epoch, per-batch-order, complete
  reservation-object digest contract;
- 13.6, the immutable first-introduction and strict successor provenance
  contract for both `official-release` and the factual
  `reserved-unexposed` V3 predecessor.

If no other task status changes, successful independent verification of those
two tasks changes the snapshot to 95/124. Live JSON remains authoritative.

V4-M0 explicitly excludes:

- recovery, reconciliation, compensation, transaction-lock, orchestration, or
  activation runtime changes;
- tasks 13.1 through 13.4, 13.7, and every 14.x task;
- creation of real `full@4`/`lite@4` reservation objects or epoch manifests;
- canonical reseal, cachebuster update, real ledger append, installation,
  publication, handoff, CI, or activation.

## Exact implementation resume point

An unverified, incomplete successor-provenance draft already exists in
`scripts/release_ledger.py`. It was started before the user narrowed the prior
session to documentation. Preserve it, but do not trust or overwrite it.

Before editing, audit the draft against current OpenSpec and direct callers.
The last known issues, which must be confirmed in source, are:

- `_introduction_epoch_material` may use the `(bytes, int)` result of
  `_workflow_sort_key` to index a mapping keyed by `(str, int)`;
- the introduction-epoch CLI validator and public exports may be incomplete;
- `tests/test_release_ledger.py` lacks the complete successor positive and
  negative matrix;
- the draft may cover only the first `reserved-unexposed` epoch rather than
  general monotonic epochs and the `official-release` chain;
- result-ledger and cumulative identity-set digest validation may be absent or
  incomplete;
- false exposure fields in an epoch record are declarations, not sufficient
  authority for supersession, release, or activation.

The primary agent must independently inspect the source and tests. Subagent
self-report is not completion evidence.

## Historical anchors to reverify

The last recorded immutable hashes are:

- `workflows/release-provenance/first-introduction.json`:
  `72e301d16546001abb397e37600cf3a141ca2955e7052f5d7dabdbb96f02016a`;
- the four-reservation `workflows/release-ledger.json`:
  `89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062`;
- `workflows/activation.json`:
  `ab7e025864038fdae1016117aa955dc01838b54c9e039b4de48e2fe6656eb710`.

Recompute them read-only at M0 start. Any mismatch is a blocker; do not
normalize, regenerate, or reseal around it.

The fixed first-introduction history contains more handler identity keys than
the union referenced by current ledger reservations. Cumulative historical
handler identity must therefore come from the complete provenance chain, never
from the ledger handler union.

## V4-M0 work order

1. Fully read `AGENTS.md`, this checkpoint, `MILESTONES.md`, and every artifact
   returned by live OpenSpec instructions.
2. Recompute the historical anchors and preserve the dirty worktree.
3. Perform a read-only contract/caller/test audit of the existing release
   ledger draft and report the exact gaps before editing.
4. Implement 13.5 and its direct negative matrix.
5. Implement 13.6 and its direct negative matrix, including both predecessor
   kinds and continuous epochs.
6. Run targeted syntax and release-ledger/provenance tests while collecting an
   explicit failure list.
7. After the M0 implementation is complete, run
   `python3 -m unittest discover -s tests -v` once on the unchanged M0
   implementation candidate.
8. Perform an independent read-only code/specification review and have the
   primary agent independently verify every finding and resolution.
9. Only after that evidence passes, mark 13.5 and 13.6 complete and update this
   checkpoint as progress-only planning changes.
10. Run post-update strict OpenSpec validation and `git diff --check`, then
    perform a read-only diff review proving every post-evidence change is
    limited to the expected task-status and resume documentation. Any
    implementation, test, validator, or package change restarts its affected
    evidence.
11. Stop.

Do not begin V4-M1 automatically. It requires a separate user decision after
the M0 report.

## V4-M0 minimum negative matrix

- historical first-introduction key deletion, addition, duplicate, reorder, or
  replacement remains rejected even if a caller recomputes its SHA;
- the original first-introduction bytes remain valid when the current package
  is a strict V4 identity superset;
- a current package missing any historical workflow or handler identity is
  rejected;
- predecessor reservation deletion, mutation, replacement, or reorder is
  rejected by exact canonical prefix reconstruction;
- empty, duplicate, historical-overlap, or batch-internally unordered append
  input is rejected, while separately ordered append batches are not globally
  reordered;
- a one-shot iterable is materialized exactly once;
- introduced workflow/handler sets must equal the exact package-minus-history
  difference and must equal the suffix workflow keys;
- every complete suffix reservation must equal the package-recomputed object;
- schema, change, Git/base, epoch sequence/ID, predecessor SHA/count, append
  digest, result-ledger digest, and cumulative-set digest tampering is rejected;
- `official-release` requires exact continuous review and handoff bindings;
- `reserved-unexposed` preserves the V3 prefix and cannot fabricate review,
  handoff, installation, publication, activation, or pin eligibility from
  `active=false` or an empty data-root scan.

## Later milestones

- V4-M1 is a conditional inactive local preview covering 13.1 through 13.3.
- V4-M2 first absorbs any 13.1 through 13.3 task left open when M1 is skipped
  or incomplete, then completes 5.13, 5.15, 7.12, 8.8, 13.4, and 13.7 while
  activation stays off.
- V4-RC follows 14.1 through 14.13 on one frozen candidate and under the
  declared external authorizations. It remains blocked by the live
  `complete-cross-platform-support` release-order prerequisite; shared
  handoff, native, post-report, CI, and installation evidence must be
  independently validated and referenced by exact identity in both changes.

None of these labels changes the immutable V3 facts or permits skipping a
task's evidence.

---

# Archived V3 refactor pause and resume checkpoint

The material below is retained as historical context only. Its old task counts,
immediate blocker, and safe-resume order are superseded by the V4 checkpoint
above and MUST NOT be treated as current instructions.

Recorded at `2026-07-28T08:20:49+08:00` after the user explicitly requested
that implementation stop. This file is the only intentional edit made after
that request.

## Pause declaration

- All implementation work is stopped.
- The three active subagents were interrupted:
  - `orchestration_matrix_integration`
  - `reconciliation_compensation_rotation`
  - `workspace_typed_primitives`
- No canonical reseal, release reservation, installation, publication,
  activation, Git staging, Git commit, or Git push was performed.
- The worktree is intentionally dirty and contains both tracked modifications
  and many untracked implementation/test files. Do not clean, reset, stash,
  discard, or regenerate it when resuming.
- Branch: `main`
- HEAD/base commit: `2dc397411ad1ea5f2a43d43e881523b125bb5eec`
- Declared base tree:
  `ee7de366a818d8800b4808015f2d8ae4c4405136`
- Full/lite v3 activation remains disabled.
- Ignored local `pyproject.toml` and `uv.lock` files must be preserved.

## OpenSpec position

Always query live OpenSpec JSON again before continuing:

```sh
openspec status --change introduce-versioned-workflow-kernel --json
openspec instructions apply --change introduce-versioned-workflow-kernel --json
```

At this checkpoint, planning artifacts are complete and apply progress is
`82/104`, with these 22 tasks still open:

- `5.8`, `5.9`, `5.10`, `5.12`, `5.13`, `5.15`
- `7.12`, `7.15`, `7.16`
- `8.8`
- `12.1` through `12.12`

Do not mark any of these complete based only on the partial work described
below. In particular, Windows evidence (`12.8`), publication/CI authorization
(`12.11`), and Windows installation authorization (`12.12`) are external
gates and must remain open.

The independently approved implementation-plan provenance available before
the pause was:

```text
/private/tmp/dev-flow-openspec-plan-review/provenance/f3fd3fb2f30f20fe/introduce-versioned-workflow-kernel/eedaf2d04fd7a1f9bade88fc6241a8b63297c47823a910a0a0fe1ef13c9f77e0.7a1319332239de815c246ef2ee2bc1ba65da09689e43197757b0245699f107cf.json
```

Treat a missing temporary file as missing evidence; do not reconstruct or
invent it.

## Exact stopping point

The immediate blocker is the schema-v3 side-effect transaction lock boundary.
`command_preflight`, `command_record_test`, and `command_review_snapshot`
currently enter `_locked_state`, which holds the task and schema-v3 workspace
registry locks, and then call `execute_v3_workflow_action_transaction`.
The transaction correctly rejects insertion of its declared scope locks after
the registry lock:

```text
WORKFLOW_ACTION_TRANSACTION_LOCK_ORDER_INVALID:
scope locks cannot be inserted after registry lock
```

Resume by implementing a short-lock manager preauthorization boundary:

1. Under the task lock, load and validate the exact expected revision, install
   the manager preauthorization, and capture only the immutable planning
   inputs.
2. Release task and workspace-registry locks before planning/dispatching the
   generic transaction.
3. Keep the request-scoped manager authority lifecycle alive until the
   transaction commits or fails, then clear it exactly once.
4. Let the generic transaction perform its authoritative reload, CAS,
   declared scope locking, journal/index/containment writes, dispatch, observe,
   and proof-backed state/outbox commit.
5. Treat drift as a zero-redispatch rejection or quarantine according to the
   existing contract. Never retry a claimed effect by dispatching it again.

Do not weaken the transaction lock-order assertion to make the tests pass.

### Root-agent partial work

- `workflow_action_transaction.py` and `workflow_action_service.py` were
  generalized from a preflight-only completion edge to a catalog-derived
  `node-action-completion` selection.
- `review.py` contains typed record-test and review-snapshot effect plans,
  deterministic payload generation, exact dispatch/observe contracts, and
  receipts bound to action plan, claim, attempt, journal, index, containment,
  observation context, repositories, and semantic result.
- Schema-v3 command entry points
  `v3_record_test_command_v1` and `v3_review_snapshot_command_v1` are wired
  through `workflows/runtime/commands.json` and the handler-global audit.
- Those command entry points are not complete because they still run the
  transaction inside `_locked_state`.
- `tests/test_v3_review_command_transaction.py` was planned but does not exist
  at this checkpoint.

### Interrupted orchestration-matrix work

The interrupted subagent was routing the catalog-declared 29 orchestration
operations through the generic action transaction and shortening lock
lifetimes. Its last report said Python compilation passed and runtime import
was blocked only by stale workflow identity digests. This work has not had
independent integration review, so inspect the complete diff and rerun its
tests before trusting that report.

Important constraints already agreed:

- Planning and manager preauthorization may use a short task lock.
- `execute_v3_workflow_action_transaction` must begin with no inherited task or
  workspace-registry lock.
- A claimed dispatcher may acquire the exact declared scope lock briefly,
  re-read authoritative state/registry bytes, enforce preimage/CAS, and make
  the one allowed external write.
- Observers are read-only.
- Manager authorize may publish its verifier only as a durable claimed,
  recoverable effect. Manager revoke remains dispatch-free.
- The intended current single-dispatch action set is manager authorize plus
  orchestration artifact record, attempt abandon, dispatch handoff,
  integration capture, plan record, reconciliation complete, result accept,
  and runtime-stop record. Revalidate the catalog rather than relying on this
  note.

### Interrupted reconciliation/compensation work

`workflow_action_reconciliation.py` now contains
`WorkflowActionReconciliationCommitPlan` backed by a live
`TransitionEvaluation` and partial authoritative commit logic. The subagent
was interrupted before reporting a final test result.

Resume by verifying all of the following in source and tests:

- the evaluator runs under the exact live locks/state and binds the exact edge;
- the emitted event is the catalog canonical event with exact recovery,
  attempt, target, effect, decision, evidence, and receipt facts;
- `UNRESOLVED` consumes no evaluator, manager nonce, proof, task mutation, or
  outbox event;
- accepted, abandoned, and compensated closure commits the task/event/nonce
  before terminal archive/unblock;
- compensation uses its own claimed journal/receipt and commits that effect
  before recovery closure;
- every claimed business or compensation effect remains zero-redispatch.

### Typed primitive work

- Baseline and workspace typed effect primitives were previously implemented
  and locally tested.
- `tests/test_v3_review_effect_primitives.py` existed and its focused seven
  tests passed in a handler-aware temporary copy; two retained legacy review
  tests also passed.
- The interrupted `workspace_typed_primitives` follow-up owned only the planned
  new review-command transaction test and did not finish creating that file.

## Last observed verification

`git diff --check` was green at the pause.

A handler-aware temporary-copy run executed:

```sh
python3 -m unittest \
  tests.test_v3_review_effect_primitives \
  tests.test_orchestration_action_catalog \
  tests.test_v3_preflight_action_transaction \
  tests.test_workflow_handler_audit -v
```

It ran 33 tests and had four failures:

- three positive/lost-response/restart preflight tests failed with the exact
  lock-order error documented above;
- one handler audit rejected the private global
  `_guard_blocked_resume_target`.

The review primitive tests and the then-current orchestration catalog tests
passed in that temporary copy. The copy was made before later parallel edits,
so its generated workflow digests are stale and must never be copied into the
canonical worktree.

No full suite has passed on the current worktree. The mandatory final command
remains:

```sh
python3 -m unittest discover -s tests -v
```

## Safe resume order

1. Read `AGENTS.md`, this checkpoint, and every OpenSpec artifact selected by
   the live `instructions apply` response.
2. Run `git status --short` and preserve every existing user/agent change.
3. Review the interrupted orchestration and reconciliation diffs for
   syntactic completeness and contract consistency before editing them.
4. Fix the short-lock manager preauthorization boundary and add command-level
   transaction tests for preflight, record-test, and review-snapshot.
5. Finish and independently test the reconciliation/compensation state
   machine.
6. Finish routing the declared orchestration operation matrix through the
   generic transaction and add disjoint/overlapping-scope concurrency tests.
7. Complete CLI-only claimed/quarantined recovery end-to-end coverage.
8. Only after every identity-covered input is frozen, perform one canonical
   reseal and provenance/release-ledger sequence. Never reseal incrementally to
   hide drift.
9. Run the exact full suite, runtime/dependency audits, Python-version syntax
   checks, every bundled Skill validator, plugin/MCP/Hook/package validators,
   strict OpenSpec validation, `git diff --check`, and independent read-only
   code/spec review against the same frozen identity.
10. Leave Windows, publication/CI, and installation tasks open until their
    explicit external evidence/authorization is actually supplied.

The architectural direction remains a standard-library authoritative workflow
kernel with declarative, versioned, catalog-sealed node/action contracts.
Official Codex Skills, Hooks, MCP, subagents, Codex SDK, and Agents SDK are
integration/adaptation surfaces; they do not replace the deterministic kernel
or become mandatory runtime dependencies.
