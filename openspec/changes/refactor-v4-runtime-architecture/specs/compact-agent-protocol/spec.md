## MODIFIED Requirements

### Requirement: Agent projections expose only the current actionable frontier
The controller SHALL provide a versioned `agent-v1` task projection containing
task ID, current revision, exact V4 workflow/profile identity, current node or
ready frontier, legal next actions, required state sections, confirmation mode
and bounded artifact locators. The projection MUST be derived from the same
greenfield product catalog and live schema-v4 state used by transition
validation and MUST NOT contain unrelated task history, repository index data
or predecessor inspection fields.

#### Scenario: Read a single actionable node
- **WHEN** a current V4 task has one legal next action
- **THEN** `agent-v1` returns that action and only the fields declared by its node contract

#### Scenario: Read a parallel frontier
- **WHEN** multiple independent repository node instances are ready
- **THEN** `agent-v1` returns a deterministically ordered frontier with stable node-instance and repository identities

#### Scenario: Encounter no legal action
- **WHEN** a task is blocked, terminal or waiting for approval
- **THEN** the projection reports that exact current condition without inventing a next action

#### Scenario: Detect catalog and state disagreement
- **WHEN** the pinned current V4 bundle cannot explain the live node
- **THEN** the controller returns a structured current-contract blocker and no action projection

## ADDED Requirements

### Requirement: Mutation receipts are action-scoped and V4-only
Every greenfield mutation SHALL return a bounded V4 receipt containing task ID,
committed revision, exact action ID, changed section identities, current node
or status, action result summary and next-action locator. The runtime MUST NOT
emit a legacy response branch when a compact profile is omitted.

#### Scenario: Receive a successful mutation
- **WHEN** a greenfield action commits
- **THEN** its receipt contains the committed revision and sufficient next-action data without a duplicate full state snapshot

#### Scenario: Lose a receipt
- **WHEN** a caller cannot retain a successful receipt
- **THEN** it reloads the current schema-v4 task projection and does not request a compatibility response

## REMOVED Requirements

### Requirement: Mutation receipts are action-scoped and backward compatible
**Reason**: backward-compatible schema-v1/v2 response behavior conflicts with
the V4-only greenfield product.

**Migration**: 无 historical caller；所有 adapter 使用 current V4 receipt。
