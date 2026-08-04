# Install Dev Flow Orchestrator

Dev Flow 0.3.0 is a clean protocol cut. Configure the installed controller with
the exact `<PLUGIN_DATA>/0.3.0` directory. Retained `<PLUGIN_DATA>/0.2.0` bytes
may remain for operator reference, but the 0.3 runtime does not discover, load,
migrate, repair, or mutate them. Explicit 0.2 schemas or state are unsupported.

Prepare every Git worktree yourself before starting a task. Admission creates
one active lease for each canonical root and worktree-specific Git directory;
distinct linked worktrees may share a common Git directory across distinct
tasks. During source actions, submit exact `dev-flow-task-change-claims/0.3.0`.
During `assurance.execute`, follow only `current_obligation` and its evidence
contract. Do not reconstruct bindings, plan IDs, findings, counters, or review
outcomes.

[简体中文](INSTALL_CN.md)

This guide installs Dev Flow Orchestrator 0.3.0 from a local Codex marketplace and
verifies the installed launcher, Hook, Skill, and controller path.

The installed 0.3.0 core runs one local task over an exact canonical set of one to
eight user-prepared Git worktrees. It always projects one current action to one
Codex executor. It does not create or switch branches/worktrees,
publish Git changes, coordinate parallel agents, call external CI/PR/release
systems, or reuse partial assurance from unchanged repository members.

## Quick install

On a supported macOS host, install from the public repository with one command:

```sh
curl -fsSL https://raw.githubusercontent.com/Innocent-children/dev-flow-orchestrator/main/scripts/install.sh | sh
```

The script checks macOS, Git, Python 3.9–3.14, and the Codex CLI; clones or
fast-forwards `$HOME/plugins/dev-flow-orchestrator`; validates the complete
candidate; preserves other personal marketplace entries while replacing any
Dev Flow entry; installs the plugin; and prints the first prompt. Review
[`scripts/install.sh`](scripts/install.sh) before running it if you do not want
to pipe a remote script directly to `sh`.

The installer treats `main` as its non-configurable authoritative source ref.
A fresh install selects `main` explicitly. An existing source proceeds only
when its origin matches the configured repository URL, its attached branch is
clean `main`, and its current commit is equal to or can fast-forward to the
fetched `main` commit. The fast-forward refuses to overwrite an ignored local
path that collides with incoming `main`, but preserves unrelated ignored
content. It refuses another branch, detached HEAD, reported local changes,
local-ahead history, divergence, or a non-Git path without switching,
resetting, stashing, cleaning, or overwriting the checkout.

If the plugin is already installed, finish or explicitly cancel active tasks,
then follow the replacement steps below. The remaining sections document the
same process manually and provide the full installed acceptance checks.

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
git clone --branch main --single-branch \
  git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

HTTPS alternative:

```sh
mkdir -p "$HOME/plugins"
git clone --branch main --single-branch \
  https://github.com/Innocent-children/dev-flow-orchestrator.git \
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

## 3. Install 0.3.0

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

## 4. Replace an installation

Codex installs an immutable cached snapshot. The package, runtime protocols,
and product documentation therefore carry the same declared product version;
this source currently uses `0.3.0` without a separate cache-only version.

1. Obtain the complete reviewed candidate.
2. Replace the marketplace source tree as one candidate.
3. Remove the installed snapshot:

   ```sh
   codex plugin remove dev-flow-orchestrator@personal
   ```

4. Install the candidate:

   ```sh
   codex plugin add dev-flow-orchestrator@personal
   ```

5. Start a new Codex task and verify the installed version and Hook source.

Replacement installs operate on the current 0.3.0 product model and state
namespace. Finish or explicitly cancel active tasks before replacing the
installed snapshot.

## 5. Data directory and controller locator

Task state must remain outside every target repository in the task. The Hook
injects one complete locator containing the installed Python launcher,
installed CLI, and exact `<PLUGIN_DATA>/0.3.0` state directory:

```text
<ctl> = <exact Hook-injected locator>
```

Use that locator unchanged for installed tasks. Do not reconstruct its paths or
append another `--data-dir`.

For a separate direct-CLI smoke, choose an explicit data directory outside the
target repository. Here `--data-dir` means the exact directory and does not
append `0.3.0`:

```sh
SOURCE_ROOT="$HOME/plugins/dev-flow-orchestrator"
DATA_DIR="/absolute/path/to/independent-dev-flow-0.3.0-state"

