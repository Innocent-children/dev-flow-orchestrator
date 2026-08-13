# Dev Flow Orchestrator Architecture

[Simplified Chinese](ARCHITECTURE_CN.md)

## Product identities

Release `0.6.9` bundles a formal Codex Skill named `dev-flow` alongside the MCP
interface without changing persisted model identity. `MODEL_VERSION`, the
task-data namespace, workflows, policies, bindings, records, findings,
snapshots, and Delivery Dossiers remain `0.4.0`.

The non-persisted transport identities are:

- `dev-flow-mcp/1.0.0`
- `dev-flow-mcp-result/1.0.0`
- `dev-flow-mcp-action/1.0.0`
- `dev-flow-mcp-guidance/1.0.0`

## Layers

```text
Codex Skill               CLI                 Read-only Web UI
     |                      |                         |
     v                      v                         v
MCP adapter ----------- Controller -----------------+
     |                      |
     |                      +--> Engine --> Delivery --> Model
     |                      +--> Store / locks / revision CAS
     |                      +--> GitClient / complete-set capture
     |
     +--> schemas, results, guidance, concurrency, stderr logging
```

The Skill provides activation and routing and calls the MCP; it does not write
task state. The Controller is the only state-transition writer. The MCP package
imports the Controller, but Controller, Engine, Store, GitClient, workflow,
assurance, delivery, review, snapshot, and model modules never import the MCP
SDK or its framework dependencies. Core and CLI runtime code remains
standard-library only; the managed MCP environment owns the third-party SDK.

## Codex Skill

`.codex-plugin/plugin.json` registers `skills: "./skills/"`. The canonical
Skill tree is closed to `SKILL.md`, `agents/openai.yaml`, and
`references/activation-and-routing.md` under `skills/dev-flow/`.

The `SKILL.md` description is the host's implicit-matching surface and also
names the explicit `$dev-flow` route. `agents/openai.yaml` carries interface
metadata and enables `policy.allow_implicit_invocation`. It intentionally omits
`dependencies`: the supported dependency schema is URL-based, while this
plugin's local STDIO server is already registered by `mcpServers: "./.mcp.json"`.
No URL or alternate transport is synthesized.

At runtime the Skill checks server identity, discovers tasks for each exact
repository root, resumes one unambiguous compatible task or starts a new one,
and then repeats the live `get_next_action`/execute/apply loop. Ambiguous task
selection returns to the user. Uncertain mutations use read-after-write recovery
before any retry.

This content is not a protocol authority. Package validation rejects a Skill
that embeds an action catalog, payload schema, state machine, transition table,
or versioned Controller protocol definition. The current MCP response remains
the source for the action id, closed payload, exact binding, review and
verification obligations, transitions, and terminal result.

## MCP server

One `MCPServer` named `dev-flow` runs over STDIO. Initialization advertises
Tools only: no Resources, Prompts, Tasks, sampling, elicitation, HTTP, SSE,
authentication, or listening transport. The catalog contains exactly five read
tools and six mutation tools.

Inputs are closed Pydantic/JSON schemas with field, enum, count, and byte
limits. Domain objects still pass through current Controller/model validators;
transport validation does not duplicate or weaken domain rules. Unknown tools,
unknown fields, malformed JSON values, and protocol failures are rejected
before Controller dispatch.

Every tool returns one concise text item plus a structured
`dev-flow-mcp-result/1.0.0` envelope. Domain errors preserve their code and
receive bounded redacted details and deterministic recovery. Unexpected adapter
exceptions return `INTERNAL_ERROR` plus a request ID; stderr records only the
exception class and stack-frame locations, never arguments, contracts,
bindings, environment values, repository contents, or the task-data root.

## Read models

Existing bounded Controller inspection APIs are reused:

- product identity and health;
- paginated stored task inventory with isolated diagnostics;
- stored task detail, contract summary, governance summary, timeline page, and
  terminal Dossier;
- canonical active-task discovery for a repository path;
- live authoritative next-action capture.

The MCP current-action view is a transient compact projection derived from
`dev-flow-agent/0.4.0`. It retains the complete repository set, snapshot
digests, exact binding, payload contract, drivers, obligation/review context,
inputs, governing resources, and source projection digest. It does not persist
a new model object or expose Git-internal snapshot paths. If complete context
does not fit its limit, the adapter returns `MCP_RESULT_LIMIT`; it never
truncates a binding or required action field.

