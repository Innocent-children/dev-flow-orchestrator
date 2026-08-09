## Context

The current lifecycle treats a mutable source path as the identity of the
verified package. Verification happens before runtime build, launcher and
marketplace writes, Codex remove/add, health, and final receipt output. The
runtime receipt describes a location, selected inputs, and the Python executable,
but not the bytes installed there. Rollback saves only selected files and re-adds
the plugin from the already-updated checkout. Uninstall then treats a shallowly
valid receipt as authority to recursively remove a complete runtime root.

The design must therefore bind creation, activation, recovery, startup, and
removal to the same release evidence. It must also distinguish filesystem steps
that can use atomic replace from Codex plugin operations that can only be
observed and compensated.

## Goals / Non-Goals

**Goals:**

- Activate only bytes derived from one verified Git commit/tree and identified by
  one canonical candidate digest.
- After any recorded clone or fast-forward selects the authoritative commit, keep
  that selected checkout baseline unchanged across successful, failed, and
  rolled-back lifecycle operations.
- Make install, upgrade, and repair recoverable from a durable transaction journal,
  immutable previous authority when conforming, and truthful legacy-observed
  component evidence otherwise.
- When a conforming installed launcher invokes the startup verifier, fail closed
  before candidate import when runtime, receipt, active identity, Python, package,
  metadata, dependency, or verifier evidence does not match.
- Remove only exact installer-owned entries while preserving all unknown content.
- Keep POSIX and PowerShell safety invariants identical without claiming native
  Windows evidence on this host.

**Non-goals:**

- Global atomicity across filesystem and external Codex operations.
- Resistance to an actor with permission to replace the launcher, or to replace the
  verifier, receipt, runtime, and active record coherently.
- Silent adoption or deletion of legacy runtime content.
- Re-enabling source checkout deletion.
- Changing public installation mode, task data, MCP protocol, or Controller state.

## Decisions

### 1. Use a Git-tree export plus staged plugin and wheel artifacts

The installer first resolves the expected origin, attached `main`, fetched commit,
and Git tree object. It captures the checkout's HEAD, index identity, and
machine-readable tracked, untracked, and ignored status. It then exports the
verified tree from Git object storage into a transaction-owned staging directory.
No build or activation input is subsequently read from the checkout.

The export is validated against the Git tree entry set. Its canonical manifest
records path bytes, entry type, Git mode, executable bit, blob/object identity,
file digest, and symlink target. Extraction rejects absolute paths, traversal,
duplicate paths, unsupported special entries, or an entry whose type or bytes do
not match the tree. This preserves executable files, symbolic links, and package
metadata. A detached worktree alone is rejected as authority because it remains a
writable checkout. A wheel alone is insufficient because Codex also consumes
plugin assets outside the Python distribution.

The option evaluation is:

| Option | Decision | Reason |
|---|---|---|
| Git archive | selected for object-tree export | It reads committed objects rather than worktree bytes and carries Git file mode and symlink entries; safe extraction and an independent canonical manifest remain mandatory. |
| Detached temporary worktree | rejected as sole authority | It is another writable checkout and does not by itself bind later consumers to unchanged bytes. |
| Wheel artifact | selected for the Python distribution only | It gives a concrete package artifact but does not contain every Codex plugin asset. |
| Staged release directory | selected for activation | It holds the validated plugin tree, wheel evidence, manifests, and release-specific activation target. |

The resulting combination is:

1. Git object/tree export for source authority;
2. a staged release-specific plugin directory for Codex activation;
3. a wheel built from that staged directory;
4. a staged managed runtime containing the installed wheel and locked
   dependencies.

The `candidate_id` is a SHA-256 digest of a versioned canonical candidate manifest
covering the source commit, source tree object, exported entry inventory, plugin
manifest, generated activation overlay, wheel bytes, distribution identity, and
dependency-lock digest. Build,
runtime promotion, marketplace target, plugin activation, launcher configuration,
health, active installation record, and ownership manifests all carry that same
identity.
The digest identifies actual content; reproducible wheel bytes across tool versions
are not assumed.

