## Purpose

Define the stable typed MCP tools that map model-facing Dev Flow operations to the
existing Controller while preserving strict schemas, current bindings, domain errors,
and one-action-at-a-time workflow authority.

## ADDED Requirements

### Requirement: The MCP server exposes one closed stable tool catalog

Interface `dev-flow-mcp/1.0.0` SHALL expose exactly these tools:

1. `dev_flow_server_info`
2. `dev_flow_list_tasks`
3. `dev_flow_find_tasks_for_path`
4. `dev_flow_get_task`
5. `dev_flow_get_next_action`
6. `dev_flow_start_task`
7. `dev_flow_apply_action`
8. `dev_flow_revise_contract`
9. `dev_flow_record_decision`
10. `dev_flow_dispose_finding`
11. `dev_flow_cancel_task`

The server SHALL NOT expose a generic CLI passthrough, arbitrary command execution,
raw state read/write, generic Controller method invocation, Web UI lifecycle control,
branch/worktree management, Git publication, external CI/PR/release effects, or an
unversioned experimental tool in the stable catalog. A catalog addition, removal,
rename, or incompatible schema change SHALL require a new MCP interface version.

#### Scenario: The stable catalog is listed

- **WHEN** a client invokes `tools/list` against interface `dev-flow-mcp/1.0.0`
- **THEN** the response contains all and only the eleven approved tool names

#### Scenario: A generic command tool is proposed

- **WHEN** implementation adds a tool that accepts arbitrary CLI arguments, Python call names, shell commands, or task-state paths
- **THEN** package validation rejects the candidate as bypassing the closed Controller interface

### Requirement: Tool schemas are closed, generated, and bounded

Every tool SHALL have a generated JSON input schema with `additionalProperties:
false` at every closed object boundary. Required and optional fields SHALL be
explicit, strings and collections SHALL carry current product bounds, enums SHALL be
closed where the domain is closed, and numeric pagination SHALL have minimum and
maximum values. Tool implementations SHALL receive typed validated values rather
than reparsing JSON strings.

Every tool SHALL declare an output schema for `dev-flow-mcp-result/1.0.0`. The
adapter SHALL additionally validate each produced structured result before returning
it. Existing embedded Controller values such as delivery contracts, action payloads,
bindings, decisions, dispositions, and findings SHALL remain subject to their current
strict domain validators; wrapping them in MCP SHALL NOT weaken or duplicate those
validators. A complete structured result envelope SHALL be no larger than 512 KiB
UTF-8.

#### Scenario: An unknown input field is supplied

- **WHEN** a caller supplies an undeclared field to any stable tool
- **THEN** transport schema validation rejects the call before Controller entry

#### Scenario: A nested domain object is structurally invalid

- **WHEN** a tool receives a JSON object that passes its outer transport type but violates the current delivery-contract, action-payload, binding, decision, or disposition contract
- **THEN** the Controller or existing domain validator returns the current structured domain error and commits no partial record

#### Scenario: Adapter output violates its schema

- **WHEN** an implementation produces a result missing a required envelope or tool-specific field
- **THEN** the adapter treats it as an internal failure and does not return malformed structured success

### Requirement: Every tool returns one versioned result envelope

Every successful or domain-failed tool call SHALL return structured content with
exactly these top-level fields:

```json
{
  "schema": "dev-flow-mcp-result/1.0.0",
  "ok": true,
  "tool": "dev_flow_get_next_action",
  "request_id": "mcp-<uuid>",
  "result": {},
  "error": null
}
```

On a domain or runtime tool failure, `ok` SHALL be false, `result` SHALL be null,
`error` SHALL contain `code`, `message`, bounded `details`, and either null or a
closed `recovery` object, and the MCP tool result SHALL be marked as an error. Every
call SHALL also return one concise text content item for clients that cannot consume
structured content. Text SHALL summarize rather than duplicate the JSON structure.