## Guidance

Initialization instructions contain only the discovery, explicit selection,
get-next, execute, and apply loop and are bounded to 4 KiB. A versioned catalog
selects guidance by current node and handler for preflight, impact, planning,
implementation, investigation, documentation, rework, assurance/review,
finalization, cancellation, and a closed generic fallback.

Impact guidance separates current and baseline codebase-memory projects and
requires source confirmation. Planning guidance carries governing OpenSpec
status, path/digest, source stage, and fallback. Review guidance uses the bound
review package and preserves its snapshot/digest authority. The final guidance
is bounded to 8 KiB.

## Repository and state authority

A task owns an immutable canonical set of one to eight user-prepared Git
worktree roots. The Controller does not create, switch, repair, or remove Git
worktrees or branches. Complete live capture covers all members twice where
required by the snapshot protocol. Missing members, overlap, aliases, shared Git
administration, stale bindings, unstable snapshots, or revision conflicts fail
atomically before state transition.

Stored inventory inspection performs no live Git capture and isolates corrupt
entries. Path discovery excludes terminal tasks and returns explicit ambiguity
for overlapping active claims. Task storage remains in the model `0.4.0`
namespace outside every repository.

## Concurrency and uncertain completion

The MCP adapter adds a bounded in-process coordinator: same-task mutations are
serialized, and at most four live-capture or mutation calls are admitted without
queueing. Excess calls fail immediately. This is only an admission optimization.
Store locks, repository membership, exact bindings, and revision CAS remain
authoritative across processes.

Mutations are non-idempotent. A disconnect or cancellation after a commit may
make completion uncertain, so clients must read the stored task and current
action before deciding whether another mutation is necessary. No adapter retry
loop replays mutations automatically.

## Release acquisition and pre-execution boundary

End-user lifecycle operations acquire version-addressed GitHub Release assets,
not a source checkout. Each version publishes one platform-neutral archive,
one closed `release-index.json`, version-agnostic `install.sh` and
`install.ps1` first-install entries, and version-matched
`install-<version>.sh` and `install-<version>.ps1` bootstraps. The archive
contains the complete sealed plugin tree, one pure-Python project wheel,
hash-locked `runtime-requirements.txt`, its `uv.lock`, versioned lifecycle
helpers, and an embedded closed manifest. The manifest inventories every
descendant except itself; the external index hashes the manifest's original
UTF-8 bytes.

The two version-matched bootstraps embed the same standard-library Phase A
verifier. It checks the bootstrap-pinned index digest before parsing, then the
closed index, archive size and digest, every tar header and portable ASCII
member path, fixed resource caps, safe exclusive extraction, raw manifest
digest, complete inventory, and static package topology. Links, reparse
ancestors, special or sparse members, unsupported tar extensions, traversal,
path collisions, and missing or undeclared members fail before extraction can
become authority.

The first-install entries share one standard-library release resolver with the
installed `update` and `reinstall` commands: one strict `MAJOR.MINOR.PATCH` or
`latest` grammar, canonical-repository-only HTTPS hosts, an official-release
filter that rejects drafts and prereleases, and downloads only under the
canonical `releases/download/v<version>/` locators. `latest` resolves through
the canonical repository's official release listing, then the selected
Release's version-matched bootstrap runs the same pinned Phase A and Phase B
verification as an exact version. Invalid versions, missing Releases, and
download failures exit non-zero before any product state changes.

No artifact helper, artifact import, artifact subprocess, runtime authority,
lifecycle state, dispatcher, marketplace, plugin, MCP, Codex state, active
record, or transaction authority may execute or change before Phase A
completes. Acquisition staging is installer-owned temporary state and never an
installed or rollback selector.

The bootstrap is the first version-specific trust input and fixes the canonical
repository, version, asset, and index digest. The dynamic `latest` path
depends on the canonical repository's release listing, which is bounded to
official non-draft, non-prerelease Releases carrying both versioned bootstrap
assets. SHA-256 proves byte agreement between the bootstrap, index, archive,
and manifest; it is not an independent signature or an absolute proof of
publication authenticity. Source commit and tree are release-builder
publication assertions. The design does not claim to resist coherent
replacement of all same-user trust inputs and does not add signing, Sigstore,
transparency logs, mirrors, or offline fresh installation.

