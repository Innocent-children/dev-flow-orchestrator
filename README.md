# Dev Flow Orchestrator

[中文说明](README.zh-CN.md) · [Installation](INSTALL.md) ·
[Contributing](CONTRIBUTING.md)

Dev Flow Orchestrator is a macOS Codex plugin for guarded, resumable software
delivery. It keeps workflow state outside project repositories, turns every
state or Git change into an explicit controller action, and preserves enough
evidence to resume safely after interruption.

The product has one plugin identity, `dev-flow-orchestrator`, and one current
runtime:

- every task uses task schema v4;
- `lite@4` handles bounded single-repository work;
- `full@4` handles full single-repository and multi-repository work.

## Requirements

- macOS;
- Git;
- Python 3.9 or newer;
- a Codex build with plugin support.

Runtime Python code uses only the standard library. Native Windows and Linux
support is not claimed by this release.

## What it controls

The controller owns workflow transitions and durable task state. It coordinates:

- intake, impact analysis, route selection, planning, implementation, focused
  verification, and independent review;
- single- and multi-repository repository sets;
- baseline capture, isolated worktree planning, and repository ownership;
- explicit approval before gated actions;
- bounded worker assignments and changed-path enforcement;
- action journals, receipts, reconciliation, quarantine, and recovery;
- `codebase-memory` discovery evidence with separate baseline and current
  workspace project identities;
- compact CLI and MCP projections for the current actionable frontier.

Git-changing behavior is deterministic and gated. The plugin never grants
implicit authority to stash, reset, clean, commit, push, force-push, rebase, or
merge.

## Workflow profiles

The controller resolves exactly one installed bundle and pins its SHA-256
identity in the first task revision.

| Workflow | Repository profile | Intended use |
|---|---|---|
| `lite@4` | Single repository | Bounded internal, test, or documentation work with explicit target paths |
| `full@4` | Single repository | Full delivery flow, normally with an isolated worktree |
| `full@4` | Multiple repositories | Coordinated planning, leases, results, barriers, and integration |

`in-place` and `branch` workspace strategies infer the lite flow.
`worktree` infers the full flow. Multi-repository tasks use the full flow.

## Install

The complete installation, replacement, MCP setup, and acceptance procedure is
in [INSTALL.md](INSTALL.md). The short path is:

1. place this reviewed source at the path referenced by one local Codex
   marketplace;
2. register that marketplace;
3. install `dev-flow-orchestrator@<marketplace>`;
4. start a new Codex session;
5. confirm one enabled plugin instance, Hook pickup, MCP discovery, and one
   real-project workflow action.

Do not create a second plugin name for the V4 release.

## Use from Codex

The public entry point is the bundled `follow-dev-flow` Skill. Typical requests
are:

```text
Use $follow-dev-flow to start this requirement in the current repository:
<requirement>
```

```text
Use $follow-dev-flow to resume task <task-id>.
```

```text
Use $review-dev-flow-change to independently review the completed task.
```

The Skill asks the controller for the current node, loads only the bound
playbook section, previews actions that need confirmation, and applies the
confirmed intent at the same task revision.

Two supporting Skills are included:

- `analyze-change-impact`: read-only impact and dependency analysis;
- `review-dev-flow-change`: fresh, independent, read-only implementation
  review.

## CLI

The CLI is the complete local operation and recovery surface. The packaged
launcher selects a supported Python interpreter:

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py --help
```

When invoking an installed copy directly, replace `.` with its plugin root.

### Configure where the plugin is active

With no scope configuration, the plugin is active everywhere. Exclude a
directory and all of its descendants:

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --mode all --add-exclude /path/to/excluded-directory
```

Activate only inside selected directories:

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --mode allowlist \
  --add /path/to/project-a \
  --add /path/to/project-b
```

Inspect or change the configuration:

```sh
# Show current scope.
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py scope

# Check one directory.
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --check /path/to/project

# Remove one exclusion.
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  scope --remove-exclude /path/to/excluded-directory

# Restore the default all-directories scope and protected-path policy.
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py scope --clear
```

Include and exclude rules are recursive. The deepest matching directory wins;
an equal include/exclude match resolves to exclude.

### Start a task directly

`--repo` is required and repeatable. Repository paths must identify Git
repositories.

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py start \
  --repo /path/to/project \
  --workspace-strategy worktree \
  --requirement "Implement the requested change"
```

For bounded lite work, declare exact repository-relative target paths:

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py start \
  --repo /path/to/project \
  --workspace-strategy in-place \
  --change-category docs \
  --target-path README.md \
  --target-path docs/usage.md \
  --requirement "Update the user documentation"
```

For a multi-repository task, repeat `--repo`:

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py start \
  --repo /path/to/service \
  --repo /path/to/client \
  --workspace-strategy worktree \
  --requirement "Change the shared contract and both implementations"
```

### Inspect and resume

```sh
# List tasks.
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py list

# Compact agent projection.
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  show --task <task-id> --profile agent-v1

# Full command-specific help.
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py <command> --help
```

Do not edit persisted task JSON directly. Use CLI or MCP actions so revision,
approval, evidence, and recovery invariants remain intact.

## State and configuration

Task state never belongs in a target repository. The data directory resolves in
this order:

1. explicit `--data-dir`;
2. `DEV_FLOW_DATA_DIR`;
3. Codex-provided `PLUGIN_DATA`;
4. `~/Library/Application Support/dev-flow-orchestrator`.

Use the same data directory when starting, inspecting, and resuming a task.
`scope` configuration is stored in that data directory.

## Codex integration

### Hook

The lifecycle Hook restores task context on session start and compaction,
injects bounded worker assignments, checks worker results, and guards Bash or
file-editing tools. Internal Hook errors fail open; the controller remains the
only workflow state machine.

### MCP

The bundled macOS MCP profile is optional and disabled by default. When enabled,
it launches `scripts/dev_flow_mcp.py` through the packaged launcher and exposes:

- `task-next`;
- `node-description`;
- `evidence-read`;
- `action-preview`;
- `action-apply`;
- `worker-result`.

The Skill remains usable through the injected CLI locator when MCP is disabled
or unavailable.

## Architecture

```text
.codex-plugin/plugin.json       plugin identity and Codex interface
.mcp.json                       optional macOS MCP profile
hooks/                          lifecycle and tool guardrail Hook
scripts/dev_flow.py             CLI controller and sealed V4 registries
scripts/dev_flow_mcp.py         typed stdio MCP facade
scripts/dev_flow_parts/         standard-library runtime modules
skills/                         public orchestration and read-only Skills
workflows/catalog.json          full@4 and lite@4 catalog
workflows/activation.json       three supported activation profiles
workflows/bundles/              package-owned graph, schema, and playbook bytes
workflows/provenance/           V4 runtime inventory and genesis
templates/                      local marketplace examples
```

Target repositories cannot override packaged workflow definitions or handlers.

## Recovery

Interrupted effects are inspected before they are changed:

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  action-recovery-inspect --help
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  action-recovery-preview --help
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py \
  action-recovery-apply --help
```

If trusted host authority cannot prove a safe outcome, recovery returns a
bounded `UNRESOLVED` operator-intervention packet and stops. It does not infer
settlement, redispatch an effect, or fabricate approval.

## Development and verification

Contributor rules are in [AGENTS.md](AGENTS.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

Use `codebase-memory` for discovery, confirm material conclusions in source,
query OpenSpec for live JSON instructions, and run only the smallest focused
tests that cover a change. Full unittest discovery is prohibited for this
repository.

## License

See [LICENSE](LICENSE).
