# Installation and file placement

Keep the plugin directory intact. Paths below are relative to the plugin root unless an absolute destination is shown.

## Plugin files

| Source | Destination | Purpose |
|---|---|---|
| `.codex-plugin/plugin.json` | `<plugin-root>/.codex-plugin/plugin.json` | Required plugin manifest |
| `.gitignore` | `<plugin-root>/.gitignore` | Excludes local Python/test by-products from plugin source control |
| `AGENTS.md` | `<plugin-root>/AGENTS.md` | Contributor rules for maintaining this plugin |
| `README.md` | `<plugin-root>/README.md` | Architecture, prerequisites, and validation overview |
| `INSTALL.md` | `<plugin-root>/INSTALL.md` | This installation and placement guide |
| `hooks/hooks.json` | `<plugin-root>/hooks/hooks.json` | Hook registration discovered by Codex |
| `hooks/dev_flow_hook.py` | `<plugin-root>/hooks/dev_flow_hook.py` | Resume context and best-effort safety guards |
| `scripts/dev_flow.py` | `<plugin-root>/scripts/dev_flow.py` | Persistent state-machine controller |
| `scripts/__init__.py` | `<plugin-root>/scripts/__init__.py` | Makes controller helpers importable by hooks/tests |
| `skills/follow-dev-flow/SKILL.md` | `<plugin-root>/skills/follow-dev-flow/SKILL.md` | Main workflow entry point |
| `skills/follow-dev-flow/agents/openai.yaml` | `<plugin-root>/skills/follow-dev-flow/agents/openai.yaml` | UI metadata for the main skill |
| `skills/follow-dev-flow/assets/direct-contract-template.md` | `<plugin-root>/skills/follow-dev-flow/assets/direct-contract-template.md` | Compact plan template for the direct route |
| `skills/follow-dev-flow/references/state-machine.md` | `<plugin-root>/skills/follow-dev-flow/references/state-machine.md` | States, commands, gates, and execution rules |
| `skills/follow-dev-flow/references/index-routing.md` | `<plugin-root>/skills/follow-dev-flow/references/index-routing.md` | Dual-index roles, naming, freshness, and explicit project routing |
| `skills/follow-dev-flow/references/openspec-route.md` | `<plugin-root>/skills/follow-dev-flow/references/openspec-route.md` | Dynamic OpenSpec route guidance |
| `skills/follow-dev-flow/references/recovery.md` | `<plugin-root>/skills/follow-dev-flow/references/recovery.md` | Resume, drift, collision, and failure recovery |
| `skills/analyze-change-impact/SKILL.md` | `<plugin-root>/skills/analyze-change-impact/SKILL.md` | codebase-memory impact-analysis procedure |
| `skills/analyze-change-impact/agents/openai.yaml` | `<plugin-root>/skills/analyze-change-impact/agents/openai.yaml` | UI metadata for the impact skill |
| `skills/analyze-change-impact/assets/impact-report-template.md` | `<plugin-root>/skills/analyze-change-impact/assets/impact-report-template.md` | Per-project impact-report template |
| `skills/analyze-change-impact/references/evidence-workflow.md` | `<plugin-root>/skills/analyze-change-impact/references/evidence-workflow.md` | Graph-to-source confirmation rules |
| `skills/review-dev-flow-change/SKILL.md` | `<plugin-root>/skills/review-dev-flow-change/SKILL.md` | Independent review procedure |
| `skills/review-dev-flow-change/agents/openai.yaml` | `<plugin-root>/skills/review-dev-flow-change/agents/openai.yaml` | UI metadata for the review skill |
| `skills/review-dev-flow-change/references/independent-review.md` | `<plugin-root>/skills/review-dev-flow-change/references/independent-review.md` | Snapshot coverage, finding, and verdict rules |
| `templates/project/AGENTS.md` | Keep as a template; optionally merge into `<business-repo>/AGENTS.md` | Repository-level policy that invokes the workflow |
| `templates/marketplace-entry.json` | Keep as a template; merge its object into a marketplace's `plugins[]` | Local plugin catalog entry |
| `templates/personal-marketplace.example.json` | Copy to `~/.agents/plugins/marketplace.json` only when that file does not exist | Complete first personal marketplace catalog |
| `tests/test_dev_flow.py` | `<plugin-root>/tests/test_dev_flow.py` | State-machine and Git-boundary regression tests |
| `tests/test_hooks.py` | `<plugin-root>/tests/test_hooks.py` | Hook bootstrap and guardrail regression tests |

Do not move individual skill references, assets, or `agents/openai.yaml` files out of their skill directories. Their relative links are intentional.

## Recommended personal installation

Use this layout when the workflow should be available across all projects:

```text
~/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
    ├── .codex-plugin/plugin.json
    ├── hooks/
    ├── scripts/
    ├── skills/
    ├── templates/
    └── tests/
```

Copy the complete plugin root to `~/plugins/dev-flow-orchestrator/`. If `~/.agents/plugins/marketplace.json` does not exist, use `templates/personal-marketplace.example.json` as its initial contents. If it already exists, merge only the object in `templates/marketplace-entry.json` into its `plugins` array and preserve the existing marketplace name, interface metadata, ordering, and plugin entries. The relative source path `./plugins/dev-flow-orchestrator` assumes this layout.

Restart the ChatGPT desktop app, install the plugin from the personal marketplace, and start a new Codex task after installation or an update so the skills and hooks are reloaded.

### Limiting the plugin to specific directories

