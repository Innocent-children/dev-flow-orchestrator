# Install Dev Flow Orchestrator

This guide installs Dev Flow Orchestrator V6 from a local Codex marketplace,
verifies the installed launcher/Hook/Skill/controller path, and defines the V5
retention and rollback-inspection boundary.

## 1. Requirements

Supported for this release:

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

Runtime code uses only Python's standard library. Do not install a Python or
Node dependency set for this plugin. OpenSpec, codebase-memory, and an
independent reviewer are optional workflow capabilities and have explicit
fallback behavior.

## 2. Put the source in a personal marketplace

These examples use `$HOME/plugins/dev-flow-orchestrator` as the marketplace
source:

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

A reviewed local candidate may be placed at the same path. Keep it as one
complete candidate tree so package identity, workflows, Skills, Hook, source,
and documentation come from the same snapshot.

Validate the candidate:

```sh
cd "$HOME/plugins/dev-flow-orchestrator"
python3 -I -S scripts/validate_package.py
python3 -m json.tool .codex-plugin/plugin.json
```

The manifest name is `dev-flow-orchestrator`, and candidate validation covers
the catalog entries for `lite`, `feature`, `bugfix`, `investigation`,
`refactor`, and `full`.

For a new personal marketplace:

```sh
mkdir -p "$HOME/.agents/plugins"
cp \
  "$HOME/plugins/dev-flow-orchestrator/templates/personal-marketplace.example.json" \
  "$HOME/.agents/plugins/marketplace.json"
```

If `~/.agents/plugins/marketplace.json` already exists, preserve it and merge
the object from `templates/marketplace-entry.json` into its `plugins` array.
Keep exactly one entry named `dev-flow-orchestrator`.

```sh
python3 -m json.tool "$HOME/.agents/plugins/marketplace.json"
```

## 3. Install V6

```sh
codex plugin list
codex plugin add dev-flow-orchestrator@personal
codex plugin list
```

The result contains exactly one enabled `dev-flow-orchestrator@personal`.

Start a new Codex task. Open `/hooks`, confirm that the Hook source is the
installed plugin snapshot, review the current definition, and trust it. Verify
that `SessionStart`, `UserPromptSubmit`, and `PreToolUse` are enabled. A
source-checkout test cannot establish installed Hook or Skill pickup.

## 4. Replace or upgrade an installation

Codex installs an immutable cached snapshot. A replacement candidate therefore
uses a new cachebuster version even though the plugin identity remains
`dev-flow-orchestrator`.

