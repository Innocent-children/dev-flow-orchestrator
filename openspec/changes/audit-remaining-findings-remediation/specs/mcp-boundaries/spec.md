## ADDED Requirements

### Requirement: MCP framing isolates bounded malformed JSON

The STDIO boundary SHALL convert decoder recursion and controlled parse failures below
the byte limit into invalid messages, continue with following requests, and SHALL NOT
catch process-control or memory exceptions or log the complete payload.

#### Scenario: Deep JSON precedes initialize

- **WHEN** one or more deeply nested bounded messages precede a valid initialize
- **THEN** the server SHALL remain alive and respond to initialize with bounded stderr

### Requirement: Current-action schemas preserve nested authority

Published active and terminal current-action alternatives SHALL be mutually exclusive,
closed for authoritative fields, and require task identity/revision/status, a non-empty
repository set, node, action identity and payload contract, exact binding, and required
guidance for active results.

#### Scenario: Nested authority is incomplete

- **WHEN** an active result has an empty task/repository/action, missing or malformed
  binding, terminal conflict, or unknown authoritative property
- **THEN** output validation SHALL reject it, including mutation results' `current`

### Requirement: MCP cancellation reaches Git children

Each live MCP read or mutation SHALL use a request-scoped signal with the existing
`GitClient.cancellation` context, mapped from protocol cancellation, AnyIO cancellation,
and peer close, while retaining existing pre/post-commit completion semantics.

#### Scenario: Cancellation occurs during blocking Git

- **WHEN** cancellation or EOF occurs before commit while Git is running
- **THEN** the child and coordinator work SHALL end promptly and persisted revision SHALL
  remain unchanged

### Requirement: Mutation output failure preserves uncertainty

The outer output guard SHALL retain the original request/tool/task context and return
`MCP_COMPLETION_UNCERTAIN`, the accurate read-after-write tool, and `blind_retry=false`
when a mutation result fails after application mutation entry.

#### Scenario: Post-processing corrupts a committed mutation result

- **WHEN** outer validation fails after mutation entry
- **THEN** the correlated response SHALL state only that completion is unknown and SHALL
  direct an authoritative read before retry

### Requirement: Catalog identity covers the observable tool interface

One canonical helper shared by catalog production and runtime self-check SHALL hash tool
name, description, input schema, output schema, annotations, and observable execution or
meta fields, independent of map or tool ordering.

#### Scenario: Observable catalog semantics change

- **WHEN** any observable field changes semantically
- **THEN** the digest SHALL change, while canonical-equivalent ordering SHALL not
