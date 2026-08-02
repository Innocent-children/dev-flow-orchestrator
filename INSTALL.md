# Install Dev Flow Orchestrator

This guide installs the single plugin identity `dev-flow-orchestrator` from a
local Codex marketplace. It also covers replacement, data storage, Hook
pickup, acceptance, and removal.

## 1. Requirements

Supported and validated for this release:

- macOS;
- Git;
- Python 3.9–3.14;
- Codex with the `codex plugin` command and `SessionStart`,
  `UserPromptSubmit`, and `PreToolUse` Hook support.

Check the host:

```sh
sw_vers
git --version
python3 --version
codex plugin --help
```

The runtime uses only Python's standard library. Do not run `pip install`,
`uv sync`, `npm install`, or `pnpm install` for this plugin.

## 2. Put the source in a marketplace root

These instructions use `$HOME` as the marketplace root. Call the checked-out
candidate `SOURCE_ROOT`; it is used only for source validation and marketplace
registration, not as proof of the installed runtime path:

```text
$HOME/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

Clone over SSH:

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

HTTPS alternative:

```sh
mkdir -p "$HOME/plugins"
git clone https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

If you received a reviewed local candidate, place that exact directory at
`$HOME/plugins/dev-flow-orchestrator`. Do not overlay it on an older copy.

Validate the source before registration:

```sh
cd "$HOME/plugins/dev-flow-orchestrator"
python3 -I -S scripts/validate_package.py
python3 -m json.tool .codex-plugin/plugin.json
```

The manifest name must remain `dev-flow-orchestrator`.

## 3. Create or update the personal marketplace

For a new personal marketplace:

```sh
mkdir -p "$HOME/.agents/plugins"
cp \
  "$HOME/plugins/dev-flow-orchestrator/templates/personal-marketplace.example.json" \
  "$HOME/.agents/plugins/marketplace.json"
```

If `~/.agents/plugins/marketplace.json` already exists, do not overwrite it.
Merge the object from `templates/marketplace-entry.json` into the existing
`plugins` array. Keep exactly one entry named `dev-flow-orchestrator`.

Validate the result:

```sh
python3 -m json.tool "$HOME/.agents/plugins/marketplace.json"
```

## 4. Install

The default personal marketplace at `~/.agents/plugins/marketplace.json` is
discovered automatically. Do not register `$HOME` with `marketplace add`.

```sh
codex plugin list
```

Install:

```sh
codex plugin add dev-flow-orchestrator@personal
codex plugin list
```

Expected outcome: exactly one installed and enabled
`dev-flow-orchestrator@personal`.

Start a new Codex session after installation. Existing sessions do not prove
that the newly installed Skill or Hook was picked up.

In the new session, open `/hooks`, confirm the Hook source is the installed
plugin snapshot, review and trust the current definition, and verify that
`SessionStart`, `UserPromptSubmit`, and `PreToolUse` are enabled. A source-tree
test cannot substitute for this installed pickup check.

## 5. Replace an existing installation

Keep the same plugin identity and perform one atomic source cutover. An
installed snapshot can remain in Codex's cache even after the marketplace
source directory changes, so a replacement candidate must carry a new
cachebuster version.

1. Obtain the complete reviewed replacement candidate with its new cachebuster.
2. Replace `$HOME/plugins/dev-flow-orchestrator` as a whole; do not overlay
   files on the older source.
3. Remove the installed snapshot:

   ```sh
   codex plugin remove dev-flow-orchestrator@personal
   ```

4. Reinstall the same identity:

   ```sh
   codex plugin add dev-flow-orchestrator@personal
   ```

5. Start a new Codex session.
6. Confirm `codex plugin list` contains exactly one enabled instance at the new
   version.
7. Open `/hooks`, confirm the definition comes from the new installed snapshot,
   and trust the new hash if it changed.
8. Verify that the installed `hooks/hooks.json` has exactly one definition for
   each of `SessionStart`, `UserPromptSubmit`, and `PreToolUse`.

Do not install a sibling name or keep simultaneous copies from multiple
marketplaces. V4 data remains in the plugin data base directory, but V5 never
loads it. Do not move, repair or delete V4 data as part of installation.

## 6. Data directory

Task state must remain outside every target repository.

Codex supplies `PLUGIN_DATA` as the installed plugin's data base directory;
this project does not define or guess a default filesystem path for it. The
Hook injects a locator containing the installed launcher, installed CLI, and
`<PLUGIN_DATA>/v5` as the exact V5 state directory:

```text
<PLUGIN_DATA>/
├── tasks/          # retained V4 data; V5 never reads it
└── v5/
    ├── tasks/
    └── locks/
```

To operate on installed V5 state, reuse the complete Hook-injected locator;
do not reconstruct either its executable paths or data directory from the
marketplace source.

For an independent direct-CLI task, choose an explicit state directory outside
the target repository. `--data-dir` means that exact directory and does not
append `v5`:

```sh
SOURCE_ROOT="$HOME/plugins/dev-flow-orchestrator"
DATA_DIR="/absolute/path/to/independent-dev-flow-state"

"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" --help
```

Use the same exact data directory for every command that operates on one task.
The controller creates or normalizes its directories to owner-only access,
writes new state files with owner-only permissions, and updates them under a
lock with atomic replacement. Do not edit them directly. Symlinks, non-regular
or malformed state, and lock/write failures fail closed; existing state-file
modes are not an integrity check. The controller does not repair or delete
malformed data automatically.