1. Obtain the complete reviewed candidate.
2. If V5 tasks matter, retain the exact V5 package snapshot and its locator as
   described in [V5 retention](#5-v5-retention-and-rollback-inspection).
3. Replace the marketplace source tree as one candidate.
4. Remove the installed snapshot:

   ```sh
   codex plugin remove dev-flow-orchestrator@personal
   ```

5. Install the candidate:

   ```sh
   codex plugin add dev-flow-orchestrator@personal
   ```

6. Start a new Codex task and verify the installed version and Hook source.

Active V5 work is completed or cancelled with the V5 installation before
normal V6 use. V6 starts new state in its own namespace and does not migrate a
V5 task.

## 5. V5 retention and rollback inspection

The installed Hook derives the controller state directory from Codex's
`PLUGIN_DATA` base:

```text
<PLUGIN_DATA>/
├── v5/                 # retained V5 tasks
│   ├── tasks/
│   └── locks/
└── v6/                 # current V6 tasks
    ├── tasks/
    └── locks/
```

V6 reads and writes only `<PLUGIN_DATA>/v6`. It never reads, copies, mutates,
or deletes `<PLUGIN_DATA>/v5`. Preserve the V5 directory and an immutable copy
or recorded installed path for the exact V5 package snapshot if later V5
inspection is required.

To inspect or resume a retained V5 task:

1. Finish or pause interaction with V6 tasks and record the exact current V6
   installed snapshot/version.
2. Remove the V6 installation under the shared plugin identity.
3. Point the personal marketplace entry at the retained V5 package snapshot
   and install `dev-flow-orchestrator@personal`.
4. Start a new Codex task, confirm `/hooks` comes from that V5 snapshot, and
   use its injected locator. The locator must name `<PLUGIN_DATA>/v5`.
5. Run the V5 locator's `list`, `show`, or `next` operation for the retained
   V5 task. Never point the V6 controller at `v5`, or the V5 controller at
   `v6`.
6. Remove V5, restore the marketplace entry to the recorded V6 candidate,
   reinstall V6, and confirm a new task injects `<PLUGIN_DATA>/v6`.

Rollback inspection changes the installed executable snapshot, not the task
data. The retained V5 task remains subject to V5's own workflow identity and
package availability. If the exact V5 package was not retained, V6 provides no
automatic V5 reader or migration path.

## 6. Data directory and controller locator

Task state must remain outside every target repository. The Hook injects one
complete locator containing the installed Python launcher, installed CLI, and
exact `<PLUGIN_DATA>/v6` state directory:

```text
<ctl> = <exact Hook-injected locator>
```

Use that locator unchanged for installed tasks. Do not reconstruct its paths or
append another `--data-dir`.

For a separate direct-CLI smoke, choose an explicit data directory outside the
target repository. Here `--data-dir` means the exact directory and does not
append `v6`:

```sh
SOURCE_ROOT="$HOME/plugins/dev-flow-orchestrator"
DATA_DIR="/absolute/path/to/independent-dev-flow-v6-state"

"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" --help
```

Use the same exact directory for every command on that task. The controller
uses private directories/files, a task lock, revision compare-and-swap,
deterministic replay, and atomic replacement. Direct state edits, symlinked
state paths, malformed records, and data/repository tree overlap fail closed.

## 7. Verify the V6 CLI contract

Create a task in a disposable initialized Git repository:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --repo /absolute/path/to/disposable-repository \
  --requirement "Installation smoke"
```

The response contains revision-zero task state with a minimal contract. Save
its `task_id`, then request the projection:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" next <task-id>
```

The first V6 action is `task.preflight`. Every `apply`, including preflight,
requires the exact object returned as `projection.action.binding`. Copy the
fresh binding as strict JSON; do not reconstruct or reuse it:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action task.preflight \
  --payload-json '{}' \
  --binding-json '<projection.action.binding JSON>'
```

Use the fresh projection returned by each apply for the next action:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action implementation.record \
  --payload-json '{"summary":"installation smoke implementation"}' \
  --binding-json '<fresh implementation binding JSON>'
```

Run the command that proves the smoke requirement. Record `passed: true` only
after it exits successfully. The minimal contract criterion ID is
`requirement`:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action verification.record \
  --payload-json '{"passed":true,"command":"git -C /absolute/path/to/disposable-repository status --short","coverage":{"requirement":"proven"},"summary":"command exited successfully"}' \
  --binding-json '<fresh verification binding JSON>'
```

Finalize from its fresh projection:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --action delivery.finalize.success \
  --payload-json '{"summary":"installation smoke completed","remaining_risks":{},"handoff":"inspect the generated dossier"}' \
  --binding-json '<fresh finalization binding JSON>'
```

The final projection reports `done: true`, status `DONE`, and a compact
dossier summary. Inspect the full ledger and dossier artifact:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" show <task-id>
```

## 8. Start with an explicit contract

Normal `feature`, `bugfix`, `investigation`, `refactor`, and `full` tasks use a
structured initial contract:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" start \
  --workflow feature \
  --repo /absolute/path/to/repository \
  --requirement "Deliver observable behavior" \
  --contract-json '{"schema":"dev-flow-delivery-contract/v1","revision":1,"summary":"Deliver observable behavior","acceptance_criteria":[{"id":"C1","statement":"The behavior is observable"}],"scope":["implementation and focused verification"],"constraints":[],"risks":[],"non_goals":[],"open_questions":[]}'
```

The object has exactly the documented fields, positive revision `1`, at least
one uniquely identified criterion, and bounded text/list content. Omitting the
object uses the requirement-derived minimal contract.

## 9. Revise scope or record a waiver

Contract revision is available after preflight. Supply the complete next
contract revision, reason, and actor label:

```sh
<ctl> revise-contract <task-id> \
  --contract-json '{"schema":"dev-flow-delivery-contract/v1","revision":2,"summary":"Revised scope","acceptance_criteria":[{"id":"C1","statement":"Revised observable condition"}],"scope":["revised work"],"constraints":[],"risks":[],"non_goals":[],"open_questions":[]}' \
  --reason 'accepted scope correction' \
  --actor-label 'operator'
```

The controller captures one `revision-source` snapshot for the new contract
and reenters the workflow's declared impact or implementation node.

Record a criterion waiver only as an explicit decision:

```sh
<ctl> decide <task-id> \
  --decision-json '{"id":"waive-C1-r1","kind":"criterion-waiver","subject":"C1","outcome":"waived","rationale":"accepted bounded exception","actor_label":"operator"}'
```

For unavailable independent review, `kind` is `assurance-waiver`, `subject` is
the exact review node ID (official workflows use `review`), and `outcome` is
`waived`. Decision IDs are unique for the task, and a `(kind, subject)` pair is
accepted once per contract digest. A later contract revision makes earlier
waivers historical.

Cancel only on explicit user instruction:

```sh
<ctl> cancel <task-id> --reason 'operator requested cancellation'
```

## 10. Verify installed Hook and Skill pickup

1. Start a new Codex task inside a disposable initialized repository.
2. Open `/hooks`; confirm the source is the installed immutable snapshot and
   trust the definition.
3. Invoke `$follow-dev-flow` and start an official workflow.
4. Confirm the injected context names Dev Flow V6, includes the installed
   launcher and CLI, selects `<PLUGIN_DATA>/v6`, and projects
   `dev-flow-agent-v2`.
5. Confirm `$follow-dev-flow` passes the exact current action binding on every
   apply and inspects the terminal dossier with `show`.
6. Confirm common shell/edit attempts that target the plugin data root are
   denied while normal repository work remains available.

Installed release evidence covers all six official workflows and records the
installed snapshot identity, task IDs, repository baselines, optional-driver
status, verification/review paths, contract-revision recovery, bounded
exhaustion, dossier outcomes, and retained V5 inspection. Any condition that
depends on a real new Codex task loading a Hook or Skill remains a manual
installed pickup check when the validation environment cannot observe it.

The bundled `scripts/validate_installed_stage1.py` runner labels its generated
driver payloads as controller-contract simulations. A verified release gate
combines that installed controller evidence with `--external-evidence` captured
from actual OpenSpec, codebase-memory, independent-review, and retained V5
`list`/`show` executions. Running the controller matrix alone reports
`execution_ok: true` and keeps the release gate `unverified`.

## 11. Troubleshooting

`Python handler does not exist`
: The marketplace source or installed snapshot is incomplete. Confirm that
  `scripts/dev_flow.py` and `scripts/dev_flow_python_launcher` exist together.

`Python 3.9-3.14 was not found`
: Install a supported Python or set `DEV_FLOW_PYTHON` to a verified absolute
  interpreter path.

`ARGUMENT_INVALID` mentioning `--data-dir`
: Place the required global `--data-dir` before the subcommand. Installed
  tasks use the complete Hook locator.

`ACTION_BINDING_INVALID` or `ACTION_BINDING_STALE`
: Obtain a fresh `next` projection and submit its complete binding. Never
  synthesize, trim, or reuse a binding.

`REVISION_CONFLICT`
: Another mutation advanced the task. Read `error.details.projection`, then
  run `next` and reassess the newly projected action.

`WORKSPACE_CHANGED`
: A context or verifying action observed a different worktree than its bound
  starting snapshot. Restore the intended snapshot or obtain a fresh action;
  source changes belong only to a declared source-producing action.

`ARTIFACT_INPUT_MISSING` or `RESOURCE_BINDING_MISSING`
: A required current artifact or declared repository resource cannot be
  resolved. Inspect `show`, freshness reasons, and current resource paths;
  produce a replacement upstream artifact when required.

`DELIVERY_NOT_READY`
: Successful finalization lacks fresh passing verification, complete coverage,
  or the required independent review/waiver. Follow the projected rework or
  decision path.

`WORKFLOW_IDENTITY_MISMATCH`
: The selected workflow or adapter differs from the task's pinned identity.
  Restore the exact definition used at task creation or start a new task.

`STATE_INVALID`
: Stored V6 state failed schema, seal, identity, ledger, or replay validation.
  Preserve it for diagnosis and do not edit it. Also confirm that a direct CLI
  was not pointed at the V5 namespace.

Codex shows a sandbox or permission prompt
: This is host-owned authority. The controller neither suppresses nor
  auto-confirms host permission prompts.

Multiple plugin rows
: Remove duplicate installations and install exactly one
  `dev-flow-orchestrator@personal`.

## 12. Remove

```sh
codex plugin remove dev-flow-orchestrator@personal
```

Removing the plugin does not remove external task data. Marketplace-entry and
data deletion are separate operator actions. Preserve active or retained V5/V6
tasks unless the exact deletion scope is intentional and recoverability has
been assessed.