Content that contributes to the candidate digest does not embed that digest in its
own bytes. “Carry” means the enclosing sealed manifest, receipt, or ownership record
associates the exact artifact digest with `candidate_id`. The non-secret activation
ID and generated `.mcp.json` overlay are complete before final candidate sealing and
their bytes are included in the candidate manifest. The manifest digest is computed
after wheel/overlay validation and is stored outside the wheel and plugin tree,
avoiding a candidate self-reference. The later `release_id` is computed from a
separate canonical tuple of schema, candidate ID, transaction ID, target-root
identity, and generation. The release manifest binds that content-only candidate and
release ID to its host paths; the release ID is not defined as a digest of bytes that
embed itself.

The sealed directory is made non-writable where the host permits, but permissions
are defense in depth rather than the trust root. Each consumer verifies the
manifest/digest immediately before using or promoting the artifact. A checkout
change after sealing cannot change the candidate. Drift before sealing or any
candidate mismatch fails before activation.

The wheel builder receives a disposable, manifest-matching build copy and separate
output directory inside transaction staging. Build backend residue is never written
to the sealed plugin release or authoritative checkout. The wheel and its installed
inventory are added to the final candidate manifest only after build validation.

### 2. Keep the release bundle separate from authoritative source

The candidate plugin tree is stored in an installer-owned, release-specific local
artifact store that the personal marketplace can address. The runtime remains
under the resolved managed-runtime authority. A shared `release_id` binds plugin
and runtime assets across those roots. The marketplace continues to contain one
local `dev-flow-orchestrator` entry and preserves unrelated entries, but that entry
targets the sealed plugin release, never the source checkout.

New transaction, release, and active-record entries live in a schema-versioned
installer namespace below each resolved root. The selected root itself is not
claimed owned merely because it exists or has a legacy marker. A pre-existing
collision at the new namespace fails closed; the installer does not relabel it.

This changes an internal path, not the public mode: the same install command,
personal marketplace, plugin ID, and bundled MCP registration remain in use. If
the selected platform roots cannot express a safe local candidate locator, the
installer fails before marketplace or Codex mutation.

Before candidate sealing, the transaction creates a non-secret unpredictable
`activation_id` distinct from `candidate_id`. The candidate manifest binds it. The
staged plugin then adds a canonical activation overlay: its marketplace source is
the release-specific sealed plugin root, and its bundled `.mcp.json` retains the
public server name/command/args while adding `DEV_FLOW_ACTIVATION_ID` to the internal
transport environment. The overlay is separate from the Git tree export and is
included in the final candidate manifest before `candidate_id` is derived. The later
release manifest binds that candidate to the host-specific `release_id` and sealed
root without a digest self-reference.

Before removing a previous plugin, the installer feature-detects that host read-back
reports both the normalized local plugin source path and bundled MCP transport
environment. The probe uses the sealed candidate with a disposable isolated
CODEX_HOME, marketplace, data, runtime, and temporary authority; it never reads or
registers against the real profile. Its isolated add/list/MCP-list/remove sequence
must demonstrate exact local-source and transport-environment read-back, including
an initially empty profile, before any real marketplace or Codex mutation. Probe
artifacts are transaction-owned and follow exact ownership cleanup. A failed probe
leaves real authorities unchanged.

After the real add, the installer requires `codex plugin list --json` to report the exact
sealed plugin root and `codex mcp list --json` to report the exact activation ID.
That observation, the release manifest/launcher digests, and installed health run
through the reported command prove which sealed release Codex selected. Fixed plugin
ID, product version, and enabled state are logical visibility only and cannot
distinguish same-version A from B. Missing, unstable, duplicate, or mismatched source
or activation read-back fails closed. If the capability is absent, failure occurs
before Codex mutation. If a Codex call has occurred and exact identity becomes
unavailable or ambiguous, the external component is `unknown`, no identity-specific
removal is issued, and the transaction becomes `partial`. This internal descriptor
preserves the public plugin ID, bundled mode, and MCP schema.