#### Scenario: A read tool succeeds

- **WHEN** a valid read tool completes
- **THEN** the envelope identifies its tool and request, sets `ok: true`, validates its tool-specific result, and sets `error: null`

#### Scenario: A domain operation fails

- **WHEN** the Controller raises a current domain error
- **THEN** the envelope sets `ok: false`, retains the exact domain code, marks the tool result as an error, and includes only a bounded applicable recovery directive

#### Scenario: A client consumes text only

- **WHEN** a client ignores structured content
- **THEN** the text item states the outcome, task identity when applicable, current action or error code, and next safe operation without embedding complete bindings or snapshots

### Requirement: Server information reports capability without exposing local secrets

`dev_flow_server_info` SHALL be a stored read. It SHALL report release version,
`dev-flow-mcp` interface version, current `MODEL_VERSION`, current namespace,
official workflow IDs, supported repository-count bounds, registration mode when
known, supported transport, runtime health, and whether the current data root is
available. It SHALL NOT return the data-root path, environment values, source
checkout path, managed-runtime path, access tokens, raw dependency metadata, or task
content.

#### Scenario: Server information is requested

- **WHEN** an initialized client calls `dev_flow_server_info`
- **THEN** it can determine interface compatibility and health without learning any protected local path

#### Scenario: The data root is unavailable

- **WHEN** the current data root cannot be prepared or read
- **THEN** server information reports bounded unavailable health and the relevant domain/runtime code without inventing an empty healthy inventory

### Requirement: Task inventory reads are bounded and do not run Git

`dev_flow_list_tasks` SHALL use the current stored inventory path and SHALL NOT run
Git or create task bindings. It SHALL support stable pagination with default limit
20 and maximum limit 100, optional current/terminal status filtering, and a stable
continuation token or offset contract. Each item SHALL include only bounded task ID,
status, workflow, revision, current node, repository-count and safe repository labels,
contract summary, and updated timestamp. It SHALL NOT include the raw ledger,
complete contract, full repository snapshot, action binding, or absolute Controller
data path.

`dev_flow_get_task` SHALL return the existing bounded stored task view by task ID,
including contract, decisions, current plan/obligation summaries, timeline summary,
terminal Dossier when present, and recovery-relevant state. It SHALL not run Git
unless a future separately named live option is specified by another interface
version. Each inventory or discovery item SHALL be no larger than 2 KiB UTF-8 and a
complete inventory or discovery page SHALL be no larger than 256 KiB UTF-8.

#### Scenario: Inventory is listed while a repository is missing

- **WHEN** one task member is temporarily unavailable but stored task state is valid
- **THEN** inventory and stored task detail remain readable without Git and accurately distinguish stored state from live readiness

#### Scenario: Inventory contains an invalid entry

- **WHEN** one current-namespace candidate task entry is invalid and another is healthy
- **THEN** the read returns healthy items plus bounded inventory diagnostics and does not represent the invalid entry as terminal or unleased

#### Scenario: A page exceeds the maximum

- **WHEN** a caller requests more than 100 inventory items
- **THEN** input validation rejects the request rather than returning an unbounded result

### Requirement: Repository-path discovery returns explicit current authority

`dev_flow_find_tasks_for_path` SHALL canonicalize one caller-supplied local path
through the same host comparison rules used by admission and current discovery. It
SHALL return matching non-terminal tasks at most once each, inventory diagnostics,
and a closed classification of `none`, `single`, `ambiguous`, or
`inventory-unavailable`. It SHALL NOT start a task, select an ambiguous task, create
an action binding, or imply that an invalid task released its membership lease.

When exactly one healthy active task matches and the caller explicitly requests the
current action in the same call, the tool MAY return the same live compact action
result as `dev_flow_get_next_action`; otherwise discovery SHALL remain a stored
identity operation. The default SHALL avoid live Git capture.

#### Scenario: One active task covers a secondary repository

