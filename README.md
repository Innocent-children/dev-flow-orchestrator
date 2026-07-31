# Dev Flow Orchestrator

[中文](README.zh-CN.md) · [Install](INSTALL.md) · [Architecture](ARCHITECTURE.md) ·
[Contributing](CONTRIBUTING.md)

Dev Flow Orchestrator is a macOS Codex plugin for explicit, resumable software
work. It has one plugin identity, one V4 runtime, and one controller that owns
all task-state transitions.

The runtime was designed as a small greenfield core:

- task state is schema v4 and stays outside target repositories;
- workflow depth, repository topology, and workspace strategy are independent;
- both `full@4` and `lite@4` support one or multiple repositories;
- every node declares its action, authority, write set, effect, failure, and
  recovery behavior;
- CLI, MCP, Hook, and Skills are thin adapters over the same controller;
- runtime Python code uses only the standard library.

This release is validated only on the current macOS host. It does not claim
native Windows or Linux support.

## The four paths

Repository count never upgrades `lite@4` to `full@4`.

| Workflow | Topology | Path |
|---|---|---|
| `full@4` | single repository | preflight → baseline → impact → route → workspace → planning → plan approval → implement → verify → review → finalize |
| `full@4` | multiple repositories | full-only gates → shared repository plan/lease/result/barrier/integration → implement → verify → review → finalize |
| `lite@4` | single repository | preflight → implement → verify |
| `lite@4` | multiple repositories | preflight → shared repository plan/lease/result/barrier/integration → implement → verify |

`in-place`, `branch`, and `worktree` are explicit workspace strategies. They do
not select the workflow. Lite has no workflow-entry approval. A shared
repository action can still require the same exact confirmation as Full when
its own node contract declares additional authority.

## Scope model

There is no global include-directory, exclude-directory, or allowlist
configuration. A task's scope is the exact set of repository paths supplied by
repeatable `--repo` arguments. The Hook finds current tasks by those repository
and prepared-workspace roots.

## Requirements

- macOS;
- Git;
- Python 3.9–3.14;
- Codex with plugin and `UserPromptSubmit` Hook support.

No `pip`, `npm`, or other runtime dependency installation is required.

## Install

Follow [INSTALL.md](INSTALL.md) for the complete source placement, personal
marketplace, replacement, Hook, optional MCP, and acceptance procedure.

The common install flow is:

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"

mkdir -p "$HOME/.agents/plugins"
cp \
  "$HOME/plugins/dev-flow-orchestrator/templates/personal-marketplace.example.json" \
  "$HOME/.agents/plugins/marketplace.json"

codex plugin add dev-flow-orchestrator@personal
codex plugin list
```

If the marketplace file already exists, merge
`templates/marketplace-entry.json` into its `plugins` array instead of
overwriting the file. The default personal marketplace is discovered
automatically. Keep exactly one installed plugin with this identity.

An installed popup-era candidate can remain cached after its source is
replaced. Upgrade it through the atomic cachebuster/remove/reinstall procedure
in [INSTALL.md](INSTALL.md), then start a new Codex session. The cutover does
not migrate old authority records into conversation confirmation evidence.
Uninstall removes the package but preserves its external task, confirmation,
and audit data by default.

## Use from Codex

The public Skill is `follow-dev-flow`:

```text
Use $follow-dev-flow to start this requirement with lite@4 in these repositories:
/path/to/service
/path/to/client

Requirement:
<text>
```

```text
Use $follow-dev-flow to resume task <task-id>.
```

Supporting Skills:

- `analyze-change-impact` performs read-only, source-confirmed impact analysis;
- `review-dev-flow-change` performs a fresh read-only implementation review.

The Skill uses the exact CLI locator injected by the Hook, or the current MCP
tools when MCP is enabled. The two transports are independent.

## CLI

Use one explicit data directory for all commands belonging to the same task:

```sh
PLUGIN_ROOT=/path/to/dev-flow-orchestrator
DATA_DIR="$HOME/Library/Application Support/dev-flow-orchestrator"

"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" --help
```

The data directory must not be inside a target repository.

### Create a task

Single-repository `lite@4`:

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --workspace-strategy in-place \
  --repo /path/to/project \
  --requirement "Update the bounded feature"
```

Multi-repository `lite@4`:

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" \
  start \
  --workflow lite \
  --workspace-strategy branch \
  --repo /path/to/service \
  --repo /path/to/client \
  --requirement "Update the shared contract and both consumers"
```

Use `--workflow full` for the full path. `--task-id` is optional; otherwise the
controller creates one.

### Read and advance

```sh
# Full state
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" show <task-id>

# Compact agent-v1 projection
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" next <task-id> \
  --session-id <hook-injected-session-id>

# Preflight Git evidence at revision 0
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" preflight <task-id> --expected-revision 0

# Apply the exact current action
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" apply <task-id> \
  --expected-revision <revision> \
  --action <action-id> \
  --payload-json '{"field":"value"}' \
  --session-id <hook-injected-session-id>
