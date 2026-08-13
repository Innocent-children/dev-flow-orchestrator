## Why

The current release path leaves three narrow but material gaps in contracts that
are already intended to be closed. Phase A appends arbitrary user arguments
after its verified Phase B identity arguments, while both Python parsers accept
abbreviations and repeated options. Phase B accepts an artifact root selected by
arguments and checks manifest identity without rechecking the complete live
artifact inventory. The Windows `msvcrt.locking` branch also omits the timeout
and cancellation linearization used by POSIX. Finally, promotion creates a
public release before re-downloaded bytes are verified and has no durable
recovery record around external mutations.

These gaps allow cross-boundary identity replacement, unbounded Windows lock
waits, and public visibility of assets that have not passed final remote-byte
verification.

## What Changes

- Close Phase A user input to the six installation-destination options and the
  lock timeout. Reject abbreviations, repeated options, positional input,
  bootstrap/release identity options, and malformed values deterministically;
  support both `--option value` and `--option=value` without losing spaces,
  apostrophes, or Unicode in native paths.
- Make Phase B derive the artifact root from the executing versioned lifecycle
  directory, keep release-index identity supplied only by Phase A, and compare
  the complete current artifact inventory with the digest-bound manifest before
  candidate construction, copying, dependency installation, or further
  lifecycle helper execution.
- Give the native Windows file-lock branch the same bounded timeout and
  cooperative cancellation semantics as POSIX, including checks while waiting
  and immediately after acquisition and exact release on every exceptional
  path. Lock bytes, state schemas, and acquisition order remain unchanged.
- Promote only through local four-asset validation, remote tag commit/tree
  identity validation, Draft Release creation, upload, authenticated official
  API re-download and full component verification, and explicit publication.
  Persist each phase in a bounded, closed, atomically replaced promotion journal
  that can safely resume a matching draft and refuses unprovable or already
  published same-version state.
- Add focused fake-only release API/runner tests, cross-platform lock semantics
  tests, native-Windows-applicable multiprocessing tests, bootstrap argument
  boundary tests, and wheel/lifecycle replacement tests. No real GitHub
  mutation is part of this change's test evidence.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `versioned-release-artifact-installation`: harden the existing two-phase
  verifier boundary, Windows lifecycle locking, and release-promotion gate.

## Impact

The change is limited to release bootstrap/verifier code, versioned lifecycle
entry and candidate construction, the shared host file-lock primitive, release
promotion and its operator guide, focused tests, package validation, and a patch
version update. It preserves checkout-free installation, the bundled Skill,
STDIO MCP, stable dispatchers, managed runtime, Controller task data, Python
3.10–3.14, and `committed`/`rolled_back`/`partial` lifecycle outcomes.

It does not add signing, Sigstore, mirrors, automatic updates, arbitrary
historical rollback, general secret scanning, broad CI changes, Controller or
membership-lock redesign, or unrelated cleanup.
