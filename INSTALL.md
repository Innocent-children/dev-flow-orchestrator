# Install Dev Flow Orchestrator

This guide installs the single plugin identity `dev-flow-orchestrator` from a
local Codex marketplace. It also covers replacement, data storage, Hook pickup,
optional MCP, acceptance, and removal.

## 1. Requirements

Supported and validated for this release:

- macOS;
- Git;
- Python 3.9–3.14;
- Codex with the `codex plugin` command and `UserPromptSubmit` Hook support.

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

These instructions use `$HOME` as the marketplace root:

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
python3 -I -S scripts/validate_greenfield_architecture.py
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
that the newly installed Skill, Hook, or MCP configuration was picked up.

## 5. Replace an existing installation

Keep the same plugin identity and perform one atomic source cutover. A
popup-era installed snapshot can remain in Codex's cache even after the
marketplace source directory changes, so a replacement candidate must carry a
new cachebuster version.

1. Obtain the complete reviewed replacement candidate with its new cachebuster.
2. Replace `$HOME/plugins/dev-flow-orchestrator` as a whole; do not overlay
   files on the popup-era source.
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
7. Verify that the installed manifest has exactly one `UserPromptSubmit` Hook
   and that Hook, CLI, and optional MCP all resolve the same `PLUGIN_DATA`
   directory.

Do not install a sibling name or keep simultaneous copies from multiple
marketplaces. Do not run old and new runtimes side by side. Old authority
records are not migrated or accepted as conversation confirmation evidence.

## 6. Data directory

Task state must remain outside every target repository.

Codex supplies `PLUGIN_DATA` to the installed Hook and MCP server. For direct
CLI use, `--data-dir` is required:

```sh
PLUGIN_ROOT="$HOME/plugins/dev-flow-orchestrator"
DATA_DIR="$HOME/Library/Application Support/dev-flow-orchestrator"

"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" --help
```

Use the same data directory for every command that operates on one task.
Task, effect, and confirmation files are private, revisioned where applicable,
locked, and atomically replaced. Confirmation directories use
local-account-only permissions and remain outside target repositories. Do not
edit them directly.

CLI, MCP, and the packaged Hook must use this exact same directory. A
confirmation recorded under another data directory cannot authorize the task,
and copying old authority records into this directory does not convert them.
Unsafe permissions or symlinks, malformed confirmation records, lock/write
failure, and confirmation-index capacity failure all fail closed: the guarded
operation remains unapplied and the controller does not repair or delete data
automatically.

There is no installation-wide include/exclude directory configuration. Each
task explicitly declares one or more repository roots with repeatable
`--repo`.

## 7. Verify the CLI package

Create a task in a disposable Git repository:

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --workspace-strategy in-place \
  --repo /path/to/disposable-repository \
  --requirement "Installation smoke"
```

The command prints one JSON object. Use its `task_id`:

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" next <task-id> \
  --session-id <hook-injected-session-id>
```

The initial action must be `task.preflight`. After preflight, a
single-repository Lite task must enter `implement` directly; a
multi-repository Lite task must enter `repository-plan`. Lite has no
workflow-entry approval.

Inspect `next` before every action. When its `required_authority` is
`task-revision+<grant>`, submit the exact current operation through
`$follow-dev-flow`, CLI, or MCP with the current bounded conversation-session
routing:

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --expected-revision <revision> \
  --action <action-id> \
  --payload-json '<json-object>' \
  --session-id <hook-injected-session-id>
```

The first call creates or reloads a durable `PENDING` request and performs no
guarded state mutation, Git command, or external effect. The agent must show
the exact bounded request, ask for the projected exact reply, and end the turn.
There is no timeout.

In a later real Codex prompt, use bare `同意` or `approve` only when the
projection says one request is unambiguous. Otherwise use
`同意 <request-id>` or `approve <request-id>`. `拒绝`, `deny`, and their
request-ID forms deny under the same ambiguity rules. The
`UserPromptSubmit` Hook records that decision but does not apply the operation.
Start the next turn by reloading `next`; only `CONFIRMED` permits the exact
same operation to be retried and consumed once. Denial is terminal for that
binding.

Do not poll, retry while pending, auto-confirm, invoke the Hook manually, or
pass approval/actor/request/raw-prompt/serialized-record fields through CLI or
MCP. The conversation session and turn are correlation and audit evidence,
not macOS or authenticated-human identity. `--session-id` and optional
`--request-turn-id` route the conversation only and must come from current
Hook context rather than caller invention.

## 8. Verify Hook pickup

The plugin discovers `hooks/hooks.json` automatically.

1. Start a new Codex session inside a repository used by a current task.
2. Invoke `$follow-dev-flow` or submit a normal prompt.
3. Confirm the injected context contains the installed controller locator,
   data directory, task ID, revision, current `agent-v1` projection, and
   correlation-only `conversation_routing`.
4. Inspect the installed `hooks/hooks.json` and confirm there is exactly one
   packaged `UserPromptSubmit` launch path.
5. Confirm the injected controller locator, optional MCP process, and Hook all
   resolve the same installed source and `PLUGIN_DATA`.
6. For a disposable pending request, submit one exact reply through the real
   Codex prompt UI. Confirm the refreshed projection records the decision but
   the Hook does not change the task revision or apply the action.

Malformed events and internal Hook errors fail open, but every guarded
operation stays unapplied. Repository-local tests and manual execution of the
Hook are not substitutes for this real Codex pickup check.

## 9. Enable and verify MCP

The packaged `dev-flow-macos` MCP server is optional and disabled by default.
Enable it in the installed plugin's Codex settings, then start another new
session.

Tool discovery must expose exactly:

- `task-start`
- `task-show`
- `task-next`
- `task-preflight`
- `action-apply`
- `effect-inspect`
- `effect-recover`

MCP and CLI call the same controller through independent transports.

For package-local protocol diagnosis:

```sh
PLUGIN_DATA="$DATA_DIR" \
  "$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow_mcp.py"