- **WHEN** a path is at or below any member of one healthy active task
- **THEN** discovery returns that task once regardless of member order

#### Scenario: Multiple valid tasks match

- **WHEN** persisted current state contains multiple matching active tasks
- **THEN** discovery returns `ambiguous` with all bounded task identities and selects none implicitly

#### Scenario: No current task matches

- **WHEN** the path is outside every valid active member
- **THEN** discovery returns `none` and performs no task mutation

### Requirement: Current-action reads preserve the exact action binding

`dev_flow_get_next_action` SHALL call the authoritative current Controller projection
for one explicit task ID and SHALL return `dev-flow-mcp-action/1.0.0`. The compact
MCP action SHALL include the task ID, status, revision, workflow, effective contract,
complete repository-set identity and safe member inventory, aggregate current
snapshot digest, current action ID and kind, exact payload schema, exact unmodified
action binding, retry/budget state, current obligation when present, driver contract
when present, review contract when present, bounded input and governing-resource
manifests, completion state, and action-specific guidance.

The adapter SHALL NOT synthesize, trim, normalize, reorder, or reuse a binding. It
SHALL fail with `MCP_RESULT_LIMIT` rather than truncate the binding or omit a field
required to execute the action safely. A terminal task SHALL return terminal status
and its Dossier/recovery summary without fabricating another action.
A complete `dev-flow-mcp-action/1.0.0` object SHALL be no larger than 128 KiB UTF-8.

#### Scenario: An active task is projected

- **WHEN** a caller requests the next action for a healthy active task
- **THEN** the result describes exactly one current action and supplies the exact binding required by `dev_flow_apply_action`

#### Scenario: The repository set changes during capture

- **WHEN** any member or relevant Git evidence changes between current complete capture passes
- **THEN** the tool returns the current instability error and no action binding is presented as usable

#### Scenario: The task is terminal

- **WHEN** a task is `DONE`, `INCOMPLETE`, or `CANCELLED`
- **THEN** the result reports terminal authority and no executable current action

### Requirement: Task creation maps directly to Controller admission

`dev_flow_start_task` SHALL accept a non-empty requirement, one official workflow ID
or absolute current custom workflow path, one to eight repository roots, an optional
explicit task ID, and either a complete initial `dev-flow-delivery-contract/0.4.0`
or the currently permitted minimal-contract path. It SHALL preserve caller-supplied
repository membership as an exact set subject to current canonicalization,
admission, stable two-pass capture, overlap, Git-identity, data-root separation, and
active-lease rules.

A successful result SHALL include task identity, immutable canonical membership,
revision-zero state summary, and the fresh preflight action or an explicit directive
to call `dev_flow_get_next_action`. It SHALL NOT create branches, worktrees, commits,
marketplace entries, or external delivery effects.

#### Scenario: A one-member task starts

- **WHEN** a valid requirement, official workflow, and one prepared worktree are supplied
- **THEN** the Controller creates one current task using the same repository-set model as a larger set and returns its first current action

#### Scenario: A repository set is invalid

- **WHEN** roots are missing, bare, duplicate, overlapping, share an invalid in-task Git identity, overlap the data root, or are leased by another active task
- **THEN** the entire start fails before revision-zero state is written

#### Scenario: Task creation is retried after uncertain transport completion

- **WHEN** the caller cannot determine whether a previous non-idempotent start committed
- **THEN** guidance requires discovery or explicit task-ID lookup before any retry and never treats start as safely replayable

### Requirement: Action application records exactly the projected current action

`dev_flow_apply_action` SHALL require `task_id`, exact `action_id`, one JSON object
`payload`, and the exact JSON object `binding` returned by the current action read.
It SHALL pass those values to `Controller.apply` without shell escaping or JSON string
round-tripping. It SHALL perform no model-side retry and SHALL return the mutation
receipt plus the fresh next or terminal compact action produced after the commit.

