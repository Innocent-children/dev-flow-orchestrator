# Install Dev Flow Orchestrator

[Simplified Chinese](INSTALL_CN.md)

This guide describes the versioned release-artifact lifecycle for release
`0.6.6`. It installs the formal `dev-flow` Codex Skill as a bundled plugin and
the local STDIO MCP server without cloning or retaining this repository. The
persisted Controller model and task-data namespace remain `0.4.0`.

## 1. Supported installation and registration mode

Use the `install.sh` or `install.ps1` asset attached to the exact GitHub Release
you selected. Do not invoke an installer from a repository checkout or set
`DEV_FLOW_SOURCE_ROOT`; checkout-driven lifecycle invocation is rejected before
product mutation.

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

## 3. Exact-version installation

On macOS, download the bootstrap from the selected version-specific release
location, inspect it if required by local policy, and execute that downloaded
asset:

```sh
VERSION=0.6.6
INSTALLER="${TMPDIR:-/tmp}/dev-flow-install-${VERSION}.sh"
curl -fL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v${VERSION}/install.sh" \
  -o "$INSTALLER"
sh "$INSTALLER"
```

On native Windows:

```powershell
$Version = '0.6.6'
$Installer = Join-Path $env:TEMP "dev-flow-install-$Version.ps1"
Invoke-WebRequest -UseBasicParsing `
  -Uri "https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v$Version/install.ps1" `
  -OutFile $Installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Installer
```

A `latest` download route may help a user choose a release, but the bootstrap
itself is version matched. After execution it constructs only URLs under
`releases/download/v<version>/`; there is no production repository, mirror, or
origin override.

## 4. Release assets and Phase A verification

Each `MAJOR.MINOR.PATCH` release publishes this one identity-matched set:

- `dev-flow-orchestrator-<version>.tar.gz`;
- `release-index.json`;
- `install.sh`;
- `install.ps1`.

The platform-neutral archive contains one top-level directory with the complete
sealed `plugin/**` tree, exactly one
`dev_flow_orchestrator-<version>-py3-none-any.whl`,
`runtime-requirements.txt`, the `uv.lock` used to generate it, versioned
`lifecycle/**` helpers, and `release-manifest.json`. The plugin tree includes
`.codex-plugin/plugin.json`, `.mcp.json`, `skills/dev-flow/**`, plugin-side CLI
assets, and installed-validation assets. The manifest inventories every
descendant except itself; `release-index.json` pins the manifest's original
UTF-8 bytes.

Both bootstraps embed byte-identical standard-library Phase A verifier code.
Before any artifact helper, artifact import, artifact subprocess, dependency
installation, candidate construction, or product-state mutation, Phase A:

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

## 5. Trust boundary

The bootstrap bytes chosen by the user, the canonical GitHub repository and
its release publication permissions, HTTPS/TLS and GitHub delivery, supported
system Python, the platform downloader, `uv`, Codex, and local account and
filesystem permissions form the initial trust boundary.

The bootstrap fixes repository, version, archive name, index digest, and
bootstrap schema. SHA-256 establishes that acquired and extracted bytes match
the bytes pinned by the bootstrap, index, and manifest. It detects corruption,
partial replacement, and cross-release mixing. SHA-256 is not an independent
digital signature or an absolute proof of publication authenticity. It does
not prove that the GitHub account was never compromised or defend against an
attacker that can replace all of one user's bootstrap, active record,
dispatchers, verifier, and managed runtime coherently. Source commit and tree
values are publication assertions checked and recorded by the release builder;
the end-user installer does not reconstruct them from a checkout.

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
- `lifecycle/` contains stable installation support;
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

Fresh install, repair, upgrade, migration, recovery, and uninstall share one
installation-wide lifecycle lock. Each command acquires it before reading
active or transaction authority and holds it until a durable terminal outcome.
Each operation creates or resumes one bounded journal. Active creation,
replacement, restoration, and deletion use expected generation plus
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

## 8. Repair, upgrade, rollback, and recovery

Repair reruns the bootstrap matching the installed version. For release
`0.6.6`, use the exact same commands from Section 3 with `VERSION=0.6.6`.
A healthy release is reused only after complete startup, receipt, ownership,
and installed-content attestation. Any drift builds a new candidate from the
reacquired and reverified same-version artifact. If that version's remote
index, archive, or manifest digest differs from the active receipt, repair
fails with a same-version identity-change error.

Upgrade runs the target version's bootstrap. For example, set `VERSION` or
`$Version` in Section 3 to the desired `MAJOR.MINOR.PATCH`; do not run the old
version's lifecycle helper to acquire the target.

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
and creates or resumes a durable uninstall transaction.

Uninstall compare-and-removes only exact product-owned plugin state, the Dev
Flow personal-marketplace member, managed-release entries, active record,
stable dispatchers, and lifecycle support, in that order. The uninstall
dispatcher and lifecycle support are removed last, and no product mutation
occurs after lock removal. An interrupted run can resume or classify its
journal without the removed runtime.

Changed, unknown, concurrent, linked, reparse, special, or unprovable content
is retained and reported by exact path. Uninstall preserves Controller task
data, unrelated marketplace and plugin entries, unrelated launchers,
standalone MCP registrations, and every legacy checkout. It never broadens into
a recursive delete to force completion.

## 12. Troubleshooting and evidence limits

- `DEV_FLOW_SOURCE_ROOT is not supported`: unset it and run the exact-version
  release bootstrap, not a checkout script.
- a Phase A digest, inventory, path, tar, or resource-limit error: stop; do not
  execute extracted helpers or adopt staging. Re-download the exact release
  bootstrap and asset set from the canonical release page.
- startup attestation failure: rerun the bootstrap matching the active version;
  do not substitute a different same-version digest envelope.
- lifecycle lock or non-terminal transaction: let the command perform bounded
  recovery. If it reports `partial`, preserve the listed paths and observations
  and follow the exact recovery guidance before another lifecycle mutation.
- standalone registration conflict: inspect it as operator-owned state; the
  bundled lifecycle will not silently adopt or remove it.
- unsupported MCP transport: use the local `--stdio` registration.

Native Windows final-artifact validation must run on native Windows x64. Static
PowerShell analysis, simulated adapters, macOS, WSL, or Wine are not native
Windows evidence. Release-candidate plugin read-back, bundled Skill discovery,
STDIO MCP startup, and uninstall must use a real Codex host. Promotion evidence
requires permission to publish all four final assets and re-download them from
their exact official version-specific locators. When those environments or
permissions are unavailable, record the gate as unverified; never infer it from
unit tests, deterministic fakes, or another platform.