"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" --help
```

Use the same exact directory for every command on that task. The controller
uses private directories/files, a task lock, revision compare-and-swap,
deterministic replay, and atomic replacement. Direct state edits, symlinked
state paths, malformed records, and data/repository tree overlap fail closed.

## 6. Verify the 0.3.0 CLI contract

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

The first 0.3.0 action is `task.preflight`. Every `apply`, including preflight,
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
  --payload-json '{"passed":true,"command":"git -C /absolute/path/to/disposable-repository status --short","coverage":{"schema":"dev-flow-verification-coverage/0.3.0","criteria":{"requirement":"proven"},"repositories":{"<repository-id>":{"command":"git -C /absolute/path/to/disposable-repository status --short","passed":true}},"integration":{"command":"git -C /absolute/path/to/disposable-repository status --short","passed":true}},"summary":"member and integration checks passed"}' \
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

The one-argument `--repo` path above creates a one-member exact repository set.
It uses `dev-flow-agent/0.3.0`, an aggregate repository-set snapshot,
`dev-flow-verification-coverage/0.3.0`, scoped resources, and
`dev-flow-delivery-dossier/0.3.0`, exactly like every larger set.

To smoke-test a larger set, prepare two to eight initialized,
non-bare local Git worktree roots and repeat `--repo`:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --repo /absolute/path/to/disposable-api \
  --repo /absolute/path/to/disposable-client \
  --requirement "Repository-set installation smoke"
```

Admission canonicalizes and sorts the exact set and rejects duplicate or
overlapping roots, shared Git common directories, non-worktree roots, and
data-directory overlap. Caller order has no meaning, and membership is
immutable after start. Save the returned member IDs. The
`dev-flow-agent/0.3.0` projection's `repository_set` carries the aggregate
snapshot digest, and every apply still uses its single fresh action binding.

At `verification.record`, cover the exact criterion and member sets plus one
integration result. The top-level command must equal `integration.command`,
and top-level `passed` must equal the conjunction of every member and
integration result:

```sh
<ctl> apply <task-id> \
  --action verification.record \
  --payload-json '{"passed":true,"command":"./verify-integration.sh","coverage":{"schema":"dev-flow-verification-coverage/0.3.0","criteria":{"requirement":"proven"},"repositories":{"<api-repository-id>":{"command":"./verify-api.sh","passed":true},"<client-repository-id>":{"command":"./verify-client.sh","passed":true}},"integration":{"command":"./verify-integration.sh","passed":true}},"summary":"all member and integration checks passed"}' \
  --binding-json '<fresh verification binding JSON>'
```

Finalization produces one aggregate `dev-flow-delivery-dossier/0.3.0`. It includes
the canonical inventory, per-member baseline/final summaries, changed-member
diagnostics, scoped resources, verification attempts, current
member/integration proof, and aggregate freshness. Before the task reaches a
terminal state, a change to any
member invalidates the current aggregate binding and assurance; obtain a fresh
action and rerun the required assurance for the complete set. After the task
is terminal, it does not reopen: later member drift only makes the existing
Dossier stale, and further delivery work requires a new task.

## 7. Start with an explicit contract

Normal `feature`, `bugfix`, `investigation`, `refactor`, and `full` tasks use a
structured initial contract:

```sh
"$SOURCE_ROOT/scripts/dev_flow_python_launcher" \
  "$SOURCE_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" start \
  --workflow feature \
  --repo /absolute/path/to/repository \
  --requirement "Deliver observable behavior" \
  --contract-json '{"schema":"dev-flow-delivery-contract/0.3.0","revision":1,"summary":"Deliver observable behavior","acceptance_criteria":[{"id":"C1","statement":"The behavior is observable"}],"scope":["implementation and focused verification"],"constraints":[],"risks":[],"non_goals":[],"open_questions":[]}'
```

The object has exactly the documented fields, positive revision `1`, at least
one uniquely identified criterion, and bounded text/list content. Omitting the
object uses the requirement-derived minimal contract. Repeat `--repo` on this
command to bind the same explicit contract to a larger exact repository set;
workflow choice does not imply repository count.

When a planning action declares repository-backed resources, every item has
exactly its returned `repository_id`, relative `path`, `role`, and
`normalizer`. Unknown or omitted IDs, escaping paths, cross-root resolution,
and duplicate scoped keys are rejected.

## 8. Revise scope or record a waiver

Contract revision is available after preflight. Supply the complete next
contract revision, reason, and actor label:

```sh
<ctl> revise-contract <task-id> \
  --contract-json '{"schema":"dev-flow-delivery-contract/0.3.0","revision":2,"summary":"Revised scope","acceptance_criteria":[{"id":"C1","statement":"Revised observable condition"}],"scope":["revised work"],"constraints":[],"risks":[],"non_goals":[],"open_questions":[]}' \
  --reason 'accepted scope correction' \
  --actor-label 'operator'
```

The controller captures one aggregate `revision-source` snapshot covering
every member for the new contract and reenters the workflow's declared impact
or implementation node. Revision cannot change repository membership.

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