## Managed release and startup authority

Only Phase B may perform semantic wheel validation, hash-required wheel-only
dependency installation, project-wheel installation, candidate construction,
and staged Skill/MCP health. It never executes an sdist build backend on the
user's machine. Candidate-specific health does not read the public active
record.

```text
version-matched bootstrap
          |
          v
Phase A verified extraction (temporary, never authority)
          |
          v
Phase B candidate + staged health
          |
          v
provisional marketplace/plugin read-back
          |
          v
active.json generation CAS
          |
          v
public dev-flow and dev-flow-mcp --stdio proof
```

A managed release contains its isolated environment, sealed plugin, runtime
receipt, installed-content verifier, and versioned lifecycle entry points. The
receipt binds the complete artifact and installed identity: index, archive,
manifest, source assertions, wheel, requirements, lock, distributions, Python,
plugin, verifier, helpers, owned inventory, release path, and transaction.

The closed `active.json` record is the only local active-release selector. It
contains only a monotonic generation, release ID, contained absolute managed
release path, receipt digest, stable-dispatcher protocol, and committing
transaction ID. Receipt, marketplace, plugin state, launcher, and helper files
may corroborate the active record but never select a competing release.

Three small product-owned dispatchers, `dev-flow`, `dev-flow-mcp`, and
`dev-flow-uninstall`, are stable installation infrastructure. Ordinary repair,
upgrade, and automatic rollback do not replace them. CLI and MCP dispatchers
validate the active schema, contained path, receipt digest, protocol, managed
Python, and versioned verifier before invoking that verifier. The verifier
attests complete installed content before project import or MCP initialization.
`dev-flow update` and `dev-flow reinstall` are recognized by the same stable
dispatcher before active release resolution; they verify the copied,
digest-pinned command driver and run it outside the managed runtime, so both
remain executable when the active release cannot start.

The plugin manifest points to root `.mcp.json`, which declares one `dev-flow`
server invoking `dev-flow-mcp --stdio`. The personal marketplace points only to
the exact plugin root inside the active managed release, never to downloads,
extraction, checkout, candidate staging, or a mutable shared plugin tree.

The closed installation record in `lifecycle/installation.json` is
digest-pinned evidence verified before every lifecycle command runs. It
records the actual runtime root, dispatcher directory, Codex home, personal
marketplace file, Controller task-data root, the Dev Flow-owned data entry
names under that root, and digests for all stable support files. Upgrade,
uninstall, and reinstall derive their exact paths from this evidence, so a
custom data root chosen at install time is honored by every later lifecycle
command. The small data-root ownership marker proves the recorded root and its
owned names; reinstall verifies it (or the closed owned-name layout) before
any data mutation. An exact, frozen immediate-predecessor installation record
may be migrated once to this expanded evidence schema; changed support bytes or
any other historical layout are retained instead of overwritten.

## Lifecycle state machine

Fresh install, repair, upgrade, reinstall, predecessor migration, recovery, and
uninstall use one installation-wide lifecycle lock for every authority read and
mutation. Reinstall cannot retain that lock while its child bootstrap acquires
it, so its durable pending journal blocks unrelated operations and a separate
operation guard prevents concurrent reinstall drivers. Only the child carrying
the exact matching reinstall transaction authorization may proceed past that
journal. Active creation, replacement, restoration, and deletion
use expected generation plus active-record-digest compare-and-swap. The
monotonic generation prevents stale writers and `A -> B -> A` identity
confusion.

Each operation creates or resumes a bounded transaction journal containing the
operation and transaction ID, expected active state, target and previous
authority, external observations, provisional effects, transaction-owned and
retained paths, phase, and outcome. A new operation first recovers or classifies
an existing non-terminal journal.

Activation orders candidate staged health before provisional marketplace and
plugin effects, host read-back, active CAS, and real public CLI/MCP startup
proof. Failure before active commit restores previous external state. Failure
after commit CAS-restores the immediate previous generation and revalidates its
public startup. The only terminal outcomes are `committed`, `rolled_back`, and
`partial`; `partial` preserves uncertainty and stops identity-specific
mutation. Rollback is automatic and limited to the immediate previous authority
while that activation transaction is unsettled.