There is no installation-wide include/exclude directory configuration. Each
task explicitly declares one repository root with `--repo`.

## 7. Verify the CLI package

Create a task in a disposable Git repository:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --repo /path/to/disposable-repository \
  --requirement "Installation smoke"
```

The command prints one JSON object. Use its `task_id`:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" next <task-id>
```

The initial action must be `task.preflight` with an empty payload. Apply it,
then walk the task to completion:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action task.preflight

"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action task.implementation.complete \
  --payload-json '{"summary": "smoke"}'

if (
  cd "$SOURCE_ROOT" &&
  python3 -I -S scripts/validate_package.py
); then
  "$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
    "$SOURCE_ROOT/scripts/dev_flow.py" \
    --data-dir "$DATA_DIR" apply <task-id> \
    --action evidence.test.record \
    --payload-json '{"passed": true, "command": "python3 -I -S scripts/validate_package.py"}'
else
  echo "Package validation failed; no passing evidence was recorded." >&2
  false
fi
```

The `if` block records passing evidence only after the exact command stored in
the payload exits successfully. If validation fails, fix the candidate and
run the command again; do not submit `passed: true`.

The final projection reports `done: true`. `apply` and `cancel` print a receipt
plus the fresh projection; `start` prints the created task. There is no
caller-managed revision bookkeeping in the protocol.

## 8. Verify Hook pickup

The plugin discovers `hooks/hooks.json` automatically.

1. Start a new Codex session inside a disposable repository.
2. Open `/hooks`, confirm the Hook comes from the installed snapshot, and trust
   its current definition.
3. Invoke `$follow-dev-flow` to create an active `lite` task for that repository
   and keep its task ID.
4. Submit a new prompt in the repository. Confirm the injected context now
   contains the installed launcher, CLI handler, `<PLUGIN_DATA>/v5`, task ID,
   persisted requirement, and current projection.
5. Execute the injected locator unchanged with `--help`; do not rebuild it from
   the marketplace source path.
6. Complete a real `lite` task through `done: true`.
7. Confirm a Bash command and `apply_patch` targeting `PLUGIN_DATA` are denied,
   while normal repository commands remain allowed.
8. Place a read-only schema-4 fixture under `<PLUGIN_DATA>/tasks` and confirm
   V5 list/Hook operations still work without reading, changing or deleting it.

Malformed events and internal Hook errors fail open, but the Hook never
writes task state. Repository-local tests and manual execution of the Hook
are not substitutes for this real Codex pickup check.

## 9. User acceptance

Acceptance is complete only when the user confirms:

1. exactly one enabled `dev-flow-orchestrator` plugin is loaded from the frozen
   candidate;
2. the installed Hook definition is trusted and injects one locator containing
   the installed launcher, CLI handler and `<PLUGIN_DATA>/v5`;
3. a real-project `lite` workflow smoke runs from `start` through
   `done: true`, and one custom workflow file selected by absolute path runs
   with zero code difference.

Do not treat the frozen candidate as accepted before those checks are
confirmed.

## 10. Troubleshooting

`Python handler does not exist`
: Check that the marketplace source is the complete candidate and that
  `scripts/dev_flow.py` and `scripts/dev_flow_python_launcher` are present.

`Python 3.9-3.14 was not found`
: Install a supported Python or set `DEV_FLOW_PYTHON` to a verified absolute
  interpreter path.

`ARGUMENT_INVALID` mentioning `--data-dir`
: The CLI requires `--data-dir` before the subcommand. For installed state,
  use the Hook-injected locator; for an independent CLI task, pass an explicit
  state directory. The CLI does not read `PLUGIN_DATA` itself.

`DATA_DIR_REQUIRED`
: An internal controller call supplied an empty data directory. A normal CLI
  invocation that omits the option is rejected earlier as `ARGUMENT_INVALID`.

`REVISION_CONFLICT`
: The task advanced concurrently. Read `error.details.projection` and re-run
  `next`; never replay a stale intent.

`WORKFLOW_IDENTITY_MISMATCH`
: The workflow file changed after the task started. Restore the original file
  or start a new task; the old task cannot run a different flow.

`WORKFLOW_NOT_FOUND`
: The selected workflow id or absolute path does not exist.

`STATE_INVALID`
: A V5 state file is corrupted or inconsistent with its pinned workflow. If a
  direct CLI command is incorrectly pointed at the `PLUGIN_DATA` base instead
  of the injected `<PLUGIN_DATA>/v5`, it can encounter a retained schema-4
  task and report that it is not V5 state. Correctly configured V5 never scans
  `<PLUGIN_DATA>/tasks`.

`TEST_NOT_PASSING`
: The verify node only advances with `passed: true`. Fix the failing test and
  re-apply.

Codex shows a sandbox or tool-permission prompt
: That prompt belongs to the Codex host, not this plugin. Dev Flow does not
  suppress, satisfy, or auto-confirm host-owned permission prompts.

Multiple plugin rows
: Remove duplicate installations and reinstall only
  `dev-flow-orchestrator@personal`.

## 11. Remove

```sh
codex plugin remove dev-flow-orchestrator@personal
```

Remove the marketplace entry only if it is no longer needed. Deleting the
plugin package does not remove the external data directory. Task state is
preserved by default.

Data deletion is a separate destructive operator action. Consider it only
after all active tasks are resolved.
