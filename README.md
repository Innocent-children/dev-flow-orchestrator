# Dev Flow Orchestrator

[Simplified Chinese](README_CN.md)

Dev Flow Orchestrator keeps long-running Codex development tasks resumable,
bounded, and verifiable across an exact set of one to eight user-prepared Git
worktrees. Release `0.6.11` bundles a formal Codex Skill named `dev-flow` and a
local STDIO MCP server while preserving the persisted `0.4.0` model and
task-data namespace.

The Skill activates and routes Codex into the MCP workflow; it is not another
workflow protocol. The Controller remains the only state-transition authority.
MCP, CLI, and the read-only Web UI are adapters over the same Controller. They
do not create or switch branches/worktrees, publish Git changes, run parallel
executors, or dispatch external CI, pull requests, or releases.

## Quick start

End-user installation requires supported 64-bit CPython 3.10–3.14, `uv`, Codex
plugin/Skill/MCP support, the platform HTTPS download facility, and a writable
absolute directory already on `PATH`. Supported Windows clients are native
Windows 10 22H2 x64 and Windows 11 x64. Git is not an installation
prerequisite. Target repositories still need one to eight existing,
user-prepared Git worktree roots because they are the work controlled by the
product.

Download and run the first-install entry with `latest`, or with an exact
`MAJOR.MINOR.PATCH` such as `0.6.11`:

```sh
(installer="$(mktemp "${TMPDIR:-/tmp}/dev-flow-install.XXXXXX")" && trap 'rm -f "$installer"' 0 HUP INT TERM && curl -fsSL "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.sh" -o "$installer" && /bin/sh "$installer" latest)
```