### 3. Acquire one profile lifecycle lock before observation

One supported personal Codex profile has one Dev Flow lifecycle lock. Its identity
is the normalized profile root plus product ID, and its process-independent lock
object lives in a validated installer-controlled profile control path that is not a
source, runtime release, launcher, marketplace, or active-record target. Replacing or
removing those assets therefore cannot replace the lock authority.

Install, upgrade, repair, and uninstall for the profile acquire that same single lock
before they classify previous state, inspect an unfinished journal, create a new
journal, or mutate any product authority. Source, managed-runtime, launcher,
marketplace, active-record, and journal roots may resolve to different paths, but
they are all subordinate to the profile lock. There are no per-root lifecycle locks
and therefore no multi-lock ordering protocol. Marketplace generation remains
guarded data observed while the profile lock is held, not a nested lock.

The lock remains held through every provisional and external effect, compensation,
the durable `committed`, `rolled-back`, or `partial` terminal record, and immediate
read-only completion observations. Contention follows one bounded documented wait
policy or returns `busy` before journal creation or product mutation. An abnormal
exit releases the process lock but not the journal; the next holder resolves that
journal before starting a new transaction. Compensation is authorized only by the
held operation's journal and cannot infer ownership of another transaction's state.

Tests start real overlapping processes for install/install, repair/install,
install/uninstall, and repair/uninstall. They assert that only the lock holder can
classify previous state or create a journal, the waiter remains outside the
transaction or returns pre-mutation `busy`, and a later entrant re-observes the first
operation's terminal authority. POSIX and PowerShell adapters implement the same
single-lock contract; native Windows execution remains subject to the platform
evidence boundary below.

### 4. Create a durable transaction before the first mutable effect

Every fresh install, upgrade, and repair receives an unpredictable
`transaction_id` while holding the profile lifecycle lock. Before cloning or
fast-forwarding source, creating candidate staging, or changing any other
installer-managed or external asset, the installer atomically writes and fsyncs a
bounded `prepared` transaction journal. Fields whose content cannot exist yet are
explicit closed-schema states, not guessed identities:
`candidate=unresolved`, `selected_source=unresolved`, `wheel=unresolved`, and
`lock=planned(<requested lock identity>)`. The prepared journal contains:

- operation and transaction schema versions;
- the previous authority class (`none`, `conforming`, or `legacy-observed`) and all
  previous identities that are actually available;
- a candidate release slot, requested origin/ref and dependency-lock plan, all with
  explicit unresolved values until their bytes exist;
- operation-start source identity and the planned clone/fast-forward transition;
- expected roots and root identities without silently claiming their contents;
- previous and candidate launcher, marketplace member, runtime, plugin, active
  record, and ownership identities;
- per-component planned, observed, restored, and recovery states;
- state sequence and timestamps.

The lifecycle states are:

```text
prepared -> staged -> promoted -> activating -> activated -> verified -> committed
any pre-commit state -> failed -> rolled-back | partial
```

`prepared` has no product mutation and does not claim a candidate identity. Source
selection, object-tree export, and transaction-owned staging execute under that
journal. The single `staged` transition atomically replaces all unresolved candidate
fields with the selected commit/tree, candidate manifest digest, candidate and
release IDs, wheel identity, and final lock identity. Those values are immutable in
all later states. `staged` has a complete sealed candidate.
`promoted` means release directories exist but are not active. `activating` and
`activated` cover local activation assets and observed Codex state. `verified`
means candidate visibility, MCP health, and applicable CLI smoke passed.
`committed` is reached only at the commit point below. `rolled-back` requires a
verified restoration. `partial` is a durable, truthful incomplete recovery.

Every transition uses temp-file write, file fsync, atomic same-filesystem replace,
and parent-directory fsync where supported. On restart, the installer must inspect
an unfinished journal before starting another operation. It may resume only a
proven idempotent step; otherwise it compensates or reports partial. It never
interprets absence of a success receipt as proof that an external Codex operation
did not occur.