The tool SHALL remain non-idempotent. A repeated call with a consumed or stale
binding SHALL receive current Controller stale-binding or revision-conflict behavior
and SHALL NOT append the same action twice. The adapter SHALL not infer missing
payload fields, add unknown fields, or turn a failed obligation into a pass.

#### Scenario: A current action is applied

- **WHEN** action ID, payload, and binding exactly match the current Controller projection
- **THEN** one Controller record commits and the result returns the authoritative fresh projection

#### Scenario: The binding is stale

- **WHEN** task revision, contract, input, predecessor, or workspace evidence no longer matches the supplied binding
- **THEN** the call commits no record and directs the caller to `dev_flow_get_next_action`

#### Scenario: The same mutation is replayed

- **WHEN** a caller repeats a previously successful apply with the old binding
- **THEN** current Controller validation rejects it rather than treating the tool annotation or transport retry as idempotence

### Requirement: Governance tools preserve explicit task authority

`dev_flow_revise_contract` SHALL map to current contract revision with the complete
next contract, optional exact ownership claims, non-empty reason, and actor label.
`dev_flow_record_decision` SHALL accept one current decision object and preserve all
current criterion-waiver and assurance-waiver constraints. `dev_flow_dispose_finding`
SHALL accept one current disposition object and an explicit actor-authorized boolean.
`dev_flow_cancel_task` SHALL require task ID and non-empty reason and SHALL succeed
only at a workflow stage that currently declares cancellation.

Each governance mutation SHALL preserve current snapshot, binding, revision,
contract-digest, finding, actor, budget, and one-record rules. The server SHALL NOT
infer user authority from a model statement, default actor authorization to true,
or report cancellation complete until the Controller returns terminal
`CANCELLED` authority.

#### Scenario: A contract revision is accepted

- **WHEN** the complete next contract and ownership evidence satisfy the current revision boundary
- **THEN** one revision record commits, prior history remains, and the fresh MCP action reflects the new effective contract

#### Scenario: Finding disposition lacks actor authority

- **WHEN** `dev_flow_dispose_finding` is called without explicit actor authorization
- **THEN** the current forbidden error is returned and no disposition record is appended

#### Scenario: Cancellation is unavailable at the current stage

- **WHEN** the workflow does not declare cancellation from the current node
- **THEN** `dev_flow_cancel_task` returns the current workflow error and preserves the task and its leases

#### Scenario: Cancellation commits

- **WHEN** the current stage permits cancellation and the Controller returns `done: true`, `status: CANCELLED`, and `current_node: cancelled`
- **THEN** the MCP result reports terminal cancellation and only then represents the task as ended

### Requirement: Tool annotations describe but do not grant authority

Read tools SHALL declare `readOnlyHint: true`, `destructiveHint: false`,
`idempotentHint: true`, and `openWorldHint: false`. `dev_flow_start_task` and
`dev_flow_apply_action` SHALL declare non-read-only, non-idempotent, closed-world
behavior; start SHALL be non-destructive and apply SHALL be classified according to
its Controller-state effect without claiming source-file authority.
Contract revision, decision, finding disposition, and cancellation SHALL declare
non-read-only, destructive, non-idempotent, closed-world behavior. All tools SHALL
declare MCP task support forbidden.

Annotations SHALL NOT bypass Codex approval, Controller validation, actor authority,
leases, bindings, or revision CAS. Installation SHALL NOT silently grant blanket
mutation approval or rewrite unrelated user MCP policy.

#### Scenario: A host uses annotations for approval

- **WHEN** a supporting host distinguishes read tools from mutations
- **THEN** the stable annotations allow that distinction while the Controller remains the only mutation authority

#### Scenario: A caller treats idempotent metadata as a retry guarantee

- **WHEN** a non-idempotent mutation response is lost
- **THEN** documentation requires read-after-write recovery and does not authorize blind replay based on tool metadata