A healthy exact-version repair may reuse an active release only after complete
startup, receipt, ownership, and installed-content attestation. Drift builds a
new verified same-version candidate. A different index, archive, or manifest
digest for the same version is rejected rather than adopted. Upgrade always
runs the target version's bootstrap.

`dev-flow update` resolves the latest official Release with the shared resolver
and runs its versioned bootstrap with the recorded paths. When the active
release is already the latest version, Phase B still performs complete runtime,
installed-content, public-startup, and stable-infrastructure attestation. A
healthy release is reused without rebuilding or replacing it; a damaged release
whose receipt identity survives is repair-rebuilt, and an unprovable state is
reported as `partial`, never success. `dev-flow reinstall` runs one durable `reinstall`
transaction: it proves the data root contains only Dev Flow-owned entries
(Controller `0.4.0` namespace, `web-runtime`, and the ownership marker), moves
them to a digest-inventoried transaction backup, installs the latest Release
through its versioned bootstrap, and deletes the backup only after a committed
install. Failure or interruption restores the previous data bytes when exact
rollback can be proven; otherwise it retains both authorities and classifies
the transaction `partial`. Activation journals pending before data removal are
recovered first. During installation, only the transaction-matched child may
bypass that reinstall journal; every unrelated activation is refused.

## Migration and uninstall boundaries

Migration accepts only the frozen installed observations of the immediately
preceding conforming checkout installer. Classification uses plugin,
marketplace, launcher marker, receipt, ownership, and transaction evidence; it
never reads, imports, executes, updates, cleans, owns, deletes, or uses the
checkout for rollback. Older, future, malformed, or ambiguous observations
stop before identity-specific mutation.

`dev-flow-uninstall` verifies stable infrastructure and a copied minimal
standard-library removal driver, then creates or resumes an uninstall journal
under the same lifecycle lock. It compare-and-removes exact plugin and
marketplace state, managed releases, active record, CLI/MCP dispatchers, and
lifecycle support in dependency order. Changed, unknown, concurrent, linked,
reparse, special, or unprovable content is retained and reported. Lifecycle
support and the uninstall dispatcher are removed last, and no product mutation
occurs after lock removal.

Controller task data, the model namespace, unrelated marketplace and plugin
state, unrelated launchers, standalone MCP registrations, and every legacy
checkout are outside installation ownership and uninstall removal. Uninstall
also preserves all Dev Flow user data, including tasks, history, evidence,
locks, Web UI runtime state and logs, and the data-root ownership marker. Only
`dev-flow reinstall` clears Dev Flow-owned task data, and only inside the
recorded data root with ownership proven, exact rollback, and `partial`
classification for anything unprovable. User repositories, worktrees, Git
data, checkouts, and unrelated plugin data are never part of reinstall
removal.

## Security and residual boundary

The tool catalog has no generic command, raw-state, branch/worktree,
publication, external CI/PR/release, or parallel-executor capability. Tool
annotations are host hints and do not grant authority.

The legacy fail-open Hook, predecessor Skills, Hook bootstrap, and Hook-specific
Windows launcher are absent from the release package. The formal `dev-flow`
Skill is present, but supplies only activation and routing. Consequently there
is no PreToolUse data-directory guard. Safety relies on Controller validation,
Store integrity, host approvals, repository and operating-system permissions,
and user review. This residual boundary is explicit rather than represented as
Skill or MCP enforcement.

## Compatibility

Supported Python is `>=3.10,<3.15`, 64-bit for managed installation. macOS is
supported by the POSIX bootstrap. Native Windows 10 22H2 x64 and Windows 11 x64
use the PowerShell 5.1/7 bootstrap without POSIX dependencies; Windows Server
and compatibility layers are outside the client claim. User-selected roots may
contain spaces, apostrophes, and Unicode, while archive-internal names use the
closed portable ASCII grammar.

Existing 0.4.x tasks resume directly because the model namespace and bytes are
unchanged. Retained historical OpenSpec material remains evidence, not current
package authority. Static PowerShell checks and macOS execution are not native
Windows evidence. Real Codex release-candidate and final promotion/re-download
gates likewise remain unverified until they run in their required environments.
