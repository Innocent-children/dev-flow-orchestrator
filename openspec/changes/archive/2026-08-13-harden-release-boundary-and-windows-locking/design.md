## Context

The version-matched shell and PowerShell assets decode the same standard-library
Phase A verifier. Phase A downloads and verifies the index and archive, extracts
one closed artifact, and starts `lifecycle/release_lifecycle.py`. Today it adds
the caller's raw arguments after trusted `--artifact-root`, `--release-index`,
and `--release-index-sha256` values. Standard `argparse` behavior permits unique
prefixes and lets a later repeated option replace an earlier one. Phase B then
accepts the selected artifact root and validates only selected identities before
building a candidate.

The shared storage primitive has a bounded nonblocking POSIX loop. Its Windows
branch uses `LK_NBLCK`, but loops forever on contention and does not consult the
request cancellation signal. Promotion validates local assets, creates a public
release with attached assets, and then downloads canonical public URLs; an
interruption leaves no durable statement of which external phase completed.

## Goals / Non-Goals

**Goals:**

- Preserve a closed, deterministic Phase A to Phase B authority boundary.
- Detect artifact replacement after extraction and before installation effects.
- Make native Windows lock admission observationally consistent with POSIX.
- Keep release assets private as a draft until authenticated remote bytes pass
  the same full validation as local bytes.
- Make promotion interruptions bounded, machine-readable, and safely resumable.

**Non-Goals:**

- Signing, Sigstore, transparency logs, mirrors, or update channels.
- Arbitrary historical rollback or any lifecycle outcome/schema change.
- Lock-file format, lock order, Controller state, membership-lock, or Controller
  state-machine redesign.
- General secret scanning, CI restructuring, real GitHub mutation in tests, or
  claims of native Windows/real Codex evidence from this host.

## Decisions

### Parse and normalize only a closed Phase B user option set

Phase A recognizes exactly `--runtime-root`, `--bin-dir`,
`--marketplace-file`, `--codex-home`, `--data-root`, and `--lock-timeout`.
Every option takes exactly one non-empty value and may use either a separate
argument or the `--option=value` spelling. The parser scans the original token
sequence before `argparse`, rejects a second occurrence regardless of spelling,
rejects unique-prefix abbreviations, rejects positional input and an extra `--`,
and emits canonical two-token pairs.

Repository, version, archive name, index digest, artifact root, release-index
path, source identity, release identity, and transaction identity are never
accepted from this caller-controlled channel. Both bootstrap templates continue
to pass arguments as arrays so shell quoting does not reinterpret values.

Phase B also disables option abbreviation. Its artifact root is
`Path(__file__).resolve().parent.parent`; there is no Phase B `--artifact-root`
input. The index path and digest remain Phase A-owned ephemeral evidence.

### Recompute the live artifact inventory at the Phase B entry

The shared verifier exposes a directory-inventory verifier that:

1. validates the artifact root name and safe directory ancestry;
2. reads the digest-bound strict manifest under the existing byte cap;
3. enumerates every descendant without following links or reparse points;
4. binds directory type/mode and regular-file type/mode/size/SHA-256 using the
   existing portable artifact contract; and
5. requires exact equality with the manifest, including wheel and lifecycle
   entries, before Phase B constructs paths or invokes candidate building.

The check uses actual filesystem observations, not manifest presence alone.
Candidate construction repeats the check at its own pre-install boundary so a
wheel or lifecycle replacement between Phase B entry and construction fails
before `uv`, copying, smoke execution, or installed-state mutation.

### Share one lock-admission algorithm across host branches

Timeout validation and deadline creation move before the platform branch. Both
branches check cancellation before each nonblocking attempt. After an OS lock is
obtained, ownership is recorded immediately, then cancellation and deadline are
checked again before yielding the critical section.

Contention sleeps for the smaller of the fixed poll interval and remaining
time. Expiry raises `STATE_LOCK_TIMEOUT` with the selected timeout; cancellation
raises `REQUEST_CANCELLED`. A raw lock obtained on an exceptional path remains
owned by `finally`, which unlocks it before descriptor close. Non-contention OS
failures retain `STATE_LOCK_FAILED`. No byte, mode, state, or acquisition-order
format changes.

### Promote through a journaled Draft Release

Promotion uses an authenticated official GitHub API adapter with a fake adapter
in tests. The ordered phases are:

1. validate the exact four local assets and all component digests;
2. resolve the remote `v<version>` commit and tree and require equality with the
   index source assertions;
3. prove no same-version release exists, or resume only the exact matching draft
   recorded by this journal;
4. create a Draft Release bound to the proven commit;
5. upload all four assets and read back their names and API identities;
6. download every asset through the authenticated official asset API and rerun
   full asset and component validation;
7. publish only after local and authenticated remote identities are equal.

The promotion journal is a closed JSON object with a fixed byte cap, canonical
serialization, atomic replacement, repository/version/source/local-digest
identity, current phase, draft release ID, uploaded asset IDs, final digests,
and last bounded diagnostic. It contains no credentials or downloaded bytes.
On rerun, immutable identity fields must match. A recorded draft is re-read and
resumed only if its ID, tag, target commit, draft status, and asset state are
provable. An already published same-version release is never overwritten or
redefined; inability to prove identity also fails closed.

## Risks / Trade-offs

- A second inventory walk adds bounded local hashing before candidate work. It
  is deliberate because manifest-only checks do not observe replacement.
- A crash immediately after an external mutation can precede the next journal
  write. Recovery therefore re-reads the official release state and only adopts
  the unique matching recorded draft; ambiguous state is preserved and refused.
- Native Windows behavior remains unproven on a non-Windows host even when the
  common algorithm and fake branch tests pass.

## Migration Plan

1. Add failing regressions for each observed gap.
2. Add the closed Phase A option parser and Phase B derived-root/live-inventory
   checks, including shell, PowerShell, special-path, and replacement coverage.
3. unify file-lock admission semantics and add native-Windows-applicable
   multiprocessing timeout/cancellation/release tests.
4. replace promotion with the Draft/API/journal sequence and fake-only tests;
   update the operator guide.
5. bump `0.6.6` to `0.6.7`, run focused tests, then execute the requested final
   repository gates exactly once.

## Open Questions

None. Any extension beyond the stated boundaries requires another OpenSpec
change.
