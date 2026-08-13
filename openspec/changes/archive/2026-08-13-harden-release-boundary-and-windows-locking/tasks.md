## 1. Preserve Reproduction Evidence

- [x] 1.1 Add and run a minimal regression proving Phase A currently accepts a
  caller-supplied artifact identity override.
- [x] 1.2 Add and run a minimal regression proving the Windows lock currently
  enters after post-acquire cancellation.
- [x] 1.3 Add and run a minimal regression proving promotion currently creates a
  non-draft release before remote-byte verification.

## 2. Close the Phase A to Phase B Boundary

- [x] 2.1 Implement a closed Phase A option scanner with no abbreviations,
  deterministic duplicate rejection, protected-identity rejection, and exact
  support for separate and `=` values.
- [x] 2.2 Keep both shell and PowerShell templates array-safe and cover spaces,
  apostrophes, Unicode, duplicate options, abbreviations, `--option=value`, and
  protected bootstrap/release identity input.
- [x] 2.3 Remove caller selection of the Phase B artifact root, derive it from
  the executing lifecycle location, and disable Phase B abbreviations.
- [x] 2.4 Recompute and compare the complete current artifact inventory at Phase
  B entry and candidate pre-install boundaries; cover replaced wheel and
  lifecycle helpers before any install or execution effect.

## 3. Align Native Windows Lock Semantics

- [x] 3.1 Share timeout validation, deadline, cancellation checks, bounded poll,
  and post-acquisition linearization between Windows and POSIX branches.
- [x] 3.2 Prove `STATE_LOCK_TIMEOUT`, `REQUEST_CANCELLED`, post-acquire rejection,
  and exact raw-lock release with deterministic branch tests.
- [x] 3.3 Add native-Windows-applicable multiprocessing contention tests without
  treating skips or non-Windows execution as native evidence.

## 4. Harden Release Promotion

- [x] 4.1 Validate the four local assets and remote tag commit/tree against index
  source identity before the first release mutation.
- [x] 4.2 Create or resume only a proven matching Draft Release, upload the exact
  assets, and reject every published or unprovable same-version release.
- [x] 4.3 Re-download through the authenticated official asset API, verify asset
  and component digests, and publish only after exact equality.
- [x] 4.4 Add a bounded closed atomic promotion journal with safe phase recovery
  and fake runner/API tests for success, mismatch, interruption, resume, and
  refusal paths. Do not mutate real GitHub state.
- [x] 4.5 Update `docs/PROMOTION.md` to document Draft isolation, authenticated
  re-download, journal recovery, and immutable refusal.

## 5. Version and Verification

- [x] 5.1 If the repository remains at `0.6.6`, update every authoritative
  product version reference to `0.6.7` without creating a tag or Release.
- [x] 5.2 Run only the focused A/B/C tests while iterating and record skips and
  simulated evidence truthfully.
- [x] 5.3 Run the requested final `uv sync --locked`, package validation, complete
  unittest discovery, and strict all-OpenSpec validation once after all focused
  work passes.
- [x] 5.4 Report initial branch/HEAD, version change, implementation evidence,
  and the absence of native Windows, real GitHub, and real Codex evidence.
