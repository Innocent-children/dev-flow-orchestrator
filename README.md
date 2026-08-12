# Dev Flow Orchestrator

[Simplified Chinese](README_CN.md)

Dev Flow Orchestrator keeps long-running Codex development tasks resumable,
bounded, and verifiable across an exact set of one to eight user-prepared Git
worktrees. Release `0.6.0` bundles a formal Codex Skill named `dev-flow`
alongside the local MCP server while preserving the persisted `0.4.0` model and
task-data namespace.

The Skill activates and routes Codex into the MCP workflow; it is not another
workflow protocol. The Controller remains the only state-transition authority.
MCP, CLI, and the read-only Web UI are adapters over the same Controller; they
do not create or switch branches/worktrees, publish Git changes, run parallel
executors, or dispatch external CI, pull requests, or releases.

## Quick start

Requirements:

- macOS with Git, `uv`, Codex plugin, Skill, and MCP support, and 64-bit
  CPython 3.10–3.14;
- Windows 10 22H2 x64 or Windows 11 x64 uses the PowerShell preview path and
  requires native Windows verification for release evidence;
- one to eight existing, user-prepared Git worktree roots.

Install bundled mode on macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

Or clone the authoritative branch and run the installer:

```sh
git clone --branch main --single-branch \
  https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
sh "$HOME/plugins/dev-flow-orchestrator/scripts/install.sh"
```

The installer validates the candidate, preserves the Skill in the sealed plugin
snapshot, builds an exact locked MCP runtime outside source and task data,
installs the supported bundled commands on `PATH`, and activates the plugin.
See [INSTALL.md](INSTALL.md) for Windows, repair, rollback, uninstall, and the
bundled-only registration boundary.

Start a new Codex task after installation. Invoke the Skill explicitly:

```text
$dev-flow Implement this requirement in the current repository and verify it.
```

Codex can also activate it implicitly from its description for substantive
multi-step implementation, bug-fix, refactoring, investigation, review, and
verification work. No extra `AGENTS.md` rule is required in target projects.

The Skill drives this Controller-owned sequence:

1. discover with `dev_flow_find_tasks_for_path` or `dev_flow_list_tasks`;
2. explicitly select or start a task;
3. call `dev_flow_get_next_action`;
4. execute only the projected action over the exact repository set;
5. submit the exact action ID, closed payload, and unchanged binding;
6. repeat until the task has a terminal Delivery Dossier.

If discovery returns several plausible active tasks, the Skill asks the user to
choose instead of selecting by recency. If a mutation response is uncertain, it
reads the task and refreshes the current action before deciding whether any
retry is safe.

## Codex Skill

The plugin manifest registers `./skills/`. The bundled Skill is located at
`skills/dev-flow/` and contains:

- `SKILL.md`, whose description supports `$dev-flow` and implicit matching;
- `agents/openai.yaml`, with Codex interface metadata and
  `policy.allow_implicit_invocation: true`;
- `references/activation-and-routing.md`, which covers applicability, exact
  repository-set discovery, ambiguous tasks, and uncertain mutation responses.

The agent metadata deliberately has no MCP dependency block. The supported MCP
dependency form is URL-based, while this plugin supplies a local STDIO server;
`.codex-plugin/plugin.json` and `.mcp.json` are therefore the single
registration path for that server.

The Skill never defines Controller actions, payload schemas, state transitions,
review obligations, or terminal rules. It obtains each of those from the live
MCP result and submits the exact current binding.

## MCP interface

The bundled `.mcp.json` exposes exactly one local STDIO server named
`dev-flow`. It invokes `dev-flow-mcp --stdio`. HTTP, SSE, listening sockets,
tokens, and OAuth transports are rejected.

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

Every tool has a closed input schema, a structured success/error envelope, one
short text summary, bounded results, request IDs, closed-world annotations, and
MCP task augmentation disabled. Annotations describe intent; they are not an
authorization or operating-system enforcement boundary.

## Workflows and state

The official workflow catalog is `lite`, `feature`, `bugfix`, `investigation`,
`refactor`, and `full`. All use the unchanged `dev-flow-workflow/0.4.0`,
`dev-flow-agent/0.4.0`, action-binding, record, assurance, review, and Delivery
Dossier identities.

Task membership is an immutable canonical repository array. A live next-action
capture covers the complete set and returns the exact binding required by the
next mutation. Discovery from a secondary member returns the same task;
ambiguous active claims fail closed.

Task data stays outside every target repository under the model `0.4.0`
namespace. The MCP adapter never exposes the Controller data-root path in
normal results or installation receipts. Existing 0.4.x tasks resume without a
state migration.

## Guidance and recovery

The server initialization text contains only the discovery/get-next/execute/
apply loop. Current-action guidance is selected from a versioned bounded
catalog and includes only the applicable objective, must-read fields, allowed
effects, required evidence, payload notes, driver rules, stale recovery,
completion rule, and canonical guidance digest.

Never blindly retry a mutation after cancellation or a lost response. Read the
stored task and current action first, compare the committed revision and
binding, and then decide whether a new mutation is needed.

## CLI and read-only Web UI

The existing CLI and local Web UI remain supported views over the same
Controller:

```sh
dev-flow --help
dev-flow web start
dev-flow web status
dev-flow web stop
```

The Web UI binds to `127.0.0.1`, reads stored task views by default, and has no
mutation authority. MCP is the primary Codex execution interface.

## Security boundary

- The Controller, Store locks, repository membership, snapshots, bindings, and
  revision compare-and-swap remain authoritative.
- MCP has no generic shell, raw-state, branch/worktree, publication, CI, PR,
  release, or parallel-agent tool.
- The formal `dev-flow` Skill is activation and routing guidance only; it is not
  a second state writer or a substitute for Controller validation.
- Removal of the legacy fail-open Hook means there is no pre-tool write guard.
  Host approvals, repository permissions, and user review remain necessary.
- The plugin never grants blanket mutation approval. Scope approvals to the
  `dev-flow` server and the exact requested tool when the host supports it.

## Development

Use the project environment and package checks:

```sh
uv sync --locked
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python scripts/validate_package.py
openspec validate add-dev-flow-skill --strict
```

Focused tests are convenient during iteration; full unittest discovery is
allowed and is the normal complete regression command for this repository.
See [CONTRIBUTING.md](CONTRIBUTING.md), [ARCHITECTURE.md](ARCHITECTURE.md), and
[ROADMAP.md](ROADMAP.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
