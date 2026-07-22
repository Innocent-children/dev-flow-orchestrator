# Dev Flow Orchestrator

This plugin drives a guarded development workflow across Git repositories, `codebase-memory-mcp`, and OpenSpec. It persists machine-readable task state, keeps human approvals explicit, and reviews committed, staged, unstaged, and untracked changes before handoff.

It uses a dual-index model per repository. A baseline project indexes the immutable detached analysis worktree for impact analysis and route decisions; a workspace project indexes the current-generation implementation worktree for planning, implementation, verification, and review discovery. Codebase-memory does not choose between them automatically: every query must pass the phase-selected project's exact returned ID. The controller exposes that choice in `show.index_selection`, archives every superseded index record for audit/ID isolation, and blocks downstream gates when a required workspace index is missing or stale.

It deliberately does not switch or pull the developer's current checkout. After preflight and explicit authorization, it resolves the configured remote's default branch, optionally fetches that remote, pins an immutable base commit, and creates a detached analysis worktree. Both direct and OpenSpec implementation then use separate task branches in isolated linked worktrees. Existing source-branch and dirty-state evidence remains visible and untouched; proceeding around an exact dirty snapshot requires structured approval.

The lifecycle hooks inject the plugin's absolute controller and private data-directory paths at session start and prompt submission. The main skill passes that data directory explicitly on every controller call, because `PLUGIN_DATA` belongs to the hook process and is not assumed to reach later shell tools. The hooks also provide task-scoped guardrails, not a security boundary: they protect recognized file-write tools and common dangerous Git commands only while a matching task is active; shell scripts, nested tooling, hosted tools, or disabled/untrusted hooks can bypass them. The controller's state, artifact hashes, explicit approvals, and final independent review remain the source of truth. Unrelated Codex tasks are not globally restricted by installing this plugin.

The evidence pipeline fails closed when Git cannot expose complete bytes reliably: tracked `assume-unchanged`/`skip-worktree` entries (including sparse checkouts), dirty initialized submodules, and clean/process content filters such as Git LFS are rejected. These are deliberate current limitations, not silently degraded coverage; normalize the checkout or use a separately governed repository/flow before continuing.

Avoid explicit workspace path or branch overrides that differ from another task only by letter case. On a case-insensitive filesystem, a not-yet-existing case-only alias can pass planning before Git rejects it during worktree creation; the controller then fails closed and requires collision recovery, but the current controller does not normalize those aliases at claim time.

## Source layout

Keep the files in these locations relative to the plugin root:

```text
dev-flow-orchestrator/
├── .codex-plugin/plugin.json        # Required plugin manifest
├── INSTALL.md                        # Exact personal/repository placement map
├── hooks/
│   ├── hooks.json                   # Codex lifecycle hook registration
│   └── dev_flow_hook.py             # State injection and best-effort guardrails
├── scripts/
│   └── dev_flow.py                  # Persistent state machine and Git control plane
├── skills/
│   ├── follow-dev-flow/             # Main workflow entry point
│   ├── analyze-change-impact/       # codebase-memory impact analysis
│   └── review-dev-flow-change/      # Independent full-change review
├── templates/project/AGENTS.md      # Optional policy to copy into a target repo
├── templates/marketplace-entry.json # Entry to merge into a local marketplace
├── templates/personal-marketplace.example.json # Complete first-marketplace example
└── tests/                            # Offline unit tests
```

Do not copy the hook or helper scripts into each business repository. Install the whole plugin directory as one unit. In each target repository, keep only project-specific guidance in `AGENTS.md` and let `openspec init`/`openspec update` generate the current Codex OpenSpec skills when that route is selected.

## Runtime prerequisites

- Python 3.9 or newer
- Git
- OpenSpec on `PATH` for the OpenSpec route
- An enabled `codebase-memory-mcp` server for baseline impact analysis and current-workspace discovery

The plugin intentionally does not bundle a machine-specific `.mcp.json`; use the existing user- or project-scoped MCP configuration.

## Development validation

From this directory:

```bash
python3 -m unittest discover -s tests -v
```

Then validate the three skill directories with `skill-creator/scripts/quick_validate.py` and validate this plugin root with `plugin-creator/scripts/validate_plugin.py`.

## Installation placement

See [`INSTALL.md`](INSTALL.md) for the exact destination of every file. For personal use, place this complete directory at the plugin location referenced by your personal marketplace entry. For a repository marketplace, place it at `<marketplace-root>/plugins/dev-flow-orchestrator/` and point that marketplace entry to `./plugins/dev-flow-orchestrator`.

After installing or updating the plugin, start a new Codex task so the new skills and hooks are loaded. Review and trust the bundled hooks when Codex asks.
