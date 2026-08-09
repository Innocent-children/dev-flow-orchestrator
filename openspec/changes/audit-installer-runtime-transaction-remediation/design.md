## Context

The current installer verifies a Git checkout and then continues to consume that
writable path. The runtime receipt is not a startup gate, rollback can use the
already-updated checkout, and uninstall recursively deletes a runtime after only a
shallow check. Install and repair also execute source-side Python in a way that
creates ignored bytecode.

`REPRODUCTION.md` records these failures on the current-head baseline. This design
uses focused extensions to the existing lifecycle rather than a general installation
platform.

## Goals / Non-Goals

**Goals:**

- Keep the selected authoritative checkout unchanged by installer-generated files.
- Build and activate one release exported from the verified Git commit/tree.
- Verify receipt v2 before Dev Flow import and before repair reuse.
- Restore the actual sealed previous release after a late failure, or report the
  observed mixed state as partial.
- Remove only entries proven owned by a simple exact manifest.
- Give POSIX and PowerShell the same product rules while reporting platform evidence
  separately.

**Non-goals:**

- Automatic adoption or recursive cleanup of legacy runtimes.
- Re-enabling automatic source-checkout deletion.
- Protection from an actor that can coherently replace the launcher, verifier,
  receipt, and runtime under the same local account.

## Identity and Files

The implementation uses at most two internal identifiers:

- `release_id` names one verified, sealed plugin/runtime release.
- `transaction_id` may name one install, upgrade, or repair attempt.

No third activation or candidate identity is introduced. A small release manifest
records the verified commit/tree, exported entry inventory, release path, wheel
digest, and release payload digest. The runtime receipt and ownership manifest refer
to `release_id` directly; they do not form a recursive digest graph.

Release-specific plugin and runtime directories live under existing
installer-controlled authorities. Existing public commands, plugin ID, marketplace
mode, bundled MCP name, and task-data paths do not change.

## Decisions

### 1. Preserve authoritative source for every outcome — DFO-AUDIT-009

After clone or an allowed fast-forward selects the authoritative revision, the
installer records the selected HEAD/tree and complete Git inventory for tracked,
untracked, and ignored paths. Final checks run after successful install, repair, or
upgrade and after failure handling. They use Git output that includes ignored paths;
ordinary porcelain alone is insufficient.

Every Python command whose program or import path comes from the authoritative
checkout runs with both:

```text
-B
PYTHONDONTWRITEBYTECODE=1 scoped to that command
```

POSIX and PowerShell apply the same rule. Package validation, runtime build, health,
and launcher generation use the sealed staging tree wherever possible. Build output
is directed to transaction staging, not source.

The installer does not create `__pycache__`, `.pyc`, `build`, `dist`, or egg-info in
source and never deletes source caches to make the final check pass. Pre-existing
allowed ignored content remains in place. Regression fixtures include an ignored
sentinel whose bytes are compared before and after, plus authorities containing
spaces, Unicode, and an apostrophe.

### 2. Contain runtime uninstall before adding exact ownership — DFO-AUDIT-010

All runtime-root and release-root whole-tree deletion is removed from POSIX,
PowerShell, and shared helpers. Managed runtime cleanup never calls `rm -rf`,
`Remove-Item -Recurse`, `shutil.rmtree`, or an equivalent recursive primitive on
those roots.

Each new release receives one versioned exact ownership manifest. It contains only
information needed for deletion:

- `release_id` and declared root;
- relative path;
- entry type;
- file digest when the entry is a regular file;
- executable bit or mode;
- symlink target text when the entry is a symlink.

Paths are normalized relative paths beneath a declared root. The manifest does not
claim the root merely because it exists, does not enumerate pre-existing content as
owned, and does not grant source ownership.