```

The process waits for newline-delimited JSON-RPC on stdin; it is not an
interactive shell.

## 10. User acceptance

Acceptance is complete only when the user confirms:

1. exactly one enabled `dev-flow-orchestrator` plugin is loaded from the frozen
   candidate;
2. exactly one real `UserPromptSubmit` confirmation Hook is loaded and Hook,
   CLI, and optional MCP use the same data directory;
3. a real-project `lite@4` multi-repository smoke and a representative
   `full@4` workflow smoke, including request → later reply → reload → exact
   retry for one gated Full action.

Do not archive the active OpenSpec change before those checks are accepted.

## 11. Troubleshooting

`Python handler does not exist`
: Check that the marketplace source is the complete candidate and that
  `scripts/dev_flow.py`, `scripts/dev_flow_mcp.py`, and
  `scripts/dev_flow_python_launcher` are present.

`Python 3.9-3.14 was not found`
: Install a supported Python or set `DEV_FLOW_PYTHON` to a verified absolute
  interpreter path.

`DATA_DIR_REQUIRED`
: Pass `--data-dir` to CLI, `--data-dir` to a package-local MCP launch, or let
  Codex provide `PLUGIN_DATA`.

`REVISION_CONFLICT`
: Reload `next`, use the returned current revision, and do not replay stale
  intent.

`CONFIRMATION_SESSION_REQUIRED`
: Use the actual Hook-injected session routing. Do not invent a session or run
  the Hook manually.

`CONFIRMATION_REPOSITORY_CONTEXT_REQUIRED` or `CONFIRMATION_EVENT_INVALID`
: Confirm the request uses the current canonical task repository/workspace
  context and that the real Hook supplied bounded session, turn, cwd, and
  prompt fields.

`CONFIRMATION_DENIED`
: The exact binding is terminal. Do not retry or recreate it; reconsideration
  requires a new controller-owned revision/binding or a new task.

`CONFIRMATION_BINDING_MISMATCH`, `CONFIRMATION_STALE`, or
`CONFIRMATION_CONSUMED`
: Reload `next`. Repeat only a currently projected exact operation; never edit
  confirmation records or replay a consumed request.

`CONFIRMATION_PENDING` or `CONFIRMATION_CLAIMED`
: Pending still needs a later real prompt decision. Claimed belongs to the
  exact effect lifecycle and must be inspected/recovered rather than
  redispatched.

`EFFECT_ALREADY_CLAIMED` or `EFFECT_RECOVERY_ALREADY_CLAIMED`
: The exact execution or recovery mode already has a durable owner. Inspect the
  journal and resume only that recovery locator; do not create another request
  or redispatch.

`EFFECT_JOURNAL_INVALID`
: Recovery could not prove that the journal, current task, canonical workspace
  requests, and original confirmation describe the same execution. Stop and
  use read-only inspection; do not edit the task, journal, or confirmation
  files.

Operator intervention reason `EFFECT_SETTLEMENT_UNPROVEN`,
`EFFECT_ABSENCE_UNPROVEN`, or `EFFECT_RECOVERY_EVIDENCE_CHANGED`
: Confirmation is not effect proof. Reinspect the execution and resolve the
  real Git/evidence state before requesting a new exact recovery operation.

`CONFIRMATION_EVENT_CONFLICT`
: The same session/turn was observed with different prompt content. Inspect
  the bounded diagnostic and submit a new real user turn.

`CONFIRMATION_ACCOUNT_UNAVAILABLE`, `CONFIRMATION_STORE_INVALID`,
`CONFIRMATION_STORE_UNAVAILABLE`, `CONFIRMATION_STORE_UNSAFE`,
`CONFIRMATION_STORE_LOCK_FAILED`, `CONFIRMATION_STORE_CORRUPT`,
`CONFIRMATION_STORE_CAPACITY`, or `CONFIRMATION_STORE_WRITE_FAILED`
: Authority has failed closed. Use read-only inspection to check the exact data
  directory, local-account-only permissions, symlinks, malformed records,
  locks, filesystem capacity, and bounded ledger capacity. Do not auto-repair,
  delete, or copy records between stores.

A request remains `PENDING`
: Confirm one installed `UserPromptSubmit` Hook was picked up in a new Codex
  session and that Hook, CLI, and MCP use the same data directory. Only an
  exact later real prompt decides the request.

Codex shows a sandbox or tool-permission prompt
: That prompt belongs to the Codex host, not this plugin. Dev Flow does not
  suppress, satisfy, or auto-confirm host-owned permission prompts.

MCP tools are absent
: Confirm `dev-flow-macos` is enabled and start a new Codex session.

Multiple plugin rows
: Remove duplicate installations and reinstall only
  `dev-flow-orchestrator@personal`.

## 12. Remove

```sh
codex plugin remove dev-flow-orchestrator@personal
```

Remove the marketplace entry only if it is no longer needed. Deleting the
plugin package does not remove the external data directory. Task state,
pending/denied decisions, tombstones, and private audit evidence are preserved
by default.

Data deletion is a separate destructive operator action. Consider it only
after all active tasks and effects are resolved and confirmation/audit
retention is no longer needed. Uninstall never treats old authority records as
new confirmation evidence and never cleans either record set automatically.