### 5. Define one final active-record replace as the commit point

Candidate staging and promotion occur before external activation. The generic
managed bundled launcher, applicable CLI launcher payloads, candidate activation
overlay, and marketplace bytes are staged and validated. The
installer then performs the ordered activation plan, observing actual state after
each external call:

1. install or validate the managed startup verifier, generic bundled launcher, and
   applicable CLI launcher;
2. replace only the owned marketplace member with the candidate release locator;
3. remove the previous plugin when required;
4. add the candidate plugin;
5. verify candidate plugin identity and bundled MCP registration;
6. run installed MCP health against the candidate;
7. run applicable final CLI/MCP smoke using the candidate activation descriptor;
8. atomically replace the versioned active installation record.

Before step 6, the staged transaction creates and seals a bounded activation
descriptor mapping the exact `activation_id` to transaction ID, candidate/release
IDs, candidate manifest digest, promoted runtime path and receipt digest, verifier
and launcher identities. The activated journal binds the descriptor digest; the
descriptor names the expected journal schema/state but does not digest the journal.
The installer invokes the observed generic command/environment in
`precommit-health` mode with the exact journal path. The verifier accepts only the
journal-bound descriptor, confirms that the journal names the same `activated`
transaction under the held lifecycle authority, validates the candidate
receipt/runtime, and executes B. Health evidence records the executed activation,
candidate, and release IDs plus a release-specific runtime marker. Same-version B
must therefore run; matching configuration metadata alone cannot pass health.

Normal installed startup has no `precommit-health` authority: it ignores transaction
descriptors and resolves only the committed active record. After commit, the active
record binds the activation-descriptor digest as historical activation evidence,
while normal launch continues through committed authority.

Step 8 is the transaction commit point. The active record includes the release,
candidate, activation descriptor, runtime receipt, launcher, marketplace member,
ownership manifest, and terminal-journal identities. While the journal remains
`verified`, the installer builds
and fsyncs a closed `committed` active-record payload. A single same-filesystem
atomic replace publishes that payload at the active-record path. That published
record is the authoritative terminal transaction record; no second journal
transition is required. Recovery reads the active record before treating a matching
pre-commit journal as unfinished. A matching committed `transaction_id` closes the
stale journal logically. Because the active ownership envelope binds that exact
journal, it remains immutable for the lifetime of the active release and is removed
only by uninstall after active attestation is no longer required. Routine cleanup
does not delete or rewrite it. No product mutation follows the commit point; success
output is a view of the already-durable active record.

Read-only post-commit observation may report whether launcher, marketplace, and
Codex authorities still match. Drift observed after atomic active-record replace
does not retroactively make the committed mutation fail and never triggers automatic
compensation. The response reports `committed=true`, component freshness as `false`
or `unknown`, and `blind_retry_safe=false`; recovery begins by reading the committed
record.

Single files and release directories can use atomic same-filesystem promotion.
Two launchers, a shared marketplace file, runtime and plugin directories, and
Codex state cannot be replaced as one atomic unit. The design therefore does not
claim global atomicity. Until the active record commits, every external or
multi-file effect is provisional and covered by compensation.

Lifecycle writers serialize marketplace changes with a versioned lock/generation,
re-read under that authority, and merge only the Dev Flow logical member. Existing
files are published only through a platform adapter that atomically exchanges the
candidate with the current path or performs replacement while retaining the exact
displaced file; absent files use atomic no-clobber creation. The installer fails
before marketplace or Codex mutation if the host cannot supply those semantics.

After publication it checks that the displaced bytes equal the captured generation
and re-observes the canonical path. A conflict retains displaced, candidate, and
current versions under bounded transaction paths and conditionally restores only
when the candidate still owns the canonical path; otherwise it records `partial`.
Compensation re-reads the latest valid document and changes only the Dev Flow member,
never copies a whole old snapshot over new unrelated entries. An uncoordinated
writer still cannot be serialized by the lifecycle lock, and the candidate may be
briefly visible before a conflict is observed. The design claims preservation of
installer-displaced versions, not a portable linearizable file CAS or global
serialization.