A personal installation is visible to every project. To keep it out of unrelated ones, record a directory scope in `<PLUGIN_DATA>/config.json` through the controller. Take `<PLUGIN_DATA>` from the bootstrap context the hook injects at session start:

```bash
python3 ~/plugins/dev-flow-orchestrator/scripts/dev_flow.py scope --data-dir <PLUGIN_DATA> --add ~/work
```

The first `--add` switches the scope from active-everywhere to allowlist mode. Outside the scope the hooks emit nothing and `start` refuses the repository, so those sessions behave as if the plugin were not installed. Verify a directory with `scope --check <dir>` and reverse the change with `scope --clear`. See the README's `Directory scope` section for excludes, the deepest-match rule, the `DEV_FLOW_SCOPE` override, and the active-task carve-out. Because the hook reads this file on every event, a scope change applies to the next Codex event without reinstalling the plugin.

### Updating an already installed local copy

Do not hand-edit the existing marketplace entry merely to defeat Codex caching. After replacing the files in the marketplace's referenced local plugin source, use the bundled `plugin-creator` skill helpers from its own skill root:

```bash
python3 <plugin-creator-skill-root>/scripts/update_plugin_cachebuster.py \
  <plugin-root>
python3 <plugin-creator-skill-root>/scripts/read_marketplace_name.py
codex plugin add dev-flow-orchestrator@<marketplace-name-printed-above>
```

The cachebuster helper preserves the base version and replaces any older `+codex.<token>` suffix with one UTC-timestamp suffix. The no-argument marketplace-name helper reads the default personal marketplace at `~/.agents/plugins/marketplace.json`; do not run `codex plugin marketplace add` for that default location. For a different confirmed local marketplace, pass `--marketplace-path <path-to-marketplace.json>` to `read_marketplace_name.py`, ensure that non-default marketplace is configured, and reinstall using the name it prints. Start a new Codex task after reinstall so updated skills and hooks are loaded.

### Upgrading from 0.1.x

The dual-index release keeps state schema version 1 and reads existing tasks without rewriting them on load. Existing `repositories[].index` records remain the current baseline records; additive `repositories[].workspace_index` starts empty and `repositories[].index_history` starts as an empty list when absent. Later reindexing archives complete superseded records in that history. A task that has not created its implementation worktree continues normally. A task at `WORKSPACE_READY`, `PLANNING`, `IMPLEMENTING`, or `VERIFYING` must index each recorded implementation worktree with the current generation's workspace-specific project name and `persistence=false`, then record the exact returned ID with `record-index --role workspace` before the next guarded transition or review snapshot. Do not repurpose the old baseline project ID. A legacy task already in `REVIEWING` or `FINALIZING` may finish against its existing immutable snapshot/review chain; if it needs implementation or planning rework, perform a supported impact reassessment to `INDEXED` and recreate the downstream workspace/index evidence instead of bypassing the new gate.

## Repository-scoped alternative

For a shared marketplace rooted at `<marketplace-root>`:

```text
<marketplace-root>/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

The same marketplace entry works because its source path is relative to `<marketplace-root>`. Use this placement only when the repository or team should own the plugin catalog.

## Files in each business repository

- Optionally merge `templates/project/AGENTS.md` into the repository's existing `AGENTS.md`. Do not overwrite project-specific instructions.
- Do not copy the plugin hooks, controller, or state files into the business repository.
- Do not copy a fixed OpenSpec workflow from this plugin. Run the installed OpenSpec initialization or update command for that project and let it generate the current `.codex/skills/openspec-*` files.
- Keep the existing user- or project-scoped codebase-memory MCP configuration. This plugin intentionally has no machine-specific `.mcp.json`.

## Runtime data

Codex supplies a private `PLUGIN_DATA` path to each installed plugin's hook commands. The hooks inject the resolved absolute path into the conversation as bootstrap/checkpoint context, and the workflow skill passes it explicitly as `--data-dir` on every controller call. The controller creates these runtime-only paths there:

```text
<PLUGIN_DATA>/
├── config.json
├── config.lock
├── workspace-registry.json
├── workspace-registry.lock
├── tasks/<task-id>/state.json
├── tasks/<task-id>/state.lock
├── tasks/<task-id>/events.jsonl
├── tasks/<task-id>/artifacts/
├── tasks/<task-id>/workspace-plans/
├── tasks/<task-id>/reviews/
├── analysis/<task-id>/<repository-id>/
├── workspaces/<task-id>/<repository-id>/
└── workspaces/<task-id>/r<generation>/<repository-id>/
```

The unnumbered workspace path is generation 0; impact reassessment retires its recorded workspaces and uses `r1`, `r2`, and later generation directories. `config.json` holds the directory scope and is the only one of these files meant to be changed by the user, through the controller's `scope` command. `workspace-registry.json` is the controller's durable cross-task ownership registry for worktree paths and repository branches; its lock serializes competing plans. `tasks/<task-id>/artifacts/` is the task's controlled location for impact reports, direct contracts, and independent review reports. The controller exclusively owns registry/lock files, `state.json`, `events.jsonl`, review snapshots, analysis worktrees, and implementation-worktree records; do not edit them manually.

These paths are not source files and must not be copied into a business repository or committed with the plugin.

The state records each repository's current baseline/workspace codebase-memory project identifiers, full superseded-index history, and provenance. The graph database itself remains owned by codebase-memory and is not stored under `PLUGIN_DATA`; index with `persistence=false` so no portable graph artifact is written into a business worktree. Retired and superseded project IDs remain in workflow history for audit, and the plugin does not delete external codebase-memory projects automatically. Cleanup is a separate explicitly authorized maintenance action.