On native Windows, download the same entry's `install.ps1` asset and run it
from PowerShell 5.1 or PowerShell 7:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$p=Join-Path ([IO.Path]::GetTempPath()) ("dev-flow-install-"+[guid]::NewGuid().ToString("N")+".ps1"); $status=1; try { Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/Innocent-children/dev-flow-orchestrator/releases/latest/download/install.ps1" -OutFile $p; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p latest; $status=$LASTEXITCODE } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }; exit $status'
```

The first-install entry validates `MAJOR.MINOR.PATCH` or `latest` before
downloading anything and fails non-zero with the local installation untouched
when the version is invalid, the Release does not exist, or a download fails.
`latest` reads only the canonical GitHub repository's official release listing
over HTTPS and never selects a draft or prerelease. Both paths download and
execute the selected Release's version-matched bootstrap, which pins the
canonical repository, version, archive name, and `release-index.json` digest.
That bootstrap is fetched from the exact canonical locator
`https://github.com/Innocent-children/dev-flow-orchestrator/releases/download/v<version>/install-<version>.sh`
(or the matching `.ps1` asset on Windows).
Before it executes artifact code or changes product state, its embedded
standard-library Phase A verifier checks the index, archive, tar members, raw
embedded manifest, complete inventory, resource limits, and required package
topology. Phase B then builds an isolated managed release from the supplied
pure-Python wheel and hash-locked, wheel-only dependencies, runs staged health,
and activates it transactionally. It preserves the Skill in the sealed plugin
snapshot. No source checkout is created or retained.

Installed lifecycle commands remain available from `PATH`:

```sh
dev-flow update      # upgrade to the latest official Release (idempotent)
dev-flow uninstall   # remove product-owned installation; keep all user data
dev-flow reinstall   # clear Dev Flow-owned task data, then install latest
```

`update` and `reinstall` are handled by the stable dispatcher before the active
release is resolved, so they still run when the active release cannot start;
they always select the latest official Release. `reinstall` removes only the
recorded Dev Flow-owned task-data entries (Controller tasks, history, state,
evidence, locks, Web UI runtime state and logs) after proving ownership, keeps a
digest-verified backup until the new install commits, and restores the previous
data exactly on failure or interruption when rollback remains provable;
otherwise it retains the evidence and reports `partial`.

See [INSTALL.md](INSTALL.md) for the trust boundary, one-line install commands,
repair, upgrade, automatic failed-activation rollback, migration, terminal
outcomes, durable paths, data boundaries, and source-independent uninstall.

After installation, start a new Codex task and invoke the Skill explicitly:

```text
$dev-flow Implement this requirement in the current repository and verify it.
```

Codex can also activate it implicitly for substantive multi-step
implementation, bug-fix, refactoring, investigation, review, and verification
work. No extra `AGENTS.md` rule is required in target projects.

The Skill drives this Controller-owned sequence:

1. discover with `dev_flow_find_tasks_for_path` or `dev_flow_list_tasks`;
2. explicitly select or start a task with `dev_flow_start_task` when needed;
3. call `dev_flow_get_next_action`;
4. execute only the projected action over the exact repository set;
5. submit the exact action ID, closed payload, and unchanged binding;
6. repeat until the task has a terminal Delivery Dossier.

If discovery returns several plausible active tasks, the Skill asks the user to
choose instead of selecting by recency. If a mutation response is uncertain,
it reads the task and refreshes the current action before deciding whether any
retry is safe.

## Installed release model

Each release archive is platform-neutral and contains the complete sealed
plugin tree, `.codex-plugin/plugin.json`, `.mcp.json`, `skills/dev-flow/**`, one
pure-Python project wheel, `runtime-requirements.txt`, the generating
`uv.lock`, versioned `lifecycle/**` helpers, and `release-manifest.json`. The
manifest inventories every descendant except itself; the external index pins
the manifest's raw UTF-8 bytes.

The active record is the only local selector of an active release. It carries a
monotonic generation, release ID, contained absolute managed-release path,
receipt digest, dispatcher protocol, and committing transaction ID. The
runtime receipt attests the complete installed release. Small product-owned
`dev-flow`, `dev-flow-mcp`, and `dev-flow-uninstall` dispatchers remain stable
across ordinary repair, upgrade, and automatic rollback; versioned verification
and lifecycle code live inside each managed release. `dev-flow update` and
`dev-flow reinstall` are recognized by the stable dispatcher before active
release resolution; they share the first-install version grammar and canonical
HTTPS release download rules. The digest-pinned installation record captures
the runtime root, dispatcher directory, Codex home, marketplace file, task-data
root, and Dev Flow-owned data paths, and every later lifecycle command derives
its exact paths from that evidence.

Every lifecycle operation holds one installation-wide lock and ends as exactly
one of:

- `committed`: the requested authority was read back and proven;
- `rolled_back`: the candidate is inactive and the immediate previous
  authority, or absence for a failed fresh install, was restored and proven;
- `partial`: neither requested nor previous authority can be proven exactly,
  so uncertain content is retained and identity-specific mutation stops.

There is no public arbitrary-history rollback command. Rollback in this release
is the automatic restoration of the immediate previous authority while the
current activation transaction is unsettled.

## Codex Skill and MCP interface

The plugin manifest registers `./skills/`. The bundled Skill is located at
`skills/dev-flow/` and contains `SKILL.md`, `agents/openai.yaml`, and
`references/activation-and-routing.md`. It supports explicit `$dev-flow`
invocation and implicit matching. It never defines Controller actions, payload
schemas, state transitions, review obligations, or terminal rules; those come
from the live MCP result.

The bundled `.mcp.json` exposes exactly one local STDIO server named
`dev-flow`, invoking `dev-flow-mcp --stdio`. HTTP, SSE, listening sockets,
tokens, and OAuth transports are not supported.

Read tools:

- `dev_flow_server_info`
- `dev_flow_list_tasks`
- `dev_flow_find_tasks_for_path`
- `dev_flow_get_task`
- `dev_flow_get_next_action`

Mutation tools:

- `dev_flow_start_task`
- `dev_flow_apply_action`
- `dev_flow_revise_contract`
- `dev_flow_record_decision`
- `dev_flow_dispose_finding`
- `dev_flow_cancel_task`

Every tool has a closed input schema, structured success/error envelope,
bounded results, request IDs, closed-world annotations, and MCP task
augmentation disabled. Annotations describe intent; they are not an
authorization or operating-system enforcement boundary.

## Workflows and task data

The official workflow catalog is `lite`, `feature`, `bugfix`, `investigation`,
`refactor`, and `full`. All retain the `dev-flow-workflow/0.4.0`,
`dev-flow-agent/0.4.0`, action-binding, record, assurance, review, and Delivery
Dossier identities.

Task membership is an immutable canonical repository array. Task data stays
outside every target repository under the model `0.4.0` namespace and outside
managed releases and lifecycle state. A live next-action capture covers the
complete set and returns the exact binding required by the next mutation.
Discovery from a secondary member returns the same task; ambiguous active
claims fail closed. Existing 0.4.x tasks resume without a state migration.
Repair, upgrade, migration, and uninstall do not delete or modify Controller
task data. Only `dev-flow reinstall` clears Dev Flow-owned task data, and only
after proving ownership through the recorded data root and marker, with exact
rollback on failure.

## CLI and read-only Web UI

The CLI and local Web UI remain views over the same Controller:

```sh
dev-flow --help
dev-flow web start
dev-flow web status
dev-flow web stop
```

The Web UI binds to `127.0.0.1`, reads stored task views by default, and has no
mutation authority. MCP is the primary Codex execution interface.

## Trust and evidence boundary

The canonical GitHub repository and its release publication permissions are
part of release provenance. The version-matched bootstrap fixes the repository,
version, assets, and index digest; the `latest` path additionally trusts the
canonical repository's official release listing to name the current Release,
which is then held to the same pinned Phase A and Phase B verification.
SHA-256 proves that downloaded bytes agree with the bytes pinned by the
bootstrap, index, and manifest; it detects corruption and cross-release mixing.
SHA-256 is not an independent digital signature and does not prove that the
GitHub account was never compromised. Source commit and tree values are
publication assertions verified and recorded by the release builder, not
source provenance reconstructed on the user's machine.

This design does not claim to resist an attacker who can coherently replace all
same-user local trust inputs. It does not add signing, Sigstore, transparency
logs, third-party mirrors, offline fresh installation, update channels, or
background updates.

Native Windows final-artifact evidence, release-candidate evidence against a
real Codex host, and final promotion/re-download evidence require their actual
environments. macOS tests, deterministic fakes, and static PowerShell checks do
not establish those results. Until such evidence is recorded, those gates must
be reported as unverified rather than inferred.

## Development

Use the project environment and repository checks:

```sh
uv sync --locked
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python scripts/validate_package.py
openspec validate install-versioned-release-artifact --strict
```

See [CONTRIBUTING.md](CONTRIBUTING.md),
[ARCHITECTURE.md](ARCHITECTURE.md), and [ROADMAP.md](ROADMAP.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