```

### Durable conversation confirmation

If `next` reports `required_authority` as `task-revision+<grant>`, the first
exact `apply` validates the current task, revision, action, payload, role and
scope, then creates or reloads a private durable confirmation request. It
returns `PENDING` without changing workflow state, running Git, or dispatching
an external effect. The request has no clock timeout.

The agent must show the bounded request, ask for an exact chat reply, and end
the turn. A later `UserPromptSubmit` event accepts:

- bare `同意` or `approve` only when one request is unambiguous in the current
  session and repository context;
- `同意 <request-id>` or `approve <request-id>` for an exact displayed request;
- `拒绝` / `deny` and their request-ID forms under the same ambiguity rules.

Additional prose does not decide a request. The Hook only records the
conversation decision; it never applies an action. On the next turn the agent
reloads `next`. Only a still-current `CONFIRMED` request permits one exact retry
of the same revision, action, payload, and scope. Pending or ambiguous requests
wait, and denial is terminal for that exact binding. Do not poll, auto-confirm,
retry while pending, fabricate a reply, or invoke the Hook manually.

There is no public confirmation/authority issuer, caller approval boolean,
caller `--actor`, raw-prompt input, or serialized record. `session_id`,
`turn_id`, local account, and controller-derived cwd/eligible-task and prompt
digests are correlation and audit evidence from the configured Codex
conversation channel. Raw cwd and prompt text are not retained. This evidence
is not independent operating-system or authenticated-human identity proof.
`--session-id` and optional `--request-turn-id` only route the request; they do
not grant authority and must not be invented.

Always reload `next` after a successful mutation, lost response, or revision
conflict. Do not edit persisted task or confirmation JSON.

### Multi-repository execution

Full reaches the shared repository kernel after its full-only gates. Lite
multi-repository enters it directly after preflight. Both use the same shared
nodes:

1. `repository.plan.record` records the exact repository ID set,
   controller-derived owner, pinned Git HEADs, dependency DAG,
   concurrency, and retry limit;
2. `repository.lease.issue` creates ready, bounded leases bound to one owner
   and pinned HEAD;
3. `repository.result.accept` binds a `PASS` or `FAIL` result digest to one
   repository lease and attempt;
4. `repository.barrier.close` closes only after every repository passes;
5. `repository.integration.record` binds the integrated result;
6. `repository.cancel` revokes active leases when explicitly requested.

Repository IDs are available in `show`. Ordering and CAS are controller-owned.

### Effect recovery

Workspace Git effects use a durable journal:

```sh
"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" effect-inspect <task-id>

"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" \
  "$PLUGIN_ROOT/scripts/dev_flow.py" \
  --data-dir "$DATA_DIR" effect-recover <task-id> \
  --execution-id <sha256> \
  --mode <settle|abandon|reattach|compensate> \
  --session-id <hook-injected-session-id>
```

Recovery validates the execution, journal binding, evidence, and selected mode
before creating a confirmation request and binds the resulting evidence digest
to that request. An actionable mode uses the same durable request, later prompt
decision, fresh projection, and exact-retry lifecycle as `apply`. The retry
reloads and proves the outcome again under the same per-execution fence used by
live dispatch. Changed or unavailable proof returns bounded operator
intervention and cannot settle or abandon the effect. When reattach or
compensation is unavailable, the controller returns that intervention before
asking for confirmation. Conversation agreement never proves effect absence,
settlement, receipt validity, reattachment, or compensation, and recovery
never guesses an outcome or redispatches an uncertain effect.

## Codex integration

### Hook

The packaged Hook injects the exact controller/data-directory locator and the
current `agent-v1` projection for in-scope tasks. It labels injected
`conversation_routing={session_id,request_turn_id}` as correlation-only, not
authority. On `UserPromptSubmit` it forwards bounded `session_id`, `turn_id`,
`cwd`, and exact prompt evidence to the controller's confirmation observer.
The controller derives the eligible active-task set from canonical cwd; the
Hook then injects the refreshed projection. The Hook never selects or applies
an action, dispatches an effect, or writes task state. Malformed events and
internal Hook errors fail open while the guarded operation stays unapplied.

### MCP

The optional `dev-flow-macos` MCP server is disabled by default. When enabled,
it exposes exactly:

- `task-start`
- `task-show`
- `task-next`
- `task-preflight`
- `action-apply`
- `effect-inspect`
- `effect-recover`

All mutating tools call the same controller methods as CLI.

## Architecture

```text
src/dev_flow_orchestrator/
  product.py             one four-profile product matrix
  model.py               immutable schema-v4 values
  workflow.py            full, lite, and shared repository node contracts
  repository_kernel.py   pure DAG/lease/result/barrier logic
  engine.py              pure eligibility and mutation planning
  authority.py           durable conversation confirmation evidence
  controller.py          sole state writer and effect coordinator
  store.py               private lock/CAS/atomic persistence
  journal.py             durable effect outcomes and recovery
  git_client.py          bounded Git reads and workspace effects
  cli.py                 JSON CLI adapter
  mcp.py                 stdio MCP adapter
  hook.py                advisory fail-open Hook

scripts/                 fixed public bootstraps and validators
skills/                  public workflow and read-only guidance
hooks/hooks.json         Codex Hook registration
.mcp.json                optional macOS MCP registration
```

The direct Python modules are the complete runtime and workflow definition.

## Safety boundaries

- state is private and outside target repositories;
- every mutation uses revision CAS and atomic replace;
- external effects use plan → dispatch → receipt → commit;
- uncertain effects are quarantined and single-dispatch;
- Git subprocesses use argument vectors and bounded output;
- the Hook is advisory and cannot write task state;
- confirmation data is local-account-private and outside repositories;
- unsafe permissions, symlinks, corruption, lock/write failure, or capacity
  exhaustion fail closed for guarded authority without automatic repair;
- Codex host-owned sandbox, filesystem, and tool-permission prompts are a
  separate boundary and are not suppressed or auto-confirmed by this plugin;
- no automatic stash, reset, clean, commit, push, rebase, merge, or force-push
  behavior is provided.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Full test discovery is prohibited for
this repository; run only focused modules that cover the changed behavior.

## License

See [LICENSE](LICENSE).