Cancel only on explicit user instruction and only when the current node is in
the selected workflow's `cancel.stages` declaration:

```sh
<ctl> cancel <task-id> --reason 'operator requested cancellation'
```

The six official workflows declare cancellation at a strict majority of their
normal nonterminal stages. Delivery finalizers never expose cancellation.

### Recover a task started with the wrong repository set

A Hook match proves only that the current path belongs to an active task's
declared repository set. It does not prove that the repositories can satisfy
the accepted requirement. When `$follow-dev-flow` confirms a semantic mismatch
from the effective contract and source, it must:

1. stop the projected workflow action without changing a member;
2. identify the exact task and mismatch, state that the task remains active,
   and request explicit cancellation authority unless the current request
   already supplies it for that task;
3. after authorization, call `<ctl> cancel` for the exact task; and
4. report completion only after the projection contains `done: true`,
   `status: CANCELLED`, and `current_node: cancelled`.

Without authorization, or when cancellation is unavailable or cannot capture
the complete repository set, the task remains active. Restore the declared
member, complete a required finalizer, or take the reported operator action;
do not replace immutable membership or start an implicit replacement task.

## 9. Verify installed Hook and Skill pickup

1. Start a new Codex task inside any member of a disposable initialized
   exact repository set, including a secondary member in a larger set. An
   ambiguous active-task match is not selected.
2. Open `/hooks`; confirm the source is the installed immutable snapshot and
   trust the definition.
3. Invoke `$follow-dev-flow` and start an official workflow.
4. Confirm the injected context names Dev Flow 0.3.0, includes the installed
   launcher and CLI, selects `<PLUGIN_DATA>/0.3.0`, and projects
   `dev-flow-agent/0.3.0` with the exact `repository_set` for every cardinality.
5. Confirm `$follow-dev-flow` passes the exact current action binding on every
   apply and inspects the terminal dossier with `show`.
6. Confirm common shell/edit attempts that target the plugin data root are
   denied while normal repository work remains available.

Installed release evidence covers all six official workflows and records the
installed snapshot identity, task IDs, repository baselines, optional-driver
status, verification/review paths, contract-revision recovery, bounded
exhaustion, and Dossier 0.3.0 outcomes. Any condition that depends on a real new
Codex task loading a Hook or Skill remains a manual
installed pickup check when the validation environment cannot observe it.

The bundled `scripts/validate_installed_stage1.py` runner labels its generated
driver payloads as controller-contract simulations. A verified release gate
combines that installed controller evidence with `--external-evidence` captured
from actual OpenSpec, codebase-memory, and independent-review executions.
Running the controller matrix alone reports
`execution_ok: true` and keeps the release gate `unverified`.

## 10. Troubleshooting

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
  starting aggregate snapshot. Restore the intended snapshot or
  obtain a fresh action; source changes belong only to a declared
  source-producing action.

`REPOSITORY_IDENTITY_MISMATCH`, `REPOSITORY_INVALID`,
`REPOSITORY_GIT_IDENTITY_DUPLICATE`, or `REPOSITORY_OVERLAP`
: A persisted member is missing or moved, no longer its exact canonical Git
  worktree root, or now conflicts with another member. Repository-dependent
  progress records no partial evidence. Restore every member at its exact
  persisted root, resolve the identity conflict, and request a fresh
  projection. Use `show` for read-only stored-ledger diagnosis.

`ARTIFACT_INPUT_MISSING` or `RESOURCE_BINDING_MISSING`
: A required current artifact or declared repository resource cannot be
  resolved. Inspect `show`, freshness reasons, and current resource paths;
  produce a replacement upstream artifact when required.

`DELIVERY_NOT_READY`
: Successful finalization lacks fresh passing verification, complete coverage,
  or the required independent review/waiver. Follow the projected rework or
  decision path.

`WORKFLOW_IDENTITY_MISMATCH`
: The selected workflow schema, selector, or canonical definition differs from
  the task's pinned identity. Restore the exact definition used at task
  creation or start a new task.

`STATE_INVALID`
: Stored 0.3.0 state failed schema, seal, identity, ledger, or replay validation.
  Preserve it for diagnosis and do not edit it. Confirm that every command
  used the task's exact controller locator and data directory.

Codex shows a sandbox or permission prompt
: This is host-owned authority. The controller neither suppresses nor
  auto-confirms host permission prompts.

Multiple plugin rows
: Remove duplicate installations and install exactly one
  `dev-flow-orchestrator@personal`.

## 11. Remove

```sh
codex plugin remove dev-flow-orchestrator@personal
```

Removing the plugin does not remove external task data. Marketplace-entry and
data deletion are separate operator actions. Preserve active 0.3.0 tasks unless
the exact deletion scope is intentional and recoverability has been assessed.
