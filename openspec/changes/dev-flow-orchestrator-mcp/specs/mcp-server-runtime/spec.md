## Purpose

Define the local MCP process, protocol, lifecycle, dependency, concurrency, logging,
and compatibility boundary that exposes the existing Dev Flow Controller without
creating a second workflow runtime or persisted authority.

## ADDED Requirements

### Requirement: The product provides one local STDIO MCP server

The product SHALL provide a local executable MCP server named `dev-flow-mcp` whose
stable Dev Flow interface identity is `dev-flow-mcp/1.0.0`. The first supported
transport SHALL be STDIO. The server SHALL implement MCP initialization,
server instructions, tool discovery, and tool calls through the official Python MCP
SDK stable v2 line and SHALL negotiate the MCP protocol revision through that SDK.

The public launcher SHALL accept `--stdio` and the documented data-root and logging
configuration only. It SHALL reject HTTP, SSE, host, port, OAuth, token, or listening
socket options as unsupported. The first release SHALL NOT expose Streamable HTTP,
server-side sampling, elicitation, MCP task augmentation, remote repository access,
or cross-machine Controller state.

#### Scenario: A compatible client initializes the server

- **WHEN** a client starts the installed launcher over STDIO and sends a valid MCP initialize request
- **THEN** the server returns its stable name and release version, bounded global instructions, and the capabilities required for the approved tool catalog

#### Scenario: The client requests the tool catalog

- **WHEN** an initialized client invokes `tools/list`
- **THEN** the server returns exactly the stable `dev-flow-mcp/1.0.0` catalog with generated input schemas, declared output schemas, and explicit tool annotations

#### Scenario: A network transport is requested

- **WHEN** an operator starts the first-release server with an HTTP, SSE, host, port, OAuth, or remote-mode option
- **THEN** startup fails before opening a socket or constructing a Controller and reports that only local STDIO is supported

#### Scenario: The STDIO client disconnects

- **WHEN** the server receives clean EOF after initialization or tool use
- **THEN** it stops without mutating task state merely because the transport ended and leaves every persisted lease and task governed by the Controller

### Requirement: MCP and existing adapters share one Controller authority

Every MCP tool that inspects or mutates Dev Flow state SHALL call the existing
`Controller` application boundary directly or a bounded application adapter that
itself delegates to that Controller. The MCP server SHALL NOT invoke the JSON CLI,
parse CLI output, call the Web UI, write task files directly, or implement a parallel
workflow state machine.

The server SHALL resolve the same current data root and `0.4.0` model namespace as
the CLI. It SHALL preserve current task IDs, immutable repository membership,
membership leases, workflow identities, records, artifacts, action bindings,
revision compare-and-swap behavior, replay validation, assurance budgets, findings,
decisions, and Delivery Dossiers. The MCP result SHALL NOT expose the physical data
root.

#### Scenario: An existing task is read through MCP

- **WHEN** a valid model `0.4.0` task created by a `0.4.x` CLI or plugin installation is inspected through MCP
- **THEN** the server reads the same task without migration, translation, copying, or a new MCP-specific task record

#### Scenario: MCP applies an action

- **WHEN** `dev_flow_apply_action` receives a current action ID, payload, and exact binding
- **THEN** the existing Controller performs snapshot capture, validation, mutation, record sealing, and fresh projection generation exactly as it does for the CLI boundary

#### Scenario: Direct state access is attempted

- **WHEN** an MCP implementation path attempts to enumerate raw task files, replace task JSON, or bypass Controller validation
- **THEN** package validation or tests fail and the operation is not part of the supported MCP interface

### Requirement: The MCP dependency remains isolated from the core runtime

The supported installed runtime SHALL be 64-bit CPython `>=3.10,<3.15`. The MCP
adapter SHALL use the official `mcp` Python SDK stable v2 line with an upper major
bound and an exact resolved lock. SDK and transitive packages SHALL be installed in
an installer-owned isolated runtime outside the verified source checkout and outside
all Controller task-data roots.

Only modules below `src/dev_flow_orchestrator/mcp/` and their launch bootstrap MAY
import the MCP SDK or its transitive framework types. Controller, Engine, Store,
GitClient, workflow, delivery, review, snapshot, platform, CLI, and Web modules SHALL
remain importable without importing or starting MCP. No task schema or product model
identity SHALL include an MCP protocol or SDK version.

#### Scenario: Core modules are imported without the MCP runtime

- **WHEN** a core-only test environment imports Controller, Store, Engine, GitClient, CLI, and Web modules without installing the MCP dependency
- **THEN** those imports remain available and no MCP module is loaded as a side effect

#### Scenario: The installed Python is 3.9

- **WHEN** an installer finds only CPython 3.9
- **THEN** MCP installation fails before plugin activation with a bounded requirement for supported CPython 3.10–3.14 and does not modify existing task data

#### Scenario: The resolved MCP dependency drifts

- **WHEN** package validation detects a missing lock, an unsupported SDK major, or installed runtime metadata that differs from the candidate lock
- **THEN** validation or activation fails rather than running an unverified dependency set

### Requirement: STDOUT remains protocol-only

While the MCP server is running, every byte written to standard output SHALL belong
to the MCP transport selected by the SDK. Startup banners, progress text, warnings,
debug output, tracebacks, installer receipts, and application logs SHALL NOT be
written to standard output.

Diagnostics SHALL use standard error only. Default diagnostics SHALL be bounded and
SHALL NOT include task requirements, contract text, repository file content, raw
environment values, secrets, complete action bindings, complete payloads, or the
Controller data-root path. Each visible tool result and matching diagnostic SHALL use
a request ID where correlation is needed. The first release SHALL emit no telemetry
or network log export. One default diagnostic event SHALL be no larger than 4 KiB
UTF-8.

