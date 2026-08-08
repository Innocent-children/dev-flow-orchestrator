# Contributing to Dev Flow Orchestrator

[Simplified Chinese](CONTRIBUTING_CN.md)

## Scope and authority

Keep changes minimal and attributable to the accepted requirement. The
Controller is the only state-transition writer. MCP, CLI, and Web adapters may
submit commands or inspect state but must not duplicate Engine, Store,
repository, binding, assurance, review, or delivery authority.

Do not add automatic branch/worktree management, Git publication, parallel
executors, external CI/PR/release dispatch, raw-state tools, or a generic command
surface. Do not weaken canonical paths, repository identity, exact membership,
locks, atomic writes, revision CAS, snapshot stability, bindings, acceptance
criteria, or final Dossier requirements.

## Environment

Runtime and development dependencies are managed by the project-level `uv`
environment. Never install them into system or user Python.

```sh
uv sync --locked
uv run python --version
```

Supported runtime metadata is `>=3.10,<3.15`. Managed installed runtimes require
64-bit Python. Core runtime modules must remain standard-library only; only
`src/dev_flow_orchestrator/mcp/` may import the MCP SDK, Pydantic, or their
framework dependencies.

## Tests

During iteration, run the smallest useful focused test:

```sh
uv run python tests/test_mcp_runtime.py -v
uv run python tests/test_package.py -v
```

Full unittest discovery is allowed. It is the canonical complete source
regression command:

```sh
uv run python -m unittest discover -s tests -p 'test_*.py'
```

The former repository rule prohibiting full unittest discovery is abolished.
Do not replace complete discovery with a hand-maintained partial module list in
release evidence. Focused suites remain useful for fast feedback.
The checked-in CI matrix runs that complete discovery on macOS and native Windows
for every supported Python minor from 3.10 through 3.14; a green subset is not a
substitute for the complete release matrix.

Run package and OpenSpec validation when relevant:

```sh
uv run python scripts/validate_package.py
openspec validate dev-flow-orchestrator-mcp --strict
```

The same installed STDIO launcher is compatible with the
[official MCP Inspector](https://github.com/modelcontextprotocol/inspector).
Use `--` so `--stdio` is passed to Dev Flow rather than parsed as an Inspector
option:

```sh
npx @modelcontextprotocol/inspector -- dev-flow-mcp --stdio
npx @modelcontextprotocol/inspector --cli --method tools/list -- dev-flow-mcp --stdio
```

The automated protocol gate remains `tests/test_mcp_runtime.py`, which uses the
official Python client directly and does not require Node.js.

Never claim a platform or matrix passed unless it actually ran. Native Windows
evidence must come from native Windows x64, not macOS, Wine, WSL, or a skipped
test. Record skips, unavailable hosts, and stale evidence explicitly.

## MCP changes

The stable catalog has exactly eleven tools. A tool change must include:

- a stable snake-case name and description at most 512 UTF-8 bytes;
- a closed input model with explicit required fields, enums, count/byte limits,
  and unknown-field rejection;
- a per-tool output schema inside the common result envelope;
- correct read-only, destructive, idempotent, closed-world, and task-support
  annotations;
- direct Controller mapping without domain-rule duplication;
- domain, protocol, unexpected-error, result-bound, concurrency, cancellation,
  and real official client/STDIO tests as applicable;
- package-validation and installed-journey coverage.

Do not print to stdout anywhere in the server import/start/run/shutdown path;
stdout is protocol-only. Diagnostics use bounded stderr records with request
IDs and no arguments, environment values, contracts, bindings, repository
contents, secrets, or task-data paths.

Preserve these context budgets:

- server instructions: 4 KiB;
- first primary sequence: 512 bytes;
- tool description: 512 bytes;
- tools list: 32 KiB;
- text summary: 4 KiB;
- current-action guidance: 8 KiB;
- compact current action: 128 KiB.
- structured result: 512 KiB;
- inventory or discovery page: 256 KiB, with 2 KiB per item;
- default stderr event: 4 KiB.

Reject first-excess input or output instead of truncating bindings, repository
membership, required evidence, or guidance authority.

## Guidance changes

Every official action node/handler must map to one safe catalog entry or the
closed generic fallback. Guidance is derived from the authoritative current
projection and includes only the applicable objective, must-read fields,
allowed effects, required evidence, payload notes, driver, stale recovery,
completion rule, and canonical guidance digest.

Do not tell a model to inspect package source, adapter source, CLI source,
removed Skills/Hooks, raw Store files, or the Controller data root. Impact
guidance must separate baseline/current codebase-memory projects and confirm
graph findings against source. Governing OpenSpec guidance must carry concrete
status, path/digest, source stage, and fallback. Review guidance must preserve
the bound review package and guidance digest.

## Installation and platform changes

Candidate validation runs before candidate runtime code. The managed runtime
must remain outside verified source and task data, use the exact lock, install a
wheel, pass MCP smoke checks, and write a matching receipt before activation.
Failed builds must preserve the previous runtime and launcher.

POSIX scripts target macOS. PowerShell scripts retain PowerShell 5.1
compatibility, literal-path handling, x64 checks, fast-forward-only source
authority, marker-validated removal, and no POSIX dependency. Pair lifecycle
behavior across platforms without copying platform-specific mechanisms.

Installed journeys must use the real PATH launcher and official MCP client over
STDIO; the server process must not import test helpers. Cover one-member and
multi-member flows, restart/resume, 0.4.x data compatibility, governance,
review/rework, assurance exhaustion, terminal Dossiers, duplicate registration,
failed build/activation rollback, and uninstall preservation.

## Public documentation

`README.md`, `ROADMAP.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, and `INSTALL.md`
are English sources. Update the English file first, then completely translate
and synchronize the corresponding `_CN.md` file. Product scope, constraints,
commands, paths, versions, links, and language switches must match.

Do not describe MCP annotations as enforcement, removed Hook behavior as
present, unverified platforms as verified, or OpenSpec/task checkboxes as proof
of product correctness.

## Git and review

Preserve unrelated user changes. Do not stash, reset, clean, switch, rebase,
merge, commit, push, publish, or modify external state unless the user explicitly
authorizes that exact action.

For code review requests, complete a read-only review and report all findings
before making any fix. Stop after the review until the user explicitly selects
and authorizes repairs.
