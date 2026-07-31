## ADDED Requirements

### Requirement: Lite enters the shared repository kernel without a workflow approval
A multi-repository `lite@4` task SHALL enter the shared repository-plan, lease,
result, barrier and integration kernel immediately after preflight. Removing
the Lite workflow-specific approval MUST NOT remove, duplicate or weaken any
authority, ownership, pinned-HEAD, CAS, retry, cancellation, result or recovery
contract declared by the shared repository nodes.

#### Scenario: Enter Lite repository planning
- **WHEN** Lite preflight records the exact multi-repository Git baseline
- **THEN** the controller advances to the same `repository-plan` contract used by Full after its full-only gates

#### Scenario: Compare shared node contracts
- **WHEN** Full and Lite reach an equivalent repository operation
- **THEN** both resolve the same action, authority, write set, effect port and recovery contract

#### Scenario: Require a repository-node confirmation
- **WHEN** a shared repository action itself declares a grant beyond task revision
- **THEN** Lite requests the same durable exact conversation confirmation as Full even though Lite entry required no approval