The platform adapter may use a feature-probed atomic rename-exchange facility on
POSIX and `File.Replace` with a retained backup on Windows. No-clobber creation uses
an exclusive create/link primitive. Tests verify the semantic result rather than a
specific syscall. A fallback that performs an unconditional replace and deletes the
displaced file is non-conforming.

### 6. Restore the real previous release or report partial

The journal classifies previous authority before candidate activation. A
`conforming` previous release has a sealed plugin release, runtime, active record,
launcher identities, marketplace member, receipt, and ownership records retained
through the candidate transaction. It is addressed by its old release and candidate
IDs. The current mutable checkout and newly staged candidate are never used as a
substitute.

A Phase 0 or older installation is `legacy-observed`: the journal records only the
logical plugin/version, paths, byte snapshots, health observations, and shallow
receipt evidence that can actually be read. It does not relabel those assets sealed
or exact-owned. A successful transaction may install and commit a new conforming
release beside the retained legacy runtime. After any external mutation, recovery
may conservatively restore captured local bytes and re-observe the legacy plugin,
but it can never report `rolled-back` or “restored” because immutable previous
identity is unavailable. Its terminal failure result is `partial`, with the legacy
path retained and each component reported. This gives existing installations an
upgrade path without deleting, adopting, or pretending to seal their old runtime.

On any pre-commit failure after a provisional effect with a conforming previous
release, compensation works from the journal and sealed previous artifact. It
observes Codex state even when a remove or add command returned non-zero, removes a
candidate only when a candidate-specific activation observation matches, restores
exact previous local assets, re-adds the plugin from the sealed previous plugin
tree, and restores the previous active record. It then verifies:

- observed active plugin identity is the previous release;
- the expected marketplace member and launchers match;
- bundled MCP registration is exact;
- previous runtime attestation passes;
- installed MCP health and applicable CLI smoke pass.

Only all-successful verification yields `rolled-back` and a “restored” statement.
For fresh install, previous identity is `none`; compensation removes only exact
transaction-created non-source entries that still match their ownership records,
retains the source checkout under DFO-AUDIT-002 containment, and verifies that no
candidate plugin remains active.

If compensation or its verification fails, the journal transitions atomically to
`partial`. The response is non-success and records the observed active identity as
previous, candidate, none, or unknown; every component as restored, candidate,
absent, retained, or unknown; unreferenced release paths; precise recovery steps
bound to sealed IDs and paths; and whether blind retry is safe. Blind retry defaults
to false. Generic remove/add guidance is not sufficient.

The transaction never resets, cleans, or rewrites source to simulate rollback. A
planned clone or fast-forward is recorded as its own source component transition.
If failure leaves source different from the operation-start identity, it preserves
that state, relies on the sealed previous release for product restoration, and
reports `partial` rather than claiming every transaction component was rolled back.

### 7. Use a content-attesting runtime receipt

The new runtime receipt is closed, versioned canonical JSON. It binds at least:

- receipt schema, `transaction_id`, `release_id`, `candidate_id`, and
  `activation_id`;
- source commit and Git tree object identity;
- candidate manifest and artifact digest;
- wheel filename/digest and distribution name/version;
- canonical installed distribution metadata digest;
- wheel `RECORD` or an equivalent exact installed-file inventory with every
  installed package entry's relative path, type, size, and digest;
- exact normalized dependency name/version set, distribution metadata and record
  digests, selected artifact hashes, and dependency-lock digest;
- Python executable content identity, version, implementation, ABI, architecture,
  bitness, and venv configuration identity;
- startup verifier and launcher path-relative identities, content digests, modes,
  and expected active-record schema/generation;
- expected activation-descriptor path/schema, `activation_id`, and expected
  transaction-journal path/schema, with no activation-descriptor or journal digest;
- runtime root/release identity and ownership-manifest digest;
- creation platform, platform tag, Python version, and timestamp.

