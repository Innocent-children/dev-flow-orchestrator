# Install Dev Flow Orchestrator

[Simplified Chinese](INSTALL_CN.md)

This guide describes the release-artifact lifecycle for release `0.6.11`. It
installs the formal `dev-flow` Codex Skill as a bundled plugin and the local
STDIO MCP server without cloning or retaining this repository. The persisted
Controller model and task-data namespace remain `0.4.0`.

## 1. Supported installation and registration mode

Bundled personal-marketplace plugin/Skill/MCP installation is the only
supported registration mode. `.codex-plugin/plugin.json` registers the Skill
tree and `.mcp.json` registers one local `dev-flow` server invoking
`dev-flow-mcp --stdio`. The installer does not adopt or provision a standalone
MCP registration. Unrelated or independently managed registrations remain
operator-owned and are preserved.

Standalone provisioning is not supported.

## 2. Requirements

macOS installation requires:

- a supported macOS host;
- 64-bit CPython 3.10, 3.11, 3.12, 3.13, or 3.14;
- `uv`;
- Codex with plugin, Skill, and MCP server support;
- `curl` with HTTPS support;
- a writable absolute directory already on `PATH`.

Native Windows installation requires Windows 10 22H2 x64 or Windows 11 x64,
64-bit CPython 3.10–3.14, `uv`, Codex, PowerShell 5.1 or PowerShell 7,
`Invoke-WebRequest`, and a writable absolute directory already on `PATH`.
Windows Server and POSIX compatibility layers are outside the supported client
claim.

Git, a repository clone, and `.git` are not end-user prerequisites. Release
production uses an exact clean Git tag, but no checkout becomes installed
authority. User-selected installation roots may contain spaces, apostrophes,
and Unicode.

## 3. One-line first installation

The first-install entry accepts exactly one version argument:

- `MAJOR.MINOR.PATCH` installs that exact official Release; or
- `latest` dynamically selects the latest official (non-draft, non-prerelease)
  Release of the canonical GitHub repository at execution time.

On macOS:

```sh
(installer="$(mktemp "${TMPDIR:-/tmp}/dev-flow-install.XXXXXX")" && trap 'rm -f "$installer"' 0 HUP INT TERM && curl -fsSL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.sh" -o "$installer" && /bin/sh "$installer" latest)
```

To pin an exact version, pass it instead of `latest`:

```sh
(installer="$(mktemp "${TMPDIR:-/tmp}/dev-flow-install.XXXXXX")" && trap 'rm -f "$installer"' 0 HUP INT TERM && curl -fsSL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.sh" -o "$installer" && /bin/sh "$installer" 0.6.11)
```