Uninstall processes known entries individually. It uses `lstat` so a link is never
followed. A regular file or symlink may be renamed to a same-filesystem quarantine
name, revalidated there, and unlinked. If type, digest, mode, target, or release
ownership differs, it is restored when safe or retained and reported. Directories
are attempted deepest first with non-recursive `rmdir` only after their owned status
is established and they are empty at that moment.

Unknown entries, changed owned files, concurrent additions or replacements,
symlinks with external targets, FIFOs, sockets, devices, reparse points, and other
special entries are retained. Their required ancestors remain. The result is
partial and names each retained path. Controller task data, source, external link
targets, and unrelated marketplace members remain unchanged.

A legacy runtime with no conforming exact manifest is retained in full. Uninstall
returns partial, prints the retained path and manual inspection guidance, and does
not derive ownership by walking its current contents. Repair may activate a new
release beside it; legacy removal remains manual.

### 3. Export and seal the verified Git release — DFO-AUDIT-006

The existing origin, branch, commit, ancestry, and cleanliness checks remain the
selection gate. After they pass, the installer records the verified commit and tree
and exports that commit from Git object storage into temporary installer-owned
staging, for example with `git archive <verified-commit>`.

Archive extraction is bounded and safe. It rejects absolute paths, `..` traversal,
duplicate destinations, and unsupported entry types. It verifies the extracted
inventory against the Git tree, including regular files, executable mode, and
symlink target text without following the link. Package validation and wheel build
then run from this staging tree.

The staged plugin payload, wheel, managed runtime, launcher inputs, and release
manifest are finalized under one `release_id`. The final plugin payload is promoted
to an installer-owned release-specific directory. The Dev Flow marketplace member
and `codex plugin add` target that sealed directory instead of the authoritative
checkout. Runtime build, health, CLI/MCP smoke, launchers, ownership, and receipt all
refer to the same release.

After sealing, later source drift cannot enter the release. The transaction may
continue if all remaining inputs come from sealed paths. If a remaining step still
needs changed source content, it fails closed. A late HEAD check is evidence about
source state, not a replacement for the sealed release.

Receipt v2 records the verified commit, verified tree, release path, release
manifest digest, and wheel digest. Permanent tests inject source drift before and
after runtime build, marketplace write, plugin add, health, launcher generation,
and success receipt publication. Each case proves that plugin, runtime, launcher,
and receipt resolve to the same sealed release or that installation fails closed.

### 4. Make receipt v2 a startup and repair gate — DFO-AUDIT-008

The existing runtime receipt becomes a closed, versioned receipt v2 containing:

- schema version and `release_id`;
- source commit and tree;
- wheel SHA-256;
- Dev Flow distribution metadata digest;
- Dev Flow installed-file paths and digests;
- exact normalized dependency name/version inventory;
- each dependency's metadata and RECORD digest;
- Python executable identity;
- runtime and release paths;
- launcher digest;
- ownership manifest digest.

One standard-library verifier implements this schema for both platforms. A
conforming CLI or MCP launcher invokes it with bytecode disabled before importing
Dev Flow. The verifier checks bounded JSON, path containment, selected release,
Python identity, package bytes, product METADATA/RECORD, exact dependency inventory,
dependency METADATA/RECORD, and ownership-manifest identity.

Missing, malformed, incompatible, wrong-path, or mismatched evidence stops startup
before product import and prints repair guidance. Startup performs no repair.
Installer and repair also compare launcher bytes independently, because a replaced
launcher may not invoke the verifier at all.

Repair returns `reused=true` only after the complete v2 verification succeeds. Any
mismatch, including a legacy receipt, rebuilds from the sealed Git release into new
staging and promotes a new verified release. It does not patch or bless the suspect
runtime in place. Legacy or suspect paths are removed only when exact ownership
permits; otherwise they are retained and reported.

This mechanism detects the accidental loss and content drift reproduced by
DFO-AUDIT-008. It is not an independent trust root against a same-privilege actor
that can replace all local verification inputs coherently.

### 5. Use one bounded lifecycle transaction — DFO-AUDIT-007