The identity graph has one construction direction:

```text
candidate manifest -> ownership body -> runtime receipt
  -> activation descriptor -> terminal pre-commit journal -> committed active record
```

The ownership body binds the transaction, release, candidate, expected receipt
path/schema, and expected active-record path/schema/generation, but contains no
receipt or downstream digest. The runtime receipt contains the ownership-body
digest. The activation descriptor contains the receipt digest, and the terminal
journal contains the descriptor digest. The active record binds those upstream
identities. Its `self_digest` is
defined over canonical active-record bytes with the `self_digest` field omitted, so
it is constructible and independently recomputable rather than recursively hashed.
All inventories are canonical and bounded.
Unexpected duplicate distributions, missing metadata, extra dependencies, or
unrepresented installed files are mismatches.

### 8. Verify before importing candidate runtime code

Both conforming launchers enter a small installer-managed verifier outside the
candidate runtime. A host Python selected and recorded by the installer invokes it
with `-I -S -B` and bytecode disabled. The conforming launcher is the local bootstrap
precondition: it checks its embedded verifier descriptor and passes only bounded
root/active-record locations. The verifier parses the active record and receipt,
validates closed schemas and path containment, recomputes Python, package, metadata,
dependency, ownership, release, and the presented launcher identity, and only then
executes the attested runtime or plugin command.

When that conforming bootstrap is invoked, missing receipt, malformed JSON,
incompatible schema, wrong release/pointer, a still-verifier-invoking launcher whose
identity differs, wrong Python, package-byte or metadata drift, dependency missing,
extra, or version drift all fail closed before importing Dev Flow. The error names
the mismatch class and directs the operator to repair; startup does not mutate or
silently rebuild.

Repair applies the same verifier. A complete match permits reuse. Every mismatch,
including a legacy receipt, builds a new staging release and activates it through
the transaction; it never repairs a suspect runtime in place.

Installer and repair independently validate installed launcher bytes before commit
or reuse. A replacement launcher can bypass the verifier entirely, so invocation of
an unmodified conforming launcher is an explicit precondition of the startup
guarantee; direct launcher replacement is detected by installer/repair integrity
checks, not guaranteed to be rejected by the replaced launcher's execution path.
This boundary detects accidental corruption and content drift under ordinary local
permissions. It does not protect against a same-privilege or more-privileged actor
that can replace the launcher or coherently replace other local attestation assets.
No independent trust root is introduced, so the product must not claim hostile
tamper resistance.

### 9. Keep the post-selection source baseline byte-identical

The checkout is used for Git authority and export only. Any unavoidable Python
command whose script path is in source uses both `-B` and a command-scoped
`PYTHONDONTWRITEBYTECODE=1`. Build, validation, health, and launcher inputs run from
the sealed candidate whenever possible.

The installer records operation-start source identity and any planned authoritative
clone or fast-forward as separate transaction evidence. After that selected commit
is established and before sealing, it captures the source immutability baseline.
After install, repair, upgrade, failure, and rollback, it compares final HEAD, tree,
index identity, and NUL-delimited porcelain including tracked, untracked, and
ignored entries to that post-selection baseline. No source change is allowed after
the baseline. A fresh clean checkout remains empty under
`git status --porcelain --ignored`. Existing unrelated ignored content allowed by
the authoritative-installation base contract may remain only when its exact
baseline/final inventory is unchanged and the Git-tree export excludes it. The
installer never deletes an ignored entry to manufacture cleanliness.

No `__pycache__`, `.pyc`, build directory, wheel output, egg-info, or other
intermediate is written to source. Tests include spaces, Unicode, and apostrophes
in authorities. Source is retained after Phase 1 by DFO-AUDIT-002 containment.

### 10. Remove runtime content only through exact ownership

