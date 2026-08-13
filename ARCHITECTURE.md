# Dev Flow Orchestrator Architecture

[Simplified Chinese](ARCHITECTURE_CN.md)

## Product identities

Release `0.6.7` bundles a formal Codex Skill named `dev-flow` alongside the MCP
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
one closed `release-index.json`, and version-matched `install.sh` and
`install.ps1` bootstraps. The archive contains the complete sealed plugin tree,
one pure-Python project wheel, hash-locked `runtime-requirements.txt`, its
`uv.lock`, versioned lifecycle helpers, and an embedded closed manifest. The
manifest inventories every descendant except itself; the external index hashes
the manifest's original UTF-8 bytes.

The two bootstraps embed the same standard-library Phase A verifier. It checks
the bootstrap-pinned index digest before parsing, then the closed index,
archive size and digest, every tar header and portable ASCII member path, fixed
resource caps, safe exclusive extraction, raw manifest digest, complete
inventory, and static package topology. Links, reparse ancestors, special or
sparse members, unsupported tar extensions, traversal, path collisions, and
missing or undeclared members fail before extraction can become authority.

No artifact helper, artifact import, artifact subprocess, runtime authority,
lifecycle state, dispatcher, marketplace, plugin, MCP, Codex state, active
record, or transaction authority may execute or change before Phase A
completes. Acquisition staging is installer-owned temporary state and never an
installed or rollback selector.

The bootstrap is the first version-specific trust input and fixes the canonical
repository, version, asset, and index digest. SHA-256 proves byte agreement
between the bootstrap, index, archive, and manifest; it is not an independent
signature or an absolute proof of publication authenticity. Source commit and
tree are release-builder publication assertions. The design does not claim to
resist coherent replacement of all same-user trust inputs and does not add
signing, Sigstore, transparency logs, mirrors, or offline fresh installation.

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

The plugin manifest points to root `.mcp.json`, which declares one `dev-flow`
server invoking `dev-flow-mcp --stdio`. The personal marketplace points only to
the exact plugin root inside the active managed release, never to downloads,
extraction, checkout, candidate staging, or a mutable shared plugin tree.

## Lifecycle state machine

Fresh install, repair, upgrade, predecessor migration, recovery, and uninstall
use one installation-wide lifecycle lock. The lock is acquired before reading
active or transaction authority and remains held until a terminal outcome is
durable. Active creation, replacement, restoration, and deletion use expected
generation plus active-record-digest compare-and-swap. The monotonic generation
prevents stale writers and `A -> B -> A` identity confusion.

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
checkout are outside installation ownership and uninstall removal.

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