#### Scenario: A tool returns a domain failure

- **WHEN** a Controller operation raises a current `DevFlowError`
- **THEN** the MCP response is written through the protocol on stdout and a bounded optional diagnostic is written only to stderr

#### Scenario: An unexpected adapter exception occurs

- **WHEN** the MCP adapter raises an exception not classified as a current domain error
- **THEN** the client receives a redacted `INTERNAL_ERROR` with a request ID, the traceback is confined to stderr, and stdout remains parseable MCP traffic

#### Scenario: Protocol purity is validated

- **WHEN** the protocol test suite captures the server's raw stdout file descriptor across initialization, success, error, cancellation, and shutdown
- **THEN** any non-protocol byte fails the candidate

### Requirement: Concurrent MCP calls remain bounded and preserve Controller correctness

The server SHALL classify operations as stored reads, live captures, or mutations.
It SHALL bound process-local live Git captures, SHALL serialize mutations for the
same task before entering the Controller, and SHALL prevent unbounded queues or
thread creation. Calls for distinct tasks MAY overlap only where current Controller,
Store, Git, and repository-set semantics permit them.

The first interface SHALL admit at most four process-local live-capture or mutation
calls to the coordinator at once. Admission SHALL be immediate: excess calls SHALL
fail with the closed runtime-unavailable result and SHALL NOT wait in a request
queue. Stored reads that do not enter Git or mutation authority remain outside this
live-operation limit.

Process-local coordination SHALL NOT replace cross-process authority. Cross-process
correctness SHALL continue to come from the current task locks, membership lock,
repository snapshot stability, exact action binding, and revision compare-and-swap
rules. The server SHALL NOT claim multi-executor or parallel-action support merely
because MCP clients can issue concurrent requests.

#### Scenario: Two calls mutate the same task

- **WHEN** two MCP requests concurrently attempt mutations against one task revision
- **THEN** at most one current mutation commits and the other receives the current Controller conflict or stale-binding behavior with no partial record

#### Scenario: Two calls race to start overlapping tasks

- **WHEN** separate MCP processes request repository sets that share an active member
- **THEN** the existing membership lock admits at most one task and returns the committed owner identity to the rejected request

#### Scenario: Live requests exceed the process bound

- **WHEN** more live capture requests arrive than the configured bounded coordinator permits
- **THEN** excess work is rejected or bounded according to the documented runtime policy without creating an unbounded queue or mutating task state

### Requirement: Cancellation never fabricates rollback

The MCP adapter SHALL observe cooperative cancellation before an expensive capture,
between bounded capture phases where the Controller exposes a safe checkpoint, and
before entering a mutation commit where possible. Cancellation before a commit SHALL
return `REQUEST_CANCELLED` and SHALL NOT claim a mutation.

Once the Controller has committed, the server SHALL NOT represent transport
cancellation or disconnect as rollback. When completion cannot be established, the
result SHALL be `MCP_COMPLETION_UNCERTAIN` with a read-after-write recovery directive
that identifies the exact read tool and task identity needed to determine the
current authoritative state. MCP task augmentation SHALL be declared unsupported for
all tools.

#### Scenario: Cancellation occurs before Controller entry

- **WHEN** a request is cancelled before a mutation enters the Controller
- **THEN** the server returns `REQUEST_CANCELLED` and no task revision or record is added

#### Scenario: Cancellation occurs during a bounded Git capture

- **WHEN** a live capture observes cancellation before the Controller commit boundary
- **THEN** the capture is stopped through current process-cancellation behavior and no partial snapshot or task record is accepted

#### Scenario: The transport disappears after a possible commit

- **WHEN** the client disconnects after the Controller may have committed but before it receives the response
- **THEN** the server and documentation require a fresh task read or next-action read and never instruct blind replay of the mutation

### Requirement: MCP transport failures use a closed error boundary

Unknown tools and malformed MCP messages SHALL use SDK-managed protocol errors.
Transport input that fails the generated tool schema SHALL fail before Controller
entry. Current `DevFlowError` values SHALL retain their existing code, message, and
bounded details inside the MCP error envelope. Unexpected adapter failures SHALL use
a closed MCP runtime code rather than a fabricated domain code.

The MCP runtime code set SHALL initially be limited to `MCP_RUNTIME_UNAVAILABLE`,
`MCP_DEPENDENCY_INVALID`, `MCP_RESULT_LIMIT`, `REQUEST_CANCELLED`,
`MCP_COMPLETION_UNCERTAIN`, and `INTERNAL_ERROR`. Adding or changing a code SHALL
require an MCP interface version review.

#### Scenario: Tool arguments are malformed

- **WHEN** a caller omits a required field, supplies an unknown field, violates a declared bound, or uses the wrong JSON type
- **THEN** schema validation rejects the call before Controller construction or mutation

#### Scenario: A Controller error is returned

- **WHEN** a current domain operation raises `ACTION_BINDING_STALE`, `REVISION_CONFLICT`, `WORKSPACE_CHANGED`, or another `DevFlowError`
- **THEN** the client receives that exact domain code with a bounded recovery directive and no protocol-level success claim

#### Scenario: An unrecognized internal condition occurs

- **WHEN** an adapter condition cannot be mapped to the closed runtime or domain code set
- **THEN** the response uses `INTERNAL_ERROR`, redacts implementation detail, and records a request ID for stderr correlation
