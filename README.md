# Dev Flow Orchestrator

Dev Flow Orchestrator is one macOS Codex plugin for guarded, resumable
development work. Its runtime is V4-native: every new task uses task schema
v4 and resolves directly to exactly one installed workflow bundle:

- `lite@4` for bounded single-repository work;
- `full@4` for full single- or multi-repository work.

Prerequisites are macOS, Git, and Python 3.9 or newer.

The catalog contains only those bundles. The activation matrix exposes three
profiles: lite single-repository, full single-repository, and full
multi-repository. Each task pins its graph and bundle SHA-256 identity.

## Architecture

The controller in `scripts/dev_flow.py` loads standard-library-only fragments
from `scripts/dev_flow_parts/`. Direct V4 registries bind commands, guards,
reducers, gates, executors, action transactions, journals, receipts,
reconciliation, workspace effects, review effects, external tools, and
multi-repository orchestration.

Workflow state lives outside target repositories under the explicit
`--data-dir` supplied by Codex. Git-changing actions are deterministic,
controller-gated, and never imply stash, reset, clean, commit, push, or
force-push authority.

`codebase-memory` is discovery evidence. Baseline and current-workspace
project IDs remain separate, phase selection is explicit, and material
conclusions must be confirmed in source.

## Entry points

- `scripts/dev_flow.py`: CLI controller.
- `scripts/dev_flow_mcp.py`: typed MCP surface.
- `hooks/dev_flow_hook.py`: fail-open context and command guardrail Hook.
- `skills/follow-dev-flow`: public workflow Skill.
- `skills/analyze-change-impact`: read-only impact Skill.
- `skills/review-dev-flow-change`: independent read-only review Skill.

The MCP configuration is intentionally disabled by default and targets the
packaged macOS launcher. The Hook configuration uses the same packaged Python
launcher.

## Local inspection

```sh
./scripts/dev_flow_python_launcher ./scripts/dev_flow.py --help
./scripts/dev_flow_python_launcher ./scripts/dev_flow_mcp.py
```

Run only the focused tests named by the active activation profile. Do not use
unittest discovery for this repository.

See [INSTALL.md](INSTALL.md) for installation and
[CONTRIBUTING.md](CONTRIBUTING.md) for verification rules.