Exact ownership is a closed, canonical, versioned record set. Its upstream ownership
body is bound to the transaction, release, candidate, expected receipt path/schema,
launcher identities, and expected active-record path/schema/generation. For every
release asset it records root ID, relative path, entry type, file digest and size,
executable/mode information, symlink target, release ID, and parent-directory
ownership. The body does not inventory its own bytes or the later receipt/active
record bytes. The downstream committed active-record ownership envelope inventories
the ownership-body file, runtime receipt, activation descriptor, and terminal
pre-commit journal by exact digest and identifies its own fixed
path/schema/generation plus the constructible `self_digest` described above.
This preserves per-entry authority without a recursive self-hash or receipt/record
cycle.
Shared marketplace ownership is represented as an exact logical member, not
ownership of the whole user file. No record infers ownership merely from current
directory contents.

Uninstall acquires the lifecycle lock, validates receipt and manifest, and handles
each entry without following symlinks or reparse points. Files and symlinks are
renamed to transaction quarantine and deleted only after exact revalidation.
Release directories may be atomically quarantined, after which their entries are
enumerated again and deleted individually. An entry that is missing, changed,
unknown, special, or concurrently replaced is retained in quarantine or in place.
Owned directories are removed deepest-first only when empty at removal time and
their own ownership is proven. Runtime and release roots are never passed to a
recursive deletion primitive.

Unknown content at the runtime root, active or inactive release, venv,
site-packages, scripts/bin, metadata, symlink, reparse point, socket, FIFO, or other
special entry produces a truthful partial result with the exact retained path and
manual inspection guidance. A concurrent entry appearing during removal is
preserved by the same rule. Other exact-owned entries may be removed and reported
separately; task data and unrelated marketplace members remain byte-identical.

### 11. Treat legacy runtimes conservatively

A runtime or release without the new exact ownership manifest, or with a missing,
legacy, malformed, or mismatched receipt, is never recursively removed and never
silently adopted. Repair may construct and activate a new attested release beside
it, but retains the legacy path and reports it for inspection. A future adoption
workflow would require its own explicit, auditable specification and cannot define
the current contents as installer-owned by enumeration alone.

New launchers fail closed on a legacy active receipt and direct repair. Software
cannot retroactively change an old launcher before upgrade; compatibility guidance
states that startup attestation begins only after a successful conforming
repair/upgrade installs the verifier and active record. A failed first transition
from legacy authority remains truthful `partial` after any external effect and does
not claim immutable rollback.

Runtime ownership and source ownership remain distinct schemas/domains. The new
manifest may reuse structural primitives in a future source proposal, but it grants
no source deletion authority now. This change carries the complete modified Windows
uninstall Requirement that retains source, so applying or archiving Phase 1 against
the current canonical main spec cannot leave the earlier default-deletion SHALL in
force. The composed target specification is checked directly and does not depend on
which active change is archived first. Default, keep-source, and unsupported explicit
removal requests all retain source; re-enabling source deletion remains a separate
acceptance decision.

## Failure and Receipt Semantics

- Failure before any mutation: non-success, no candidate active, previous state
  unchanged, transaction may close as `failed`.
- Failure after provisional effects with verified compensation: non-success,
  transaction `rolled-back`, previous release proven healthy.
- Failed or uncertain compensation: non-success, transaction `partial`, explicit
  active/component observations and `blind_retry_safe=false` unless proven.
- Active-record replace succeeds: transaction committed. No later failure is
  reported as if the mutation never happened; response loss requires reading the
  active record before retry.
- Legacy/unknown ownership on uninstall: partial preservation, never a complete
  removal claim.

## Risks / Trade-offs

- Side-by-side candidate and previous releases use more disk. They are necessary
  for truthful rollback; cleanup is a separate exact-ownership transaction.
- Full startup inventory verification adds latency. Correctness takes priority;
  optimization may cache only with a separately validated invalidation authority.
- A shared marketplace and external Codex state remain observable between steps.
  The journal and verifier make that interval recoverable, not globally atomic.
- Conservative legacy handling leaves disk behind and may require manual cleanup.
- POSIX can provide dynamic evidence in this phase's future implementation. Native
  Windows behavior remains unverified until run on a supported isolated host.