Install, upgrade, and repair use a small versioned transaction record. Its fields
are limited to:

- optional `transaction_id`;
- operation;
- previous `release_id` and path, or `none`/legacy observation;
- candidate `release_id` and path;
- current concrete step;
- actual observed state for runtime selection, plugin, marketplace member, MCP
  launcher, and CLI launcher;
- terminal outcome: `committed`, `rolled_back`, or `partial`.

The record is a bounded snapshot. It is atomically replaced when observations change
so a failure result can describe the state actually left behind.

For an older source-based installation, the installer exports and verifies a sealed
previous release from the current verified commit before fast-forwarding source. If
it cannot create a runnable previous release, it fails before marketplace, launcher,
runtime-selection, or Codex mutation. The previous sealed release remains available
until the attempt commits or a verified rollback completes.

Before changing the real plugin, Dev Flow marketplace member, launchers, or selected
runtime, the candidate plugin/runtime/launcher assets are fully staged and verified.
The concrete forward sequence is:

1. promote candidate runtime and plugin release;
2. update only the Dev Flow marketplace member;
3. install the MCP and CLI launcher bytes;
4. remove the previous plugin when needed and add the candidate plugin;
5. after every Codex command, observe the currently visible plugin and MCP state;
6. run candidate health and final applicable CLI/MCP smoke;
7. publish the active selection receipt for the candidate as the final mutation.

The committed active-selection receipt is the success form of the bounded record and
names the selected `release_id`. After it is published, the installer performs only
output and read-only reporting checks.

Marketplace updates always re-read the valid current document, replace only the Dev
Flow member, preserve unrelated members, and atomically replace the file while
retaining the transaction's previous bytes. Rollback re-reads the document and
restores only that member when the candidate value is still present. If unrelated
or candidate state changed so restoration cannot be proven safe, it preserves the
current file and reports partial.

A Codex return code never proves that no side effect occurred. The installer
observes plugin and MCP state after successful and unsuccessful remove/add commands
and records that observation before continuing or compensating.

On a late failure, rollback uses the sealed previous release to restore plugin
activation, the previous marketplace member, launcher bytes, and previous runtime
selection. It then observes the plugin/MCP state and runs previous MCP health plus
applicable CLI smoke. Only an actually running, healthy previous release produces
`rolled_back` and a "previous restored" message.

If any component cannot be safely restored or verified, the command returns
non-zero and records `partial`, each component's current state, retained paths, and
`blind_retry_safe=false`. Candidate B is never described as restored A. Fresh-install
failure removes only transaction-owned entries that still pass exact ownership and
continues to retain source.

Deterministic test seams cover candidate staging, runtime build, runtime promotion,
marketplace write, MCP launcher write, CLI launcher write, plugin remove, plugin add,
health, final CLI/MCP smoke, and rollback failure. They are test controls only and do
not add a production transaction framework.

## Failure and Result Semantics

- Failure before external or selected-runtime mutation returns non-zero and leaves
  the previous release selected.
- A late failure with fully verified restoration returns non-zero with
  `rolled_back` and proves the previous release healthy.
- Incomplete or uncertain restoration returns non-zero with `partial`, observed
  component state, retained paths, and `blind_retry_safe=false`.
- Successful publication of the active selection receipt returns committed success;
  subsequent checks are read-only.
- Legacy runtime ownership yields retained paths and a partial uninstall outcome.

## Test and Platform Boundary

Lifecycle tests place HOME, CODEX_HOME, runtime, data, source, marketplace, PATH,
fake Codex, and Git remote beneath one `TemporaryDirectory` and assert every target
is contained there. Tests never access the real Codex profile, marketplace, runtime,
task data, or remote repository.

POSIX receives dynamic evidence. PowerShell implements the same source, sealing,
receipt, rollback, and ownership semantics, but this host executes only parser,
static, host-neutral, and safe simulation tests. Native Windows remains
`NOT RUN — native Windows host unavailable`.
