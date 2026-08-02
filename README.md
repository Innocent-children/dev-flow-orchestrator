# Dev Flow Orchestrator

[简体中文](README_CN.md) · [Installation](INSTALL.md) ·
[Architecture](ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md)

Dev Flow Orchestrator turns a software requirement into a resumable Codex
task. It keeps the task moving through clear stages, saves progress between
sessions, and gives Codex one concrete next step at a time.

Codex still writes the code and runs the verification. The plugin coordinates
the sequence and records the result of each stage. Its standard `lite`
workflow covers repository preflight, implementation, and verification, while
custom workflow files can describe project-specific sequences.

## What it gives you

- Resume a development task in a later Codex session by task ID.
- Work on one clear stage at a time instead of reconstructing progress from
  chat history.
- Check the target Git repository before implementation begins.
- Complete verification only after recording a passing command result.
- Keep workflow state outside the target repository.
- Add code-impact analysis, implementation review, or a custom workflow when
  the task needs more structure.

Each task works with one Git repository.

## Requirements

- macOS;
- Python 3.9–3.14;
- Git, with the target path set to a worktree root that already has a commit;
- Codex with plugin and Hook support.

The plugin runtime uses the Python standard library and does not require a
package installation step. The bundled Skills use the external
`codebase-memory-mcp` integration for code discovery.

## Install

For a new personal marketplace:

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"

cd "$HOME/plugins/dev-flow-orchestrator"
python3 -I -S scripts/validate_package.py

mkdir -p "$HOME/.agents/plugins"
cp templates/personal-marketplace.example.json \
  "$HOME/.agents/plugins/marketplace.json"

codex plugin add dev-flow-orchestrator@personal
```

Use the `cp` command only when
`~/.agents/plugins/marketplace.json` does not exist. If it already exists,
merge `templates/marketplace-entry.json` into its `plugins` array.

Start a new Codex task after installation, open `/hooks`, and review and trust
the installed Hook definition. See [INSTALL.md](INSTALL.md) for HTTPS cloning,
existing marketplace setup, upgrades, verification, troubleshooting, and
removal.

## Start and resume a task

Daily use goes through `$follow-dev-flow`.

Start a task with the repository path, workflow, and requirement:

```text
Use $follow-dev-flow to start a task with the lite workflow in this repository:
/absolute/path/to/repository

Requirement:
<what must be delivered>
```

Keep the returned task ID. To continue later:

```text
Use $follow-dev-flow to resume task <task-id>.
```

The installed Hook reconnects Codex to an active task when the current
directory is inside its repository. The Skill then follows the next stage,
records the result, and continues until the task is done.

## The `lite` workflow

`lite` is the standard workflow included with the plugin:

```text
preflight → implement → verify → done
any unfinished stage ── cancel ──→ cancelled
```

| Stage | What happens |
|---|---|
| `preflight` | The plugin performs a bounded, read-only Git inspection and records the starting repository state. |
| `implement` | Codex makes the requested change and records an implementation summary. |
| `verify` | Codex runs the relevant check and records its command and result. The task finishes only with a passing result. |

Preflight requires the exact root of a non-bare Git worktree with an existing
`HEAD` commit. A dirty worktree and detached `HEAD` are supported.

To stop an unfinished task, explicitly ask Codex to cancel it and provide a
reason. Cancellation is available from every unfinished `lite` stage.

## Additional capabilities

The plugin includes two supporting Skills:

- `$analyze-change-impact` traces the likely impact of a change and confirms
  material findings in source;
- `$review-dev-flow-change` performs an independent, read-only implementation
  review.

You can also pass an absolute JSON or YAML workflow path instead of `lite`.
Custom workflows use the step types provided by the runtime and may attach
driver metadata such as `tool: openspec` to tell Codex which tool should handle
a stage. A running task remains bound to the selected workflow, so keep that
file available and unchanged until the task finishes.

See [Workflow definitions](ARCHITECTURE.md#workflow-definitions) for the file
format, supported handlers, payload contracts, and extension points.

## State and safety

- Task state is stored in the plugin data directory, not in the target
  repository. The state directory and repository must be separate directory
  trees.
- State updates use locks and atomic replacement. Do not edit task state files
  by hand.
- Git preflight is read-only. The controller does not automatically stash,
  reset, clean, commit, checkout, merge, or push.
- `$follow-dev-flow` asks for explicit authorization before cancellation and
  before `stash`, `reset`, `clean`, `force-push`, `rebase`, `merge`, `commit`,
  or `push` operations.

The Hook restores task context and guards the plugin data path for common
shell and editing tools. It is an operational guardrail rather than a security
sandbox: if the Hook cannot process an event, it does not block the host
operation. Workflow validation and state transitions remain the controller's
responsibility.

## CLI and further documentation

The packaged CLI exposes `start`, `show`, `next`, `apply`, `cancel`, and
`list`. Direct CLI use requires an explicit `--data-dir`; use the packaged
Python launcher and keep the same data directory for every command on a task.
The [installation guide](INSTALL.md#7-verify-the-cli-package) contains a
complete command-line walkthrough.

- [INSTALL.md](INSTALL.md): installation, upgrades, verification, and
  troubleshooting.
- [ARCHITECTURE.md](ARCHITECTURE.md): workflow format, projections, state, and
  module boundaries.
- [CONTRIBUTING.md](CONTRIBUTING.md): development and validation guidance.
- [LICENSE](LICENSE): license terms.
