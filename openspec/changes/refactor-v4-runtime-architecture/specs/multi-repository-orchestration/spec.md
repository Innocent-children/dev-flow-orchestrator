## ADDED Requirements

### Requirement: Repository topology does not determine workflow depth
The multi-repository orchestration capability SHALL be available to both
`full@4` and `lite@4`. Its plan, ownership, DAG, lease, result, barrier and
integration contracts MUST be selected by repository topology, while workflow
depth determines only which additional workflow gates surround those shared
operations.

#### Scenario: Run lite across repositories
- **WHEN** a `lite@4` task selects multiple repositories
- **THEN** it uses the shared repository kernel without acquiring full-only baseline, impact, route, managed-worktree planning or independent-review nodes

#### Scenario: Run full across repositories
- **WHEN** a `full@4` task selects multiple repositories
- **THEN** it uses the same repository kernel plus the full workflow's declared gates

### Requirement: The greenfield repository kernel begins with a minimal contract
The first multi-repository greenfield slice SHALL implement only canonical
repository identity, deterministic repository ordering, exclusive
repository-scoped ownership and one current result barrier. Lease,
concurrency, retry, cancellation and recovery MUST be added as later explicit
nodes rather than prebuilt framework layers.

#### Scenario: Build the first repository set
- **WHEN** a task supplies two distinct Git repositories
- **THEN** the kernel records a canonical ordered set, derives the manager actor from controller-owned task/session and local-account context without accepting a caller owner map or claiming authenticated-human identity, and creates one barrier bound to that set

#### Scenario: Request an unimplemented orchestration node
- **WHEN** a pre-cutover focused test requests a repository capability not yet included in the greenfield slice
- **THEN** the new runtime reports that the node is absent and does not delegate to the old orchestration service

### Requirement: Shared repository nodes retain one authority model
Lite and full SHALL use the same repository node implementation and authority
contract for equivalent repository effects. Workflow-specific gates MAY
authorize entry to that node but MUST NOT duplicate its ownership, CAS,
idempotency, result or barrier validation.

#### Scenario: Compare equivalent repository effects
- **WHEN** lite and full dispatch the same repository-scoped operation
- **THEN** both resolve the same node contract, state-write set and effect port

#### Scenario: Duplicate workflow-specific validation
- **WHEN** a lite- or full-specific layer reimplements repository ownership or result CAS
- **THEN** architecture review rejects the duplicated invariant

#### Scenario: Caller attempts to choose a lease owner
- **WHEN** repository plan input includes an owner or actor identity
- **THEN** payload validation rejects it before conversation-request creation, lease creation or state mutation