On native Windows:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$p=Join-Path ([IO.Path]::GetTempPath()) ("dev-flow-install-"+[guid]::NewGuid().ToString("N")+".ps1"); $status=1; try { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.ps1" -OutFile $p; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p latest; $status=$LASTEXITCODE } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }; exit $status'
```

Replace `latest` with `0.6.11` (or another published `MAJOR.MINOR.PATCH`) to pin
an exact version.

The entry rejects any other version syntax, including prefixes, ranges,
whitespace, and prerelease suffixes, before downloading anything. For `latest`
it reads only the canonical GitHub repository's official release listing over
HTTPS and requires a `vMAJOR.MINOR.PATCH` tag whose Release carries both
versioned bootstrap assets; drafts and prereleases are never selected. It then
downloads that Release's version-matched bootstrap
(`install-<version>.sh` / `install-<version>.ps1`) from the exact
`https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v<version>/`
HTTPS locator and executes it, so both the exact and the dynamic path enter the
same versioned Phase A and Phase B verification. No product state is modified before the versioned bootstrap
completes its downloads and validation: an invalid version, a missing Release,
or a download failure exits non-zero with the local installation untouched.
Only the canonical repository, its release API, and the official GitHub HTTPS
release delivery hosts are used; mirrors and arbitrary download URLs are
refused.

The version-matched bootstrap pins the canonical repository, version, archive
name, and `release-index.json` digest and embeds the standard-library Phase A
verifier described below. Forwarded options stay inside the closed Phase B
destination set (`--runtime-root`, `--bin-dir`, `--marketplace-file`,
`--codex-home`, `--data-root`, `--lock-timeout`). Downloading
`install.sh`/`install.ps1` from a version-specific release locator and running
it with the exact matching version is also supported, but the one-line entry
above is the documented surface.

## 4. Release assets and Phase A verification

Each `MAJOR.MINOR.PATCH` release publishes this one identity-matched set:

- `dev-flow-orchestrator-<version>.tar.gz`;
- `release-index.json`;
- `install.sh` and `install.ps1` (the version-agnostic first-install entries);
- `install-<version>.sh` and `install-<version>.ps1` (the version-matched
  bootstraps).

The platform-neutral archive contains one top-level directory with the complete
sealed `plugin/**` tree, exactly one
`dev_flow_orchestrator-<version>-py3-none-any.whl`,
`runtime-requirements.txt`, the `uv.lock` used to generate it, versioned
`lifecycle/**` helpers, and `release-manifest.json`. The plugin tree includes
`.codex-plugin/plugin.json`, `.mcp.json`, `skills/dev-flow/**`, plugin-side CLI
assets, and installed-validation assets. The manifest inventories every
descendant except itself; `release-index.json` pins the manifest's original
UTF-8 bytes.

Both version-matched bootstraps embed byte-identical standard-library Phase A
verifier code. Before any artifact helper, artifact import, artifact
subprocess, dependency installation, candidate construction, or product-state
mutation, Phase A:

1. downloads the index under a fixed hard cap and verifies the digest embedded
   in the bootstrap before JSON parsing;
2. parses a strict closed schema and checks the canonical repository, exact
   version, archive name, schema, and bounds;
3. downloads the archive with streaming size accounting and verifies its exact
   size and SHA-256 before extraction;
4. inspects every tar header, member type, path, case-collision key, declared
   mode, and fixed resource bound before writing a member;
5. extracts exclusively into a new empty installer-owned staging directory,
   without following link or reparse ancestors;
6. verifies the raw embedded-manifest digest and its closed schema;
7. compares the complete extracted inventory with the manifest; and
8. checks the required plugin, wheel, lock, requirements, and lifecycle
   topology without importing or executing artifact code.

Artifact member names use `/` and a closed portable ASCII grammar. Absolute or
drive-qualified paths, `.`, `..`, backslashes, colons, controls, trailing dots
or spaces, ASCII case collisions, Windows device names, links, sparse files,
devices, FIFOs, unsupported tar extensions, undeclared members, missing
members, and fixed hard-cap violations are rejected.

Only a successful Phase A can enter Phase B. Temporary acquisition and
extraction paths never become marketplace, active, receipt, or rollback
authority. Handled outcomes remove transaction-owned staging exactly or report
the precise retained path.

Caller input crosses this boundary only through the closed destination-option
set `--runtime-root`, `--bin-dir`, `--marketplace-file`, `--codex-home`,
`--data-root`, and `--lock-timeout`. Both `--option value` and
`--option=value` preserve native paths containing spaces, apostrophes, and
Unicode. Abbreviations, duplicates, positional input, and release or artifact
identity options are rejected. Phase B derives the artifact root from its own
versioned lifecycle location and rechecks the complete live inventory before
candidate construction; candidate construction checks it again before copying,
installing the wheel, or executing another helper.

## 5. Trust boundary

The bootstrap bytes chosen by the user, the canonical GitHub repository and
its release publication permissions, HTTPS/TLS and GitHub delivery, the
canonical repository's release listing used by `latest`, supported system
Python, the platform downloader, `uv`, Codex, and local account and
filesystem permissions form the initial trust boundary.

The version-matched bootstrap fixes repository, version, archive name, index
digest, and bootstrap schema. SHA-256 establishes that acquired and extracted
bytes match the bytes pinned by the bootstrap, index, and manifest. It detects
corruption, partial replacement, and cross-release mixing. The dynamic
`latest` path additionally trusts the canonical repository's official release
listing to name the current Release; the Release it names is then held to the
same pinned Phase A and Phase B verification as an exact version. SHA-256 is
not an independent digital signature or an absolute proof of publication
authenticity. It does not prove that the GitHub account was never compromised
or defend against an attacker that can replace all of one user's bootstrap,
active record, dispatchers, verifier, and managed runtime coherently. Source
commit and tree values are publication assertions checked and recorded by the
release builder; the end-user installer does not reconstruct them from a
checkout.

This release does not add signing, Sigstore, transparency-log verification,
third-party mirrors, or offline fresh installation.

## 6. Phase B, managed releases, and durable authority

Phase B semantically validates the package, creates a transaction-owned
candidate, installs hash-required wheel-only dependencies and the supplied
pure-Python project wheel without running an sdist build backend, and performs
candidate-specific package, Skill, MCP, receipt, and runtime health checks.
Candidate health does not use the public active record.

Default managed-runtime roots are:

- macOS: `~/.local/share/dev-flow-orchestrator/runtime`
- Windows: `%LOCALAPPDATA%\dev-flow-orchestrator\runtime`

Within the selected absolute runtime root:

- `releases/<release-id>/` contains each managed release;
- `active.json` is the only local selector of the active release;
- `transactions/` contains bounded durable lifecycle journals;
- `lifecycle/` contains stable installation support, including the update and
  reinstall command driver and the shared release resolver;
- `reinstall-command-guard/lifecycle.lock` serializes parent reinstall drivers
  while their child bootstrap uses the installation lock;
- `lifecycle.lock` is the installation-wide lock.

The exact `release-id` includes the version and verified release identity; do
not construct or select it manually. A managed release contains the isolated
environment, sealed plugin, runtime receipt, full installed-content verifier,
and versioned lifecycle entry points. The receipt binds index, archive,
manifest, source assertions, wheel, requirements, lock, distributions, Python,
plugin, verifier, helper, owned-file, release-path, and transaction identity.

`active.json` is deliberately smaller. Its closed schema contains the
monotonic generation, release ID, contained absolute release path, receipt
digest, dispatcher protocol, and committing transaction ID. Launchers,
marketplace data, receipts, and helpers do not compete with it as active
selectors.

The closed installation record in `lifecycle/installation.json` is the
digest-pinned evidence every lifecycle command verifies before running. It
records the actual runtime root, dispatcher directory, Codex home, personal
marketplace file, Controller task-data root, the Dev Flow-owned data entry
names under that root, and the digests of all stable lifecycle support files.
Upgrade, uninstall, and reinstall derive their exact paths from this evidence,
so a custom data root chosen at install time is honored by every later
lifecycle command. The frozen immediate predecessor may migrate once to this
expanded evidence schema only when its record, stable support, and dispatchers
all match their pinned identities; drift or older layouts are preserved.

The product owns three small stable dispatchers in the selected writable PATH
directory:

- `dev-flow`
- `dev-flow-mcp`
- `dev-flow-uninstall`

On Windows these commands are installed as `dev-flow.cmd`,
`dev-flow-mcp.cmd`, and `dev-flow-uninstall.cmd`.

Ordinary repair, upgrade, and automatic rollback reuse their bytes. CLI and MCP
dispatchers minimally validate active-record, contained-path, receipt,
protocol, Python, and versioned-verifier evidence before invoking the active
verifier. The verifier checks the complete installed identity before importing
project code. The personal marketplace points only to the active managed
release's exact plugin root.

Controller task data remains in the Codex plugin data root under namespace
`0.4.0`, outside managed releases, lifecycle state, and ownership removal.

## 7. Activation, locking, and terminal outcomes

Fresh install, repair, upgrade, reinstall, migration, recovery, and uninstall
share one installation-wide lifecycle lock for authority reads and mutations.
Reinstall releases it while the child bootstrap acquires the same lock; its
pending journal blocks unrelated operations, an independent operation guard
excludes a second reinstall driver, and only the child carrying the exact
matching transaction authorization may proceed. Each operation creates or
resumes one bounded journal. Active
creation, replacement, restoration, and deletion use expected generation plus
active-record-digest compare-and-swap; generations increase monotonically.

Candidate activation follows this order:

1. complete candidate-specific staged health;
2. provision the marketplace and Codex plugin and read them back;
3. commit the target active record by generation CAS;
4. prove startup through the real public `dev-flow` and
   `dev-flow-mcp --stdio` paths;
5. record the terminal transaction outcome.

Every lifecycle result is one of:

- `committed`: the requested release or uninstall state is authoritative and
  its required read-back succeeded;
- `rolled_back`: the candidate is not authoritative and the immediate previous
  authority, or absence for a failed fresh install, was restored and proven;
- `partial`: exact requested or previous authority cannot be proven; further
  identity-specific mutation stops, uncertain content is retained, and the
  journal records observations, paths, and bounded recovery guidance.

No command reports success with an in-progress journal, disagreed plugin or
marketplace state, or an unclassified provisional effect.

## 8. Update, repair, and recovery

`dev-flow update` upgrades the current installation to the latest official
Release:

```sh
dev-flow update
```

The command is recognized by the stable dispatcher before the active release is
resolved, so it remains executable when the active release cannot start. It
resolves the latest official Release with the same shared version and
canonical-download rules as first installation, then runs that Release's
versioned bootstrap with the exact paths recorded in the installation evidence.
The existing lifecycle lock, transaction journal, artifact verification,
staged health, active CAS, public proof, and rollback machinery handle the
upgrade, including repair-rebuilding a damaged active release whose receipt
identity is still provable. Even when the active release is already latest,
Phase B reruns complete runtime, installed-content, public-startup, and stable-
infrastructure attestation. A healthy release is reused without rebuilding or
replacing it; there is no receipt-only success shortcut. Resolution failure, a missing Release, or a download
failure exits non-zero before any product state changes; an unrecoverable
installation is reported as `partial`, never as success.

Repair of a drifted same-version installation reuses the same machinery: run
the first-install entry with the installed version (Section 3). A healthy
release is reused only after complete startup, receipt, ownership, and
installed-content attestation. Any drift builds a new candidate from the
reacquired and reverified same-version artifact. If that version's remote
index, archive, or manifest digest differs from the active receipt, repair
fails with a same-version identity-change error.

Rollback is automatic and limited to the immediate previous authority during
the unsettled activation transaction. Failure before active commit restores
previous external state. Failure after commit CAS-restores the immediate
previous generation, restores external state, and revalidates the previous
public startup path. It requires no network, Git, or checkout. There is no
public command for arbitrary historical rollback and no unbounded retention
policy.

Before a new lifecycle mutation, the command recovers or classifies any
non-terminal transaction. It does not retry indefinitely. If authority remains
ambiguous, the transaction becomes `partial` and the new mutation is refused.

## 9. Bounded predecessor migration

Automatic migration recognizes only the immediately preceding conforming
checkout-based installer represented by the frozen predecessor fixtures. It
classifies identity solely from installed plugin observations, launcher
markers, receipt, ownership, marketplace, and transaction state. Older,
future, malformed, or ambiguous layouts stop before identity-specific
mutation.

Migration never reads, imports, executes, fetches, pulls, resets, cleans,
adopts, or deletes the predecessor checkout. The checkout is never rollback
input and remains user-owned after a successful migration. If the installed
observations do not prove exactly one predecessor authority, preserve them and
follow the reported recovery guidance. Supporting broader historical schemas
requires a separate OpenSpec change.

The legacy source checkout remains untouched and retained throughout migration.

## 10. Verify activation

Confirm the stable commands resolve from `PATH`:

```sh
command -v dev-flow
command -v dev-flow-mcp
command -v dev-flow-uninstall
dev-flow --help
dev-flow web start
dev-flow web status
dev-flow web stop
```

In Codex, read back the enabled personal-marketplace plugin and confirm its path
is the exact plugin root inside the active managed release. Confirm one Skill
named `dev-flow` and one MCP server named `dev-flow`. Start a new Codex task,
invoke `$dev-flow`, and ask Codex to call `dev_flow_server_info`.

The plugin manifest registers `./skills/` and the root `.mcp.json`. The sealed
plugin preserves the exact `skills/dev-flow/` tree, including metadata with
`implicit_invocation: true`. The installed-stage validator records the paired
Skill and STDIO MCP evidence before activation. The Skill routes commands to
the Controller. It does not authorize a mutation by itself.

`dev-flow-mcp --stdio` is a long-lived protocol process. Run it only through an
MCP client or inspector, not as an interactive shell command. Unsupported
transport flags must fail without opening a listening socket.

## 11. Source-independent uninstall

Run the stable dispatcher from any directory; do not invoke `uninstall.sh` or
`uninstall.ps1` from a checkout:

```sh
dev-flow-uninstall
```

The command needs neither network access nor a repository checkout. It verifies
stable installation evidence, copies and verifies a minimal standard-library
removal driver outside the managed runtime, acquires the same lifecycle lock,
and creates or resumes a durable uninstall transaction. It is dispatched before
active-release resolution, so it still runs when the active release cannot
start; unprovable content is then retained and reported instead of being
deleted.

Uninstall compare-and-removes only exact product-owned plugin state, the Dev
Flow personal-marketplace member, managed-release entries, active record,
stable dispatchers, and lifecycle support, in that order. The uninstall
dispatcher and lifecycle support are removed last, and no product mutation
occurs after lock removal. An interrupted run can resume or classify its
journal without the removed runtime.

Uninstall preserves all Dev Flow user data: Controller tasks and history,
state, evidence, lock files, Web UI runtime state and logs, and the data-root
ownership marker stay exactly where they were. Changed, unknown, concurrent,
linked, reparse, special, or unprovable content is retained and reported by
exact path. Uninstall also preserves unrelated marketplace and plugin entries,
unrelated launchers, standalone MCP registrations, and every legacy checkout.
It never broadens into a recursive delete to force completion.

## 12. Reinstall with full data reset

`dev-flow reinstall` clears all Dev Flow-owned user data and installs the
latest official Release:

```sh
dev-flow reinstall
```

Like `update`, it is dispatched before active-release resolution and always
targets the latest official Release with the same canonical resolution and
download rules. It uses the installation-wide lifecycle lock and one durable
`reinstall` transaction.

The cleanup is strictly limited to the recorded task-data root from the
digest-pinned installation evidence, and only to entries provably owned by Dev
Flow inside it: the Controller `0.4.0` namespace (tasks, history, state,
evidence, and lock files), the `web-runtime` directory (state and logs), and
the data-root ownership marker. The data root is first proven to contain only
those owned top-level entries, with no links, reparse points, special files,
unbounded inventory, or unknown content; anything else preserves the entire
data root and reports `partial`. The proven data is moved to a
transaction-owned backup with a digest-inventoried manifest, the target
Release is installed through its versioned bootstrap, and only a committed
install whose reported active identity still matches the lock-protected active
authority deletes the backup exactly. If the install fails or is interrupted,
the previous data bytes are verified and restored when exact rollback remains
provable; incomplete restoration, cleanup, or active-identity proof ends as
`partial` with exact retained paths and a non-zero exit. An interrupted
reinstall resumes from its journal instead of starting a second removal, and a
second concurrent reinstall driver cannot claim that journal.

User repositories, worktrees, Git data, source checkouts, unrelated plugin
data, and every other user file are never part of reinstall removal. Stop
Dev Flow processes (for example `dev-flow web stop`) before reinstalling so
the data move is not contended; a contended or unprovable move fails safely
and reports what was retained.

## 13. Troubleshooting and evidence limits

- `DEV_FLOW_SOURCE_ROOT is not supported`: unset it and run the official
  install entry, not a checkout script.
- a first-install version, resolution, or download error: stop. No product
  state was modified; pass a published `MAJOR.MINOR.PATCH` or `latest`.
- a Phase A digest, inventory, path, tar, or resource-limit error: stop; do not
  execute extracted helpers or adopt staging. Re-download the release
  bootstrap and asset set from the canonical release page.
- startup attestation failure: run `dev-flow update`, or rerun the first-install
  entry with the installed version; do not substitute a different same-version
  digest envelope.
- lifecycle lock or non-terminal transaction: let the command perform bounded
  recovery. If it reports `partial`, preserve the listed paths and observations
  and follow the exact recovery guidance before another lifecycle mutation.
- standalone registration conflict: inspect it as operator-owned state; the
  bundled lifecycle will not silently adopt or remove it.
- unsupported MCP transport: use the local `--stdio` registration.

Native Windows final-artifact validation must run on native Windows x64. Static
PowerShell analysis, simulated adapters, macOS, WSL, or Wine are not native
Windows evidence. Release-candidate plugin read-back, bundled Skill discovery,
STDIO MCP startup, uninstall, update, and reinstall must use a real Codex host.
Promotion evidence requires permission to publish all six final assets and
re-download them from their exact official version-specific locators. When
those environments or permissions are unavailable, record the gate as
unverified; never infer it from unit tests, deterministic fakes, or another
platform.
